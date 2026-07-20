import hashlib
from functools import wraps
import requests
from flask import request, abort
from flask_api import status
from werkzeug.exceptions import HTTPException
from api import settings, constants
from api.utils.security_utils import AuthenticationError, ExternalServiceError
from api.auth.cas_auth import start_member_session_jwt, validate_proxy, validate_third_party, get_urs_token
from api.maap_database import db
from api.models.member import Member
from api.models.personal_access_token import PersonalAccessToken
from api.models.role import Role
import jwt
from jwt import PyJWKClient

HEADER_PROXY_TICKET = "proxy-ticket"
THIRD_PARTY_AUTH_HEADER_GITLAB = "X-Gitlab-Token"
HEADER_CP_TICKET = "cpticket"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CAS_AUTHORIZATION = "cas-authorization"
HEADER_DPS_TOKEN = "dps-token"
HEADER_MAAP_API_KEY = "X-MAAP-API-Key"


def get_authorized_user():
    auth_header_name = get_auth_header()
    auth_header_value = request.headers.get(auth_header_name) if auth_header_name else None

    try:
        if auth_header_name == HEADER_PROXY_TICKET or auth_header_name == HEADER_CP_TICKET:

            if auth_header_value and auth_header_value.lower().startswith('jwt:'):
                decoded = verify_jwt_token(auth_header_value)
                if not decoded:
                    raise AuthenticationError("Invalid or expired jwt token.")

                _member = start_member_session_jwt(decoded, auth_header_value)

                return _member
            else:
                member_session = validate_proxy(auth_header_value)
                if member_session is not None:
                    return member_session.member

                # Not a valid proxy ticket — try as a personal access token
                _member = validate_personal_access_token(auth_header_value)
                if _member is not None:
                    return _member
        elif auth_header_name == HEADER_AUTHORIZATION:
            if auth_header_value and auth_header_value.lower().startswith('bearer '):
                token = auth_header_value.split(" ")[1]

                # Try JWT first, then fall back to personal access token
                decoded = verify_jwt_token(token)
                if decoded:
                    _member = start_member_session_jwt(decoded, token)
                    return _member

                # Not a valid JWT — try as a personal access token
                _member = validate_personal_access_token(token)
                if _member is not None:
                    return _member

                raise AuthenticationError("Invalid or expired token.")
            else: # Malformed Authorization header
                raise AuthenticationError("Malformed Authorization header.")

        elif auth_header_name == HEADER_MAAP_API_KEY:
            # Personal access token passed directly via X-MAAP-API-Key
            _member = validate_personal_access_token(auth_header_value)
            if _member is not None:
                return _member
            raise AuthenticationError("Invalid or expired API key.")

        # If no valid auth method found or successfully processed
        return None

    except AuthenticationError as e:
        # Log the auth error specifically if needed, then re-raise or let it propagate
        # For get_authorized_user, it might be better to return None and let login_required handle abort
        # However, if we want to abort immediately on auth errors even when just "getting" user,
        # then abort here. For now, let it return None on failure.
        # current_app.logger.warning(f"Authentication failed in get_authorized_user: {e.description}")
        return None # Or re-raise e if callers should handle it
    except ExternalServiceError as e:
        # Similar to AuthenticationError, decide whether to abort or return None.
        # current_app.logger.error(f"External service error in get_authorized_user: {e.description}")
        return None # Or re-raise e
    except Exception: # Catch any other unexpected error during auth processing
        # current_app.logger.error(f"Unexpected error in get_authorized_user: {e}", exc_info=True)
        return None

def _authorize_jwt_member(decoded, token_string, role):
    """Resolve the member behind a validated Keycloak JWT (auto-creating a
    suspended-guest record on first touch, matching the CAS-era flow) and
    enforce the required role, mirroring the CAS-proxy and PAT paths.

    Returns the member. A None member (auto-creation failure) is tolerated
    only for GUEST-level endpoints; anything higher raises."""
    member = start_member_session_jwt(decoded, token_string)
    if member is None:
        if role <= Role.ROLE_GUEST:
            return None
        raise AuthenticationError("Insufficient permissions.")
    if member.role_id is None or member.role_id < role:
        raise AuthenticationError("Insufficient permissions.")
    return member


def validate_personal_access_token(raw_token):
    """Validate a personal access token and return the corresponding Member.

    Hashes the raw token, looks it up in personal_access_token,
    verifies it is active (not revoked, not expired), then joins
    against the member table via user_identifier = member.email
    to confirm the member exists and has status = 'active'.

    Returns the Member on success, or None on failure.
    """
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    pat = (
        db.session.query(PersonalAccessToken)
        .filter_by(token_hash=token_hash)
        .filter(PersonalAccessToken.revoked_at.is_(None))
        .first()
    )

    if pat is None or not pat.is_active:
        return None

    member = (
        db.session.query(Member)
        .filter_by(email=pat.user_identifier, status=constants.STATUS_ACTIVE)
        .first()
    )

    return member


def authenticate_third_party():
    def authenticate_third_party_outer(wrapped_function):
        @wraps(wrapped_function)
        def wrap(*args, **kwargs):
            if THIRD_PARTY_AUTH_HEADER_GITLAB in request.headers and validate_third_party(request.headers[THIRD_PARTY_AUTH_HEADER_GITLAB]):
                return wrapped_function(*args, **kwargs)

            abort(status.HTTP_401_UNAUTHORIZED, description="Not authorized.")

        return wrap
    return authenticate_third_party_outer

def login_required(role=Role.ROLE_GUEST):
    def login_required_outer(wrapped_function):
        @wraps(wrapped_function)
        def wrap(*args, **kwargs):
            auth_header_name = get_auth_header()
            auth_header_value = request.headers.get(auth_header_name) if auth_header_name else None

            try:
                if auth_header_name == HEADER_PROXY_TICKET or auth_header_name == HEADER_CP_TICKET:

                    if auth_header_value and auth_header_value.lower().startswith('jwt:'):
                        decoded = verify_jwt_token(auth_header_value)
                        if not decoded:
                            raise AuthenticationError("Invalid or expired jwt token.")

                        # Resolve the member (auto-creating on first touch) and
                        # enforce the endpoint's required role — a valid JWT
                        # alone no longer satisfies elevated-role endpoints.
                        _authorize_jwt_member(decoded, auth_header_value, role)
                        return wrapped_function(*args, **kwargs)
                    
                    member_session = validate_proxy(auth_header_value) # Can raise Auth/ExternalServiceError
                    if member_session is not None and member_session.member.role_id >= role:
                        return wrapped_function(*args, **kwargs)
                    elif member_session is None: # Valid proxy ticket, but no session or role mismatch
                        raise AuthenticationError("Invalid session or insufficient permissions.")

                elif auth_header_name == HEADER_AUTHORIZATION:
                    if auth_header_value and auth_header_value.lower().startswith('bearer '):
                        token = auth_header_value.split(" ")[1]

                        # Try JWT first
                        decoded = verify_jwt_token(token)
                        if decoded:
                            _authorize_jwt_member(decoded, token, role)
                            return wrapped_function(*args, **kwargs)

                        # Not a valid JWT — try as a personal access token
                        _member = validate_personal_access_token(token)
                        if _member is not None and _member.role_id >= role:
                            return wrapped_function(*args, **kwargs)
                        elif _member is not None:
                            raise AuthenticationError("Insufficient permissions.")

                        raise AuthenticationError("Invalid or expired token.")

                    else: # Malformed Authorization header
                        raise AuthenticationError("Malformed Authorization header.")

                elif auth_header_name == HEADER_MAAP_API_KEY:
                    # Personal access token passed via X-MAAP-API-Key
                    _member = validate_personal_access_token(auth_header_value)
                    if _member is not None and _member.role_id >= role:
                        return wrapped_function(*args, **kwargs)
                    elif _member is not None:
                        raise AuthenticationError("Insufficient permissions.")
                    raise AuthenticationError("Invalid or expired API key.")

                elif auth_header_name == HEADER_CAS_AUTHORIZATION:
                    # Validate CAS SECRET KEY
                    is_valid = bool(auth_header_value == settings.CAS_SECRET_KEY)
                    if not is_valid:
                        raise AuthenticationError("Invalid CAS secret key.")
                    else:
                        # This auth method is a service-to-service request. Proceed with invocation
                        return wrapped_function(*args, **kwargs)

                elif auth_header_name == HEADER_DPS_TOKEN and valid_dps_request():
                    # DPS token implies a trusted internal service, often with admin-like privileges or specific operational rights.
                    return wrapped_function(*args, **kwargs)

                # If none of the above conditions were met and returned, it's an authorization failure.
                # This will be caught by the AuthenticationError catch block if an error was raised,
                # or fall through to a generic 403 if no specific auth error was raised but access not granted.
                raise AuthenticationError("No valid authentication credentials provided or processed.")

            except AuthenticationError as e:
                # Flask-RESTPlus will handle Werkzeug exceptions.
                # We ensure AuthenticationError inherits from werkzeug.exceptions.Unauthorized (401)
                abort(status.HTTP_401_UNAUTHORIZED, description=e.description or "Authentication failed.")
            except ExternalServiceError as e:
                # ExternalServiceError inherits from werkzeug.exceptions.ServiceUnavailable (503)
                abort(status.HTTP_503_SERVICE_UNAVAILABLE, description=e.description or "Authentication service unavailable.")
            except HTTPException as http_err:
                # CAtch any Werkzeig exceptions
                abort(http_err.code, description=http_err.description)
            except Exception as e:
                # Catch any other unexpected errors during the auth process
                # Log this error, as it's unexpected.
                # current_app.logger.error(f"Unexpected error in login_required decorator: {e}", exc_info=True)
                abort(status.HTTP_500_INTERNAL_SERVER_ERROR, description="An unexpected error occurred during authentication.")

            # Fallback if no auth method succeeded and no specific exception was caught and aborted.
            # This line should ideally not be reached if logic above is complete.
            abort(status.HTTP_403_FORBIDDEN, description="You are not authorized to access this resource.")

        return wrap
    return login_required_outer

def valid_dps_request():
    if HEADER_DPS_TOKEN in request.headers:
        return settings.DPS_MACHINE_TOKEN == request.headers[HEADER_DPS_TOKEN]
    return False


def get_auth_header():
    if HEADER_PROXY_TICKET in request.headers:
        return HEADER_PROXY_TICKET
    if HEADER_CP_TICKET in request.headers:
        return HEADER_CP_TICKET
    if HEADER_AUTHORIZATION in request.headers:
        return HEADER_AUTHORIZATION
    if HEADER_CAS_AUTHORIZATION in request.headers:
        return HEADER_CAS_AUTHORIZATION
    if HEADER_DPS_TOKEN in request.headers:
        return HEADER_DPS_TOKEN
    if HEADER_MAAP_API_KEY in request.headers:
        return HEADER_MAAP_API_KEY
    return None


def edl_federated_request(url, stream_response=False):
    s = requests.Session()
    response = s.get(url, stream=stream_response)

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        maap_user = get_authorized_user()

        if maap_user is not None:
            urs_token = get_urs_token(maap_user.id)
            s.headers.update({'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
                              'Connection': 'close'})

            response = s.get(url=response.url, stream=stream_response)

    return response

# --- HELPER FUNCTION TO VALIDATE JWT ---
def verify_jwt_token(token):
    try:
        if token.startswith("jwt:"):
            token = token[4:]

        # Fetch JWKS keys from Keycloak
        jwks_client = PyJWKClient(settings.KEYCLOAK_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Decode and validate the token
        try:
            decoded_token = jwt_decode(token, signing_key, True)
        except:
            # Retry without expiration validation
            decoded_token = jwt_decode(token, signing_key, False)
            
        return decoded_token
    except Exception as e:
        print("JWT validation error:", e)
        return None

def jwt_decode(token, signing_key, verify_exp):
    decoded_token = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.JWT_AUDIENCE,
                options={"verify_exp": verify_exp}
            )
    return decoded_token
