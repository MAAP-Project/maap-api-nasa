import flask
from xmltodict import parse
from flask import current_app, request
from .cas_urls import create_cas_login_url
from .cas_urls import create_cas_logout_url
from .cas_urls import create_cas_validate_url
from .cas_urls import create_cas_proxy_url
from .cas_urls import create_cas_proxy_validate_url


try:
    from urllib import urlopen
except ImportError:
    from urllib.request import urlopen

blueprint = flask.Blueprint('cas', __name__)


@blueprint.route('/login/')
def login():
    """
    This route has two purposes. First, it is used by the user
    to login. Second, it is used by the CAS to respond with the
    `ticket` after the user logs in successfully.

    When the user accesses this url, they are redirected to the CAS
    to login. If the login was successful, the CAS will respond to this
    route with the ticket in the url. The ticket is then validated.
    If validation was successful the logged in username is saved in
    the user's session under the key `CAS_USERNAME_SESSION_KEY` and
    the user's attributes are saved under the key
    'CAS_USERNAME_ATTRIBUTE_KEY'
    """

    cas_token_session_key = current_app.config['CAS_TOKEN_SESSION_KEY']

    redirect_url = create_cas_login_url(
        current_app.config['CAS_SERVER'],
        current_app.config['CAS_LOGIN_ROUTE'],
        flask.url_for('.login', origin=flask.session.get('CAS_AFTER_LOGIN_SESSION_URL'), _external=True))

    if 'ticket' in flask.request.args:
        flask.session[cas_token_session_key] = flask.request.args['ticket']

    if cas_token_session_key in flask.session:

        if validate(flask.session[cas_token_session_key]):
            if 'CAS_AFTER_LOGIN_SESSION_URL' in flask.session:
                redirect_url = flask.session.pop('CAS_AFTER_LOGIN_SESSION_URL')
            elif flask.request.args.get('origin'):
                redirect_url = flask.request.args['origin']
            else:
                redirect_url = flask.url_for(
                    current_app.config['CAS_AFTER_LOGIN'])
        else:
            del flask.session[cas_token_session_key]

    current_app.logger.debug('Redirecting to: {0}'.format(redirect_url))

    return flask.redirect(redirect_url)


@blueprint.route('/logout/')
def logout():
    """
    When the user accesses this route they are logged out.
    """

    cas_username_session_key = current_app.config['CAS_USERNAME_SESSION_KEY']
    cas_attributes_session_key = current_app.config['CAS_ATTRIBUTES_SESSION_KEY']

    if cas_username_session_key in flask.session:
        del flask.session[cas_username_session_key]

    if cas_attributes_session_key in flask.session:
        del flask.session[cas_attributes_session_key]

    if(current_app.config['CAS_AFTER_LOGOUT'] is not None):
        redirect_url = create_cas_logout_url(
            current_app.config['CAS_SERVER'],
            current_app.config['CAS_LOGOUT_ROUTE'],
            current_app.config['CAS_AFTER_LOGOUT'])
    else:
        redirect_url = create_cas_logout_url(
            current_app.config['CAS_SERVER'],
            current_app.config['CAS_LOGOUT_ROUTE'])

    current_app.logger.debug('Redirecting to: {0}'.format(redirect_url))
    return flask.redirect(redirect_url)


def validate(ticket):
    """
    Will attempt to validate the ticket. If validation fails, then False
    is returned. If validation is successful, then True is returned
    and the validated username is saved in the session under the
    key `CAS_USERNAME_SESSION_KEY` while tha validated attributes dictionary
    is saved under the key 'CAS_ATTRIBUTES_SESSION_KEY'.
    """

    cas_username_session_key = current_app.config['CAS_USERNAME_SESSION_KEY']
    cas_attributes_session_key = current_app.config['CAS_ATTRIBUTES_SESSION_KEY']

    current_app.logger.debug("validating token {0}".format(ticket))

    # Check if proxy ticket is present in header.
    # If so, initiate proxy auth.
    if 'proxy-ticket' in request.headers:

        proxy_granting_ticket = request.headers['proxy-ticket']

        cas_validate_proxy_url = create_cas_proxy_url(
            current_app.config['CAS_SERVER'],
            flask.url_for('.login', origin=flask.session.get('CAS_AFTER_LOGIN_SESSION_URL'), _external=True),
            proxy_granting_ticket
        )

        cas_response = validate_cas_request(cas_validate_proxy_url)

        if cas_response[0]:
            current_app.logger.debug("valid")
            xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:proxySuccess"]
            proxy_ticket = xml_from_dict["cas:proxyTicket"]

            proxy_validate_url = create_cas_proxy_validate_url(
                current_app.config['CAS_SERVER'],
                flask.url_for('.login', origin=flask.session.get('CAS_AFTER_LOGIN_SESSION_URL'), _external=True),
                proxy_ticket
            )

            cas_proxy_response = validate_cas_request(proxy_validate_url)

            if cas_proxy_response[0]:
                start_cas_session(cas_proxy_response)

                return True;
            else:
                current_app.logger.debug("invalid")

        else:
            current_app.logger.debug("invalid")

    else:
        cas_validate_url = create_cas_validate_url(
            current_app.config['CAS_SERVER'],
            current_app.config['CAS_VALIDATE_ROUTE'],
            flask.url_for('.login', origin=flask.session.get('CAS_AFTER_LOGIN_SESSION_URL'), _external=True),
            ticket)

        cas_response = validate_cas_request(cas_validate_url)

        if cas_response[0]:
            start_cas_session(cas_response)

            return True;
        else:
            current_app.logger.debug("invalid")

    return False


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


def start_cas_session(cas_response):

    cas_username_session_key = current_app.config['CAS_USERNAME_SESSION_KEY']
    cas_attributes_session_key = current_app.config['CAS_ATTRIBUTES_SESSION_KEY']

    current_app.logger.debug("valid")
    xml_from_dict = cas_response[1]["cas:serviceResponse"]["cas:authenticationSuccess"]
    username = xml_from_dict["cas:user"]
    attributes = xml_from_dict.get("cas:attributes", {})

    if attributes and "cas:memberOf" in attributes:
        if isinstance(attributes["cas:memberOf"], basestring):
            attributes["cas:memberOf"] = attributes["cas:memberOf"].lstrip('[').rstrip(']').split(',')
            for group_number in range(0, len(attributes['cas:memberOf'])):
                attributes['cas:memberOf'][group_number] = attributes['cas:memberOf'][group_number].lstrip(' ').rstrip(
                    ' ')
    flask.session[cas_username_session_key] = username
    flask.session[cas_attributes_session_key] = attributes