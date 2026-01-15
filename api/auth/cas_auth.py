from datetime import timedelta, datetime

import flask
import requests
from flask import request, json
from flask_api import status
from xmltodict import parse
from flask import current_app
from .cas_urls import create_cas_proxy_url, create_cas_validate_url, create_cas_proxy_validate_url
from api.maap_database import db
from api.models.member import Member
from api.models.member_session import MemberSession
from api import settings
from api import constants
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto import Random
from Crypto.Hash import SHA
from base64 import b64decode
from api.utils.url_util import proxied_url
import ast
import socket # For socket.timeout
from xml.parsers.expat import ExpatError # For XML parsing errors
from api.models.role import Role
from api.utils.security_utils import AuthenticationError, ExternalServiceError


try:
    from urllib import urlopen, URLError # URLError for network issues
except ImportError:
    from urllib.request import urlopen, URLError # URLError for network issues


blueprint = flask.Blueprint('cas', __name__)

PROXY_TICKET_PREFIX = "PGT-"
JWT_TOKEN_PREFIX = "jwt:"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_SUSPENDED = "suspended"

def validate(service, ticket):
    """
    Will attempt to validate the ticket. If validation fails False
    is returned. If validation is successful then True is returned
    and the validated username is saved in the session under the
    key `CAS_USERNAME_SESSION_KEY`.
    """

    current_app.logger.debug("validating token {}".format(ticket))

    cas_validate_url = create_cas_validate_url(
        current_app.config['CAS_SERVER'],
        '/cas/p3/serviceValidate',
        service,
        ticket) + '&pgtUrl=' + current_app.config['CAS_SERVER']

    current_app.logger.debug("Making GET request to {}".format(cas_validate_url))

    try:
        response = urlopen(cas_validate_url, timeout=settings.REQUESTS_TIMEOUT_SECONDS)
        xmldump = response.read().strip().decode('utf8', 'ignore')
        xml_from_dict = parse(xmldump) # This can raise ExpatError

        success_auth = xml_from_dict.get("cas:serviceResponse", {}).get("cas:authenticationSuccess")
        success_proxy = xml_from_dict.get("cas:serviceResponse", {}).get("cas:proxySuccess")

        is_valid = bool(success_auth or success_proxy)

        if is_valid:
            attributes_parent = success_auth or success_proxy # Get the one that exists
            attributes = attributes_parent.get("cas:attributes", {})
            pg_ticket = get_cas_attribute_value(attributes, 'proxyGrantingTicket')
            if not pg_ticket:
                 current_app.logger.warning("No proxyGrantingTicket found in CAS response.")
                 raise AuthenticationError("Missing proxyGrantingTicket from CAS.")
            return validate_proxy(pg_ticket, True)
        else:
            failure_message = xml_from_dict.get("cas:serviceResponse", {}).get("cas:authenticationFailure", {}).get("#text", "Unknown CAS validation error")
            current_app.logger.warning(f"CAS validation failed: {failure_message}")
            raise AuthenticationError(f"CAS ticket validation failed: {failure_message}")

    except (URLError, socket.timeout) as e:
        current_app.logger.error(f"CAS server connection failed or timed out: {e}")
        raise ExternalServiceError("CAS server connection failed or timed out.")
    except ExpatError as e:
        current_app.logger.error(f"Failed to parse XML response from CAS: {e}")
        raise AuthenticationError("Invalid XML response from CAS server.")
    except ValueError as e: # Catching if decode fails or parse has other issues
        current_app.logger.error(f"CAS returned unexpected result or malformed XML: {e}")
        raise AuthenticationError("CAS returned unexpected or malformed response.")
    except AuthenticationError: # Re-raise our own specific auth errors
        raise
    except Exception as e: # Catch-all for other unexpected errors during validation
        current_app.logger.error(f"Unexpected error during CAS ticket validation: {e}")
        raise ExternalServiceError("An unexpected error occurred during CAS ticket validation.")


def validate_proxy(ticket, auto_create_member=False):
    """
    Will attempt to validate the proxy ticket. If validation fails, then None
    is returned. If validation is successful, then a Member object is returned
    and the validated proxy ticket is saved in the session db table while the
    validated attributes are saved under member db table.
    """

    pgt_token_duration_in_days = 60

    current_app.logger.debug("validating token {0}".format(ticket))
    decrypted_ticket = decrypt_proxy_ticket(ticket)
    cas_session = db.session.query(MemberSession).filter_by(session_key=decrypted_ticket).first()

    # Check for active session created within allowed timespan
    if cas_session is not None and cas_session.creation_date + timedelta(days=pgt_token_duration_in_days) > datetime.utcnow():
        return cas_session
    else:
        cas_validate_proxy_url = create_cas_proxy_url(
            current_app.config['CAS_SERVER'],
            proxied_url(request),
            decrypted_ticket
        )

        cas_response = validate_cas_request(cas_validate_proxy_url)

        if cas_response[0]:
            current_app.logger.debug("valid proxy granting ticket")

            xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:proxySuccess"]
            proxy_ticket = xml_from_dict["cas:proxyTicket"]

            proxy_validate_url = create_cas_proxy_validate_url(
                current_app.config['CAS_SERVER'],
                proxied_url(request),
                proxy_ticket
            )

            cas_proxy_response = validate_cas_request(proxy_validate_url)

            if cas_proxy_response[0]:
                return start_member_session(cas_proxy_response, decrypted_ticket, auto_create_member)

    current_app.logger.debug("invalid proxy granting ticket")
    return None


def validate_bearer(token):
    """
    Will attempt to validate the bearer token. If validation fails, then None
    is returned. If validation is successful, then a Member object is returned.
    """

    current_app.logger.debug("validating token {0}".format(token))
    url = current_app.config['CAS_SERVER'] + '/oauth2.0/profile'
    headers = {'Authorization': 'Bearer ' + token}

    try:
        resp = requests.get(url, headers=headers, timeout=settings.REQUESTS_TIMEOUT_SECONDS)
        resp.raise_for_status()  # Raises HTTPError for 4xx/5xx responses

        return resp.json() # This can raise json.JSONDecodeError

    except requests.exceptions.Timeout:
        current_app.logger.error(f"Timeout connecting to CAS server for bearer token validation at {url}")
        raise ExternalServiceError("Authentication service timed out.")
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"Connection error to CAS server for bearer token validation at {url}")
        raise ExternalServiceError("Could not connect to authentication service.")
    except requests.exceptions.HTTPError as e:
        # This catches 4xx and 5xx errors from resp.raise_for_status()
        if e.response.status_code == status.HTTP_401_UNAUTHORIZED or e.response.status_code == status.HTTP_403_FORBIDDEN:
            current_app.logger.warning(f"Invalid bearer token. CAS server responded with {e.response.status_code}.")
            raise AuthenticationError("Invalid bearer token.")
        else:
            current_app.logger.error(f"CAS server returned HTTP {e.response.status_code} for bearer token validation.")
            raise ExternalServiceError(f"Authentication service returned an error: {e.response.status_code}")
    except json.JSONDecodeError:
        current_app.logger.error("Failed to decode JSON response from CAS server during bearer token validation.")
        raise AuthenticationError("Invalid response from authentication service.")
    except Exception as e: # Catch-all for other unexpected errors
        current_app.logger.error(f"Unexpected error during bearer token validation: {e}")
        raise ExternalServiceError("An unexpected error occurred during token validation.")

def validate_third_party(secret_token):
    return secret_token == settings.THIRD_PARTY_SECRET_TOKEN_GITLAB

def validate_cas_request(cas_url):

    xml_from_dict = {}
    is_valid = False

    current_app.logger.debug(f"Making GET request to {cas_url}")

    try:
        response = urlopen(cas_url, timeout=settings.REQUESTS_TIMEOUT_SECONDS)
        xmldump = response.read().strip().decode('utf8', 'ignore')
        xml_from_dict = parse(xmldump) # Can raise ExpatError

        # Check for successful authentication or proxy success
        auth_success = xml_from_dict.get("cas:serviceResponse", {}).get("cas:authenticationSuccess")
        proxy_success = xml_from_dict.get("cas:serviceResponse", {}).get("cas:proxySuccess")

        is_valid = bool(auth_success or proxy_success)

        if not is_valid:
            failure_node = xml_from_dict.get("cas:serviceResponse", {}).get("cas:authenticationFailure")
            if failure_node:
                error_code = failure_node.get("@code", "UNKNOWN_ERROR")
                error_message = failure_node.get("#text", "CAS request failed without detailed message.")
                current_app.logger.warning(f"CAS request failed. Code: {error_code}. Message: {error_message}. URL: {cas_url}")
                # Do not raise AuthenticationError here, let the caller decide.
                # This function's contract is to return (is_valid, xml_dict)
            else: # Should not happen if CAS is behaving, but good to log
                current_app.logger.warning(f"CAS request to {cas_url} was not successful and no failure node found in response.")

        return is_valid, xml_from_dict

    except (URLError, socket.timeout) as e:
        current_app.logger.error(f"CAS server connection failed or timed out for URL {cas_url}: {e}")
        raise ExternalServiceError(f"CAS server connection failed or timed out: {e}")
    except ExpatError as e:
        current_app.logger.error(f"Failed to parse XML response from CAS for URL {cas_url}: {e}")
        # Potentially return is_valid = False and an empty dict or specific error structure in xml_from_dict
        # For now, let's raise to indicate a severe issue with the response.
        raise AuthenticationError(f"Invalid XML response from CAS server: {e}")
    except ValueError as e: # Catching if decode fails
        current_app.logger.error(f"CAS returned unexpected result (e.g. decode error) for URL {cas_url}: {e}")
        raise AuthenticationError(f"CAS returned unexpected or malformed response: {e}")
    except Exception as e: # Catch-all for other unexpected errors
        current_app.logger.error(f"Unexpected error during CAS request to {cas_url}: {e}")
        raise ExternalServiceError(f"An unexpected error occurred during CAS request: {e}")


def start_member_session(cas_response, ticket, auto_create_member=False):

    xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:authenticationSuccess"]
    attributes = xml_from_dict.get("cas:attributes", {})
    usr = get_cas_attribute_value(attributes, 'preferred_username')

    member = db.session.query(Member).filter_by(username=usr).first()
    urs_access_token = get_cas_attribute_value(attributes, 'access_token')
    is_esa_user = get_cas_attribute_value(attributes, 'iss') == settings.ESA_ISS_HOST

    if is_esa_user:
        esa_system_account = db.session.query(Member).filter_by(username=settings.ESA_EDL_SYS_ACCOUNT).first()

        if esa_system_account is None:
            current_app.logger.warning(f"No ESA system account found for user {usr}.")
        else:
            urs_access_token = esa_system_account.urs_token 

    if member is None and (auto_create_member or is_esa_user):
        member = Member(first_name=get_cas_attribute_value(attributes, 'given_name'),
                        last_name=get_cas_attribute_value(attributes, 'family_name'),
                        username=usr,
                        email=get_cas_attribute_value(attributes, 'email'),
                        organization=get_cas_attribute_value(attributes, 'organization'),
                        urs_token=urs_access_token,
                        role_id=Role.ROLE_MEMBER if is_esa_user else Role.ROLE_GUEST,
                        status=MEMBER_STATUS_ACTIVE if is_esa_user else MEMBER_STATUS_SUSPENDED,
                        creation_date=datetime.utcnow())
        try:
            db.session.add(member)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to add new member {usr}: {e}")
            raise
    else:
        member.urs_token = urs_access_token

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to update member {usr}: {e}")
        raise

    member_session = MemberSession(member_id=member.id, session_key=ticket, creation_date=datetime.utcnow())
    try:
        db.session.add(member_session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to create member session for {usr}: {e}")
        raise

    return member_session


def start_member_session_jwt(decoded_jwt, token_string, auto_create_member=False):

    usr = decoded_jwt.get("preferred_username")

    member = db.session.query(Member).filter_by(username=usr).first()

    if member is None and (auto_create_member):
        member = Member(first_name=decoded_jwt.get("given_name"),
                        last_name=decoded_jwt.get("family_name"),
                        username=usr,
                        email=decoded_jwt.get("email"))
        try:
            db.session.add(member)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to add new member {usr}: {e}")
            raise

    member_session = MemberSession(member_id=member.id, session_key=token_string, creation_date=datetime.utcnow())
    try:
        db.session.add(member_session)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to create member session for {usr}: {e}")
        raise

    current_app.logger.error(f"Found member {usr}")
    current_app.logger.error(f"Member username {member.username}")

    return member


def get_cas_attribute_value(attributes, attribute_key):

    if attributes and "cas:" + attribute_key in attributes:
        return attributes["cas:" + attribute_key]
    else:
        return ''


def decrypt_proxy_ticket(ticket):
    if ticket.startswith(PROXY_TICKET_PREFIX) or ticket.startswith(JWT_TOKEN_PREFIX):
        return ticket
    else:
        try:
            key = RSA.import_key(settings.CAS_PROXY_DECRYPTION_TOKEN)
            dsize = SHA.digest_size
            sentinel = Random.new().read(15 + dsize)
            decryptor = PKCS1_v1_5.new(key)
            decrypted = decryptor.decrypt(ast.literal_eval(str(b64decode(ticket))), sentinel)

            return decrypted.decode("utf-8")
        except:
            current_app.logger.debug("invalid proxy granting ticket")
            return ''