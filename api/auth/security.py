from functools import wraps
import requests
from flask import request, abort
from flask_api import status
from werkzeug.exceptions import HTTPException
from api import settings
from api.utils.security_utils import AuthenticationError, ExternalServiceError
from api.auth.cas_auth import validate_proxy, validate_bearer, validate_cas_request, validate_third_party
from api.maap_database import db
from api.models.member import Member
from api.models.role import Role

HEADER_PROXY_TICKET = "proxy-ticket"
THIRD_PARTY_AUTH_HEADER_GITLAB = "X-Gitlab-Token"
HEADER_CP_TICKET = "cpticket"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CAS_AUTHORIZATION = "cas-authorization"
HEADER_DPS_TOKEN = "dps-token"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_SUSPENDED = "suspended"


def get_authorized_user():
    auth_header_name = get_auth_header()
    auth_header_value = request.headers.get(auth_header_name) if auth_header_name else None

    try:
        if auth_header_name == HEADER_PROXY_TICKET or auth_header_name == HEADER_CP_TICKET:
            member_session = validate_proxy(auth_header_value)
            if member_session is not None:
                return member_session.member
        elif auth_header_name == HEADER_AUTHORIZATION:
            if auth_header_value and auth_header_value.lower().startswith('bearer '):
                token = auth_header_value.split(None, 1)[1]
                # validate_bearer now returns user attributes on success or raises an exception
                user_attributes = validate_bearer(token)
                if user_attributes and 'id' in user_attributes: # URS profile returns 'id' as username
                    # NOTE: Evaluate returning a member session object for oauth clients
                    return user_attributes
                else: # Should not happen if validate_bearer is successful and returns expected data
                    raise AuthenticationError("Bearer token validation succeeded but returned unexpected data.")
            else: # Malformed Authorization header
                raise AuthenticationError("Malformed Authorization header.")

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
                    member_session = validate_proxy(auth_header_value) # Can raise Auth/ExternalServiceError
                    if member_session is not None and member_session.member.role_id >= role:
                        return wrapped_function(*args, **kwargs)
                    elif member_session is None: # Valid proxy ticket, but no session or role mismatch
                        raise AuthenticationError("Invalid session or insufficient permissions.")

                elif auth_header_name == HEADER_AUTHORIZATION:
                    if auth_header_value and auth_header_value.lower().startswith('bearer '):
                        token = auth_header_value.split(None, 1)[1]
                        user_attributes = validate_bearer(token) # Can raise Auth/ExternalServiceError

                        # Similar to get_authorized_user, need to map user_attributes to a Member and check role
                        # This part needs robust implementation based on what validate_bearer returns.
                        # Assuming 'id' is the username and we need to fetch member role.
                        if user_attributes and 'id' in user_attributes:
                            member = db.session.query(Member).filter(Member.username == user_attributes['id']).first()
                            if member and member.role_id >= role:
                                return wrapped_function(*args, **kwargs)
                            elif not member:
                                raise AuthenticationError("User identified by token not found in MAAP database.")
                            else: # Member found, but role too low
                                raise AuthenticationError("Insufficient permissions for this resource.")
                        else: # Should not happen if validate_bearer is successful
                             raise AuthenticationError("Bearer token validation succeeded but returned unexpected data.")
                    else: # Malformed Authorization header
                        raise AuthenticationError("Malformed Authorization header.")

                elif auth_header_name == HEADER_CAS_AUTHORIZATION:
                     # validate_cas_request returns (is_valid, xml_dict) or raises.
                     # If it doesn't raise, then is_valid should be true for access.
                    is_valid, _ = validate_cas_request(auth_header_value)
                    if is_valid:
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
    return None


def edl_federated_request(url, stream_response=False):
    s = requests.Session()
    response = s.get(url, stream=stream_response)

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        maap_user = get_authorized_user()

        if maap_user is not None:
            urs_token = db.session.query(Member).filter_by(id=maap_user.id).first().urs_token
            s.headers.update({'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
                              'Connection': 'close'})

            response = s.get(url=response.url, stream=stream_response)

    return response