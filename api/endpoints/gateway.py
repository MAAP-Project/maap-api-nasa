import logging
import secrets
from datetime import datetime, timezone, timedelta

import hashlib
import requests
from flask import request
from flask_api import status
from flask_restx import Resource

import api.settings as settings
from api import constants
from api.restplus import api
from api.auth.security import get_authorized_user, login_required, verify_jwt_token
from api.maap_database import db
from api.models.member import Member
from api.models.personal_access_token import PersonalAccessToken
from api.utils.esa_client import ESATokenClient
from api.utils.http_util import err_response

log = logging.getLogger(__name__)
ns = api.namespace('gateway', description='Joint NASA/ESA token exchange operations')

HEADER_API_KEY = "X-MAAP-API-Key"
HEADER_USER_IDENTIFIER = "X-MAAP-User-Identifier"
HEADER_USER_ORIGIN = "X-MAAP-User-Origin"


def _hash_token(raw_token):
    """Hash a token using SHA-256 for storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _validate_admin_api_key():
    """Validate the X-MAAP-API-Key header against known partner admin keys.
    Returns True if the key is valid, False otherwise."""
    api_key = request.headers.get(HEADER_API_KEY, "")
    if not api_key:
        return False
    return api_key in (settings.NASA_ADMIN_API_KEY, settings.ESA_ADMIN_API_KEY) and api_key != ""


def _get_admin_identity():
    """Extract and validate admin caller identity from headers.
    Returns (user_identifier, user_origin) tuple or None on failure."""
    if not _validate_admin_api_key():
        return None

    user_identifier = request.headers.get(HEADER_USER_IDENTIFIER)
    user_origin = request.headers.get(HEADER_USER_ORIGIN)

    if not user_identifier or not user_origin:
        return None

    return user_identifier, user_origin


def _is_jwt_auth():
    """Check if the current request is authenticated via JWT (not a personal access token)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        return verify_jwt_token(token) is not None

    # proxy-ticket or cpticket with jwt: prefix
    for header_name in ("proxy-ticket", "cpticket"):
        value = request.headers.get(header_name, "")
        if value.lower().startswith("jwt:"):
            return verify_jwt_token(value) is not None

    return False


def _verify_member_exists(user_identifier):
    """Check that a member with the given email exists and is active.
    Returns the Member or None."""
    return (
        db.session.query(Member)
        .filter_by(email=user_identifier, status=constants.STATUS_ACTIVE)
        .first()
    )


def _create_token_for_user(user_identifier, user_origin):
    """Core token creation logic shared by self-service and admin endpoints."""
    req_data = request.get_json()
    if not isinstance(req_data, dict):
        return err_response("Valid JSON body object required.")

    token_name = req_data.get("token_name", "")
    expires_in = req_data.get("expires_in")

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)

    # Calculate expiration
    expires_at = None
    if expires_in is not None:
        if not isinstance(expires_in, int) or expires_in <= 0:
            return err_response("expires_in must be a positive integer (seconds).")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    elif settings.TOKEN_DEFAULT_EXPIRY_SECONDS > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.TOKEN_DEFAULT_EXPIRY_SECONDS
        )

    pat = PersonalAccessToken(
        user_identifier=user_identifier,
        user_origin=user_origin,
        token_name=token_name if token_name else None,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    try:
        db.session.add(pat)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.error(f"Failed to create personal access token: {e}")
        return err_response("Failed to create token.", status.HTTP_500_INTERNAL_SERVER_ERROR)

    return {
        "token": raw_token,
        "token_id": pat.token_id,
        "token_name": pat.token_name,
        "expires_at": pat.expires_at.isoformat() if pat.expires_at else None,
    }, status.HTTP_201_CREATED


def _list_tokens_for_user(user_identifier, user_origin=None, check_member=False):
    """Core token listing logic shared by self-service and admin endpoints."""
    if check_member and _verify_member_exists(user_identifier) is None:
        return err_response("User not found.", status.HTTP_404_NOT_FOUND)

    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    size = min(size, 100)

    query = (
        db.session.query(PersonalAccessToken)
        .filter_by(user_identifier=user_identifier)
        .filter(PersonalAccessToken.revoked_at.is_(None))
        .order_by(PersonalAccessToken.created_at.desc())
    )
    if user_origin is not None:
        query = query.filter_by(user_origin=user_origin)

    tokens = query.offset((page - 1) * size).limit(size).all()

    return [
        {
            "token_id": t.token_id,
            "token_name": t.token_name,
            "user_origin": t.user_origin,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "is_active": t.is_active,
        }
        for t in tokens
    ]


def _revoke_token_for_user(token_id, user_identifier, user_origin):
    """Core token revocation logic shared by self-service and admin endpoints."""
    pat = (
        db.session.query(PersonalAccessToken)
        .filter_by(token_id=token_id, user_identifier=user_identifier, user_origin=user_origin)
        .filter(PersonalAccessToken.revoked_at.is_(None))
        .first()
    )

    if pat is None:
        return err_response("Token not found or already revoked.", status.HTTP_404_NOT_FOUND)

    pat.revoked_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.error(f"Failed to revoke token {token_id}: {e}")
        return err_response("Failed to revoke token.", status.HTTP_500_INTERNAL_SERVER_ERROR)

    return "", status.HTTP_204_NO_CONTENT


# =============================================================================
# ESA delegation: self-service requests targeting the ESA platform are proxied
# to ESA's gateway (via the NASA admin API key) rather than stored locally.
# =============================================================================

def _requested_origin():
    """The platform origin the caller is targeting, from the X-MAAP-User-Origin header."""
    return request.headers.get(HEADER_USER_ORIGIN, "")


def _is_esa_origin(origin):
    """True if the requested origin identifies the ESA platform."""
    return bool(settings.ESA_OIDC_ORIGIN) and origin == settings.ESA_OIDC_ORIGIN


def _esa_not_configured():
    """Return an err_response if ESA delegation isn't fully configured, else None."""
    if not settings.ESA_GATEWAY_BASE_URL:
        return err_response("ESA gateway is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if not settings.ESA_ADMIN_API_KEY:
        return err_response("ESA admin API key is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


def _esa_error_detail(e):
    """Human-readable detail for an ESA gateway request failure: the upstream
    status and (truncated) response body when there was a response, otherwise
    the connection-level error."""
    resp = getattr(e, "response", None)
    if resp is not None:
        body = (resp.text or "").strip().replace("\n", " ")
        return f"ESA gateway returned {resp.status_code}: {body[:300]}"
    return f"Could not reach ESA gateway: {e}"


def _create_esa_token(user_identifier):
    """Delegate token creation to ESA's gateway for a NASA-authenticated user."""
    not_configured = _esa_not_configured()
    if not_configured is not None:
        return not_configured

    req_data = request.get_json()
    if not isinstance(req_data, dict):
        return err_response("Valid JSON body object required.")

    token_name = req_data.get("token_name") or None
    expires_in = req_data.get("expires_in")
    if expires_in is not None and (not isinstance(expires_in, int) or expires_in <= 0):
        return err_response("expires_in must be a positive integer (seconds).")

    try:
        result = ESATokenClient().create_token(
            user_identifier, token_name=token_name, expires_in=expires_in
        )
    except requests.RequestException as e:
        detail = _esa_error_detail(e)
        log.error(f"Failed to create ESA token for {user_identifier}: {detail}")
        return err_response(f"Failed to create ESA token. {detail}", status.HTTP_502_BAD_GATEWAY)

    return result, status.HTTP_201_CREATED


def _list_esa_tokens(user_identifier):
    """List the user's ESA tokens, tagged with the ESA origin so callers can
    distinguish them. Returns [] (logging a warning) if ESA is unavailable so
    the local listing still succeeds."""
    if _esa_not_configured() is not None:
        return []

    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)

    # Our API (and the NASA local query) is 1-based; ESA's gateway paginates
    # 0-based, so page=1 would ask ESA for its *second* page and return nothing
    # for users with fewer than `size` tokens. Translate to ESA's convention.
    esa_page = max(page - 1, 0)

    try:
        esa_tokens = ESATokenClient().list_tokens(user_identifier, page=esa_page, size=size)
    except requests.RequestException as e:
        log.warning(f"Failed to list ESA tokens for {user_identifier}: {_esa_error_detail(e)}")
        return []

    return [
        {
            "token_id": t.get("token_id"),
            "token_name": t.get("token_name"),
            "user_origin": settings.ESA_OIDC_ORIGIN,
            "expires_at": t.get("expires_at"),
            "created_at": t.get("created_at"),
            "is_active": t.get("is_active", True),
        }
        for t in esa_tokens
    ]


def _revoke_esa_token(token_id, user_identifier):
    """Delegate token revocation to ESA's gateway for a NASA-authenticated user."""
    not_configured = _esa_not_configured()
    if not_configured is not None:
        return not_configured

    try:
        ESATokenClient().revoke_token(user_identifier, token_id)
    except requests.HTTPError as e:
        resp_code = e.response.status_code if e.response is not None else None
        if resp_code == status.HTTP_404_NOT_FOUND:
            return err_response("Token not found or already revoked.", status.HTTP_404_NOT_FOUND)
        detail = _esa_error_detail(e)
        log.error(f"Failed to revoke ESA token {token_id} for {user_identifier}: {detail}")
        return err_response(f"Failed to revoke ESA token. {detail}", status.HTTP_502_BAD_GATEWAY)
    except requests.RequestException as e:
        detail = _esa_error_detail(e)
        log.error(f"Failed to revoke ESA token {token_id} for {user_identifier}: {detail}")
        return err_response(f"Failed to revoke ESA token. {detail}", status.HTTP_502_BAD_GATEWAY)

    return "", status.HTTP_204_NO_CONTENT


# =============================================================================
# Self-service endpoints: authenticated user manages their own tokens
# =============================================================================

@ns.route('/members/self/tokens')
class SelfTokens(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """Create a personal access token for the authenticated user. Requires JWT authentication."""
        if not _is_jwt_auth():
            return err_response("JWT authentication required to create tokens.", status.HTTP_403_FORBIDDEN)

        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email

        # An ESA-targeted request is delegated to ESA's gateway; otherwise the
        # token is created locally with the NASA origin.
        if _is_esa_origin(_requested_origin()):
            return _create_esa_token(user_identifier)

        user_origin = settings.NASA_CAS_OIDC_ORIGIN
        return _create_token_for_user(user_identifier, user_origin)

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):
        """List personal access tokens for the authenticated user (all origins)."""
        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email
        # "All origins" = locally-stored NASA tokens plus the user's ESA tokens
        # fetched from ESA's gateway.
        return _list_tokens_for_user(user_identifier) + _list_esa_tokens(user_identifier)


@ns.route('/members/self/tokens/<string:token_id>')
class SelfTokenRevoke(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, token_id):
        """Revoke a personal access token for the authenticated user. Requires JWT authentication."""
        if not _is_jwt_auth():
            return err_response("JWT authentication required to delete tokens.", status.HTTP_403_FORBIDDEN)

        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email

        # Route ESA-targeted revocations to ESA's gateway; otherwise revoke the
        # locally-stored NASA token.
        if _is_esa_origin(_requested_origin()):
            return _revoke_esa_token(token_id, user_identifier)

        user_origin = settings.NASA_CAS_OIDC_ORIGIN
        return _revoke_token_for_user(token_id, user_identifier, user_origin)


# =============================================================================
# Admin endpoints: partner platform manages tokens on behalf of a user
# =============================================================================

@ns.route('/members/tokens')
class AdminTokens(Resource):

    def post(self):
        """Create a personal access token on behalf of a user (admin/partner platform).

        Required headers:
            X-MAAP-API-Key: Admin API key for the calling platform
            X-MAAP-User-Identifier: Email/ID of the target user
            X-MAAP-User-Origin: OIDC origin URL of the target user's platform
        """
        identity = _get_admin_identity()
        if identity is None:
            return err_response("Missing or invalid authorization.", status.HTTP_403_FORBIDDEN)

        user_identifier, user_origin = identity
        return _create_token_for_user(user_identifier, user_origin)

    def get(self):
        """List personal access tokens for a user (admin/partner platform).

        Required headers:
            X-MAAP-API-Key: Admin API key for the calling platform
            X-MAAP-User-Identifier: Email/ID of the target user
            X-MAAP-User-Origin: OIDC origin URL of the target user's platform
        """
        identity = _get_admin_identity()
        if identity is None:
            return err_response("Missing or invalid authorization.", status.HTTP_403_FORBIDDEN)

        user_identifier, user_origin = identity
        return _list_tokens_for_user(user_identifier, user_origin, check_member=True)


@ns.route('/members/tokens/<string:token_id>')
class AdminTokenRevoke(Resource):

    def delete(self, token_id):
        """Revoke a personal access token for a user (admin/partner platform).

        Required headers:
            X-MAAP-API-Key: Admin API key for the calling platform
            X-MAAP-User-Identifier: Email/ID of the target user
            X-MAAP-User-Origin: OIDC origin URL of the target user's platform
        """
        identity = _get_admin_identity()
        if identity is None:
            return err_response("Missing or invalid authorization.", status.HTTP_403_FORBIDDEN)

        user_identifier, user_origin = identity
        return _revoke_token_for_user(token_id, user_identifier, user_origin)
