import logging
import secrets
from datetime import datetime, timezone, timedelta

import hashlib
from flask import request
from flask_api import status
from flask_restx import Resource

import api.settings as settings
from api import constants
from api.restplus import api
from api.auth.security import get_authorized_user, login_required
from api.maap_database import db
from api.models.member import Member
from api.models.personal_access_token import PersonalAccessToken
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


def _list_tokens_for_user(user_identifier, user_origin, check_member=False):
    """Core token listing logic shared by self-service and admin endpoints."""
    if check_member and _verify_member_exists(user_identifier) is None:
        return err_response("User not found.", status.HTTP_404_NOT_FOUND)

    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    size = min(size, 100)

    query = (
        db.session.query(PersonalAccessToken)
        .filter_by(user_identifier=user_identifier, user_origin=user_origin)
        .filter(PersonalAccessToken.revoked_at.is_(None))
        .order_by(PersonalAccessToken.created_at.desc())
    )

    tokens = query.offset((page - 1) * size).limit(size).all()

    return [
        {
            "token_id": t.token_id,
            "token_name": t.token_name,
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
# Self-service endpoints: authenticated user manages their own tokens
# =============================================================================

@ns.route('/members/self/tokens')
class SelfTokens(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """Create a personal access token for the authenticated user."""
        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email
        user_origin = settings.NASA_CAS_OIDC_ORIGIN
        return _create_token_for_user(user_identifier, user_origin)

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):
        """List personal access tokens for the authenticated user."""
        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email
        user_origin = settings.NASA_CAS_OIDC_ORIGIN
        return _list_tokens_for_user(user_identifier, user_origin)


@ns.route('/members/self/tokens/<string:token_id>')
class SelfTokenRevoke(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, token_id):
        """Revoke a personal access token for the authenticated user."""
        authorized_user = get_authorized_user()
        if authorized_user is None:
            return err_response("Could not identify user.", status.HTTP_401_UNAUTHORIZED)

        user_identifier = authorized_user.email
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
