from functools import wraps
import requests
from flask import request, abort
from flask_api import status
from api import settings
from api.auth.cas_auth import validate_proxy, validate_bearer, validate_cas_request
from api.maap_database import db
from api.models.member import Member

HEADER_PROXY_TICKET = "proxy-ticket"
HEADER_CP_TICKET = "cpticket"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CAS_AUTHORIZATION = "cas-authorization"
HEADER_DPS_TOKEN = "dps-token"


def get_authorized_user():
    auth = get_auth_header()

    if auth == HEADER_PROXY_TICKET or auth == HEADER_CP_TICKET:
        member_session = validate_proxy(request.headers[auth])

        if member_session is not None:
            return member_session.member

    if auth == HEADER_AUTHORIZATION:
        bearer = request.headers.get(auth)
        token = bearer.split()[1]
        authorized = validate_bearer(token)

        if authorized is not None:
            return authorized

    return None


def login_required(wrapped_function):
    @wraps(wrapped_function)
    def wrap(*args, **kwargs):

        auth = get_auth_header()

        if ((auth == HEADER_PROXY_TICKET or auth == HEADER_CP_TICKET) and
                validate_proxy(request.headers[auth]) is not None):
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
