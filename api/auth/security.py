from functools import wraps
import requests
from flask import request, abort
from flask_api import status
from api import settings
from api.auth.cas_auth import validate_proxy, validate_bearer, validate_cas_request, validate_third_party
from api.maap_database import db
from api.models.member import Member
from api.models.role import Role

HEADER_PROXY_TICKET = "proxy-ticket"
THIRD_PARTY_AUTH_HEADER = "X-Gitlab-Token"
HEADER_CP_TICKET = "cpticket"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CAS_AUTHORIZATION = "cas-authorization"
HEADER_DPS_TOKEN = "dps-token"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_SUSPENDED = "suspended"


def get_authorized_user():
    print("graceal1 in get authorized user")
    try:
        auth = get_auth_header()

        if auth == HEADER_PROXY_TICKET or auth == HEADER_CP_TICKET:
            member_session = validate_proxy(request.headers[auth])

            if member_session is not None:
                print("graceal1 returning member")
                return member_session.member

        if auth == HEADER_AUTHORIZATION:
            bearer = request.headers.get(auth)
            token = bearer.split()[1]
            authorized = validate_bearer(token)

            if authorized is not None:
                return authorized
    except Exception as e:
        print("graceal1 exception getting user which is ")
        print(e)

    return None

def authenticate_third_party():
    def authenticate_third_party_outer(wrapped_function):
        @wraps(wrapped_function)
        def wrap(*args, **kwargs):
            if THIRD_PARTY_AUTH_HEADER in request.headers and validate_third_party(request.headers[THIRD_PARTY_AUTH_HEADER]):
                return wrapped_function(*args, **kwargs)

            abort(status.HTTP_403_FORBIDDEN, description="Not authorized.")

        return wrap
    return authenticate_third_party_outer

def login_required(role=Role.ROLE_GUEST):
    def login_required_outer(wrapped_function):
        @wraps(wrapped_function)
        def wrap(*args, **kwargs):
            auth = get_auth_header()

            if auth == HEADER_PROXY_TICKET or auth == HEADER_CP_TICKET:
                member_session = validate_proxy(request.headers[auth])

                if member_session is not None and member_session.member.role_id >= role:
                    return wrapped_function(*args, **kwargs)

            if auth == HEADER_AUTHORIZATION:
                bearer = request.headers.get(auth)
                token = bearer.split()[1]
                authorized = validate_bearer(token)

                if authorized is not None:
                    return wrapped_function(*args, **kwargs)

            if auth == HEADER_CAS_AUTHORIZATION and validate_cas_request(request.headers[auth]) is not None:
                return wrapped_function(*args, **kwargs)

            if auth == HEADER_DPS_TOKEN and valid_dps_request():
                return wrapped_function(*args, **kwargs)

            abort(status.HTTP_403_FORBIDDEN, description="Not authorized.")

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
