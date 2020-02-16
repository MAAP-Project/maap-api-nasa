from datetime import timedelta, datetime

import flask
from flask import abort, request
from xmltodict import parse
from flask import current_app
from .cas_urls import create_cas_proxy_url
from .cas_urls import create_cas_proxy_validate_url
from api.maap_database import db
from api.models.member import Member
from api.models.member_session import MemberSession
from functools import wraps


try:
    from urllib import urlopen
except ImportError:
    from urllib.request import urlopen

blueprint = flask.Blueprint('cas', __name__)


def validate_proxy(ticket):
    """
    Will attempt to validate the proxy ticket. If validation fails, then None
    is returned. If validation is successful, then a Member object is returned
    and the validated proxy ticket is saved in the session db table while the
    validated attributes are saved under member db table.
    """

    current_app.logger.debug("validating token {0}".format(ticket))

    cas_session = MemberSession.query.filter_by(session_key=ticket).first()

    # Check for session created timestamp < 2 hours old
    if cas_session is not None and cas_session.creation_date + timedelta(hours=2) > datetime.utcnow():
        return cas_session
    else:
        cas_validate_proxy_url = create_cas_proxy_url(
            current_app.config['CAS_SERVER'],
            request.base_url,
            ticket
        )

        cas_response = validate_cas_request(cas_validate_proxy_url)

        if cas_response[0]:
            current_app.logger.debug("valid proxy granting ticket")

            xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:proxySuccess"]
            proxy_ticket = xml_from_dict["cas:proxyTicket"]

            proxy_validate_url = create_cas_proxy_validate_url(
                current_app.config['CAS_SERVER'],
                request.base_url,
                proxy_ticket
            )

            cas_proxy_response = validate_cas_request(proxy_validate_url)

            if cas_proxy_response[0]:
                return start_member_session(cas_proxy_response, ticket)

    current_app.logger.debug("invalid proxy granting ticket")
    return None


def validate_cas_request(cas_url):

    xml_from_dict = {}
    is_valid = False

    current_app.logger.debug("Making GET request to {0}".format(
        cas_url))

    try:
        xmldump = urlopen(cas_url).read().strip().decode('utf8', 'ignore')
        xml_from_dict = parse(xmldump)
        is_valid = True if "cas:authenticationSuccess" in xml_from_dict["cas:serviceResponse"] or \
                           "cas:proxySuccess" in xml_from_dict["cas:serviceResponse"] else False
    except ValueError:
        current_app.logger.error("CAS returned unexpected result")

    return is_valid, xml_from_dict


def start_member_session(cas_response, ticket):

    xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:authenticationSuccess"]
    attributes = xml_from_dict.get("cas:attributes", {})
    usr = get_cas_attribute_value(attributes, 'preferred_username')

    member = Member.query.filter_by(username=usr).first()

    if member is None:
        member = Member(first_name=get_cas_attribute_value(attributes, 'given_name'),
                        last_name=get_cas_attribute_value(attributes, 'family_name'),
                        username=usr,
                        email=get_cas_attribute_value(attributes, 'email'),
                        organization=get_cas_attribute_value(attributes, 'organization'))
        db.session.add(member)
        db.session.commit()

    member_session = MemberSession(member_id=member.id, session_key=ticket)
    db.session.add(member_session)
    db.session.commit()

    return member_session


def get_cas_attribute_value(attributes, attribute_key):

    if attributes and "cas:" + attribute_key in attributes:
        return attributes["cas:" + attribute_key]
    else:
        return ''


def get_authorized_user():
    if 'proxy-ticket' in request.headers:
        member_session = validate_proxy(request.headers['proxy-ticket'])

        if member_session is not None:
            return member_session.member.serialize

    return None


def login_required(wrapped_function):
    @wraps(wrapped_function)
    def wrap(*args, **kwargs):

        if 'proxy-ticket' in request.headers:
            authorized = validate_proxy(request.headers['proxy-ticket'])

            if authorized is not None:
                return wrapped_function(*args, **kwargs)

        abort(403, description="Not authorized.")

    return wrap

