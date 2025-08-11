#!/usr/bin/env python

import logging.config

import os
from flask import Flask, Blueprint, request, session
from api import settings
from api.auth.cas_auth import validate
from api.utils.environments import Environments, get_environment
from api.utils.url_util import proxied_url
from api.endpoints.cmr import ns as cmr_collections_namespace
from api.endpoints.algorithm import ns as algorithm_namespace
from api.endpoints.ogc import ns as ogc_namespace
from api.endpoints.job import ns as job_namespace
from api.endpoints.wmts import ns as wmts_namespace
from api.endpoints.wms import ns as wms_namespace
from api.endpoints.members import ns as members_namespace
from api.endpoints.environment import ns as environment_namespace
from api.endpoints.organizations import ns as organizations_namespace
from api.endpoints.admin import ns as admin_namespace
from api.endpoints.build import ns as build_namespace
from api.restplus import api
from api.maap_database import db
from api.models import initialize_sql
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = settings.CAS_SECRET_KEY
logging_conf_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '../logging.conf'))
logging.config.fileConfig(logging_conf_path)
log = logging.getLogger(__name__)

blueprint = Blueprint('baseapi', __name__, url_prefix='/api')
api.init_app(blueprint)
api.add_namespace(cmr_collections_namespace)
app.register_blueprint(blueprint)

app.config['CAS_SERVER'] = settings.CAS_SERVER_NAME
app.config['CAS_AFTER_LOGIN'] = settings.CAS_AFTER_LOGIN
app.config['CAS_USERNAME_SESSION_KEY'] = 'cas_token_session_key'
app.config['SQLALCHEMY_DATABASE_URI'] = settings.DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'isolation_level': 'AUTOCOMMIT', 'pool_size': 10, 'pool_pre_ping': True}
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 30

app.app_context().push()
db.init_app(app)
initialize_sql(db.engine)
# Create any new tables
db.create_all()


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN' # Consider DENY if no framing is ever needed
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # A basic CSP. Might need to be adjusted based on actual content (e.g. if Swagger UI needs more).
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none';"
    # Add HSTS header if your application is always served over HTTPS
    if request.is_secure or request.headers.get('X-Forwarded-Proto', 'http') == 'https':
         response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


@app.route('/')
def index():

    html = '<a href="/api/">MAAP API</a>'
    env = get_environment(proxied_url(request))

    if env == Environments.DIT:
        html += '<a href="{}/login?service={}" style="float: right"><b>Authorize</b></a>'\
            .format(settings.CAS_SERVER_NAME, proxied_url(request, True))

        cas_token_session_key = app.config['CAS_USERNAME_SESSION_KEY']

        if 'ticket' in request.args:
            session[cas_token_session_key] = request.args['ticket']

        if cas_token_session_key in session:
            member_session = validate(proxied_url(request, True), session[cas_token_session_key])
            if member_session is None:
                del session[cas_token_session_key]
            else:
                html += '<br><br><div style="float:right; text-align: right">'\
                    'Username:<br>'\
                    '<b>{}</b><br><br>'\
                    'Proxy ticket:<br>'\
                    '<b>{}</b></div>'.format(member_session.member.username, member_session.session_key)

    return html


def configure_app(flask_app):
    flask_app.config['SERVER_NAME'] = settings.FLASK_SERVER_NAME
    flask_app.config['CMR_API_TOKEN'] = settings.CMR_API_TOKEN
    flask_app.config['CMR_CLIENT_ID'] = settings.CMR_CLIENT_ID
    flask_app.config['SWAGGER_UI_DOC_EXPANSION'] = settings.RESTPLUS_SWAGGER_UI_DOC_EXPANSION
    flask_app.config['RESTPLUS_VALIDATE'] = settings.RESTPLUS_VALIDATE
    flask_app.config['RESTPLUS_MASK_SWAGGER'] = settings.RESTPLUS_MASK_SWAGGER
    flask_app.config['ERROR_404_HELP'] = settings.RESTPLUS_ERROR_404_HELP
    flask_app.config['TILER_ENDPOINT'] = settings.TILER_ENDPOINT
    flask_app.config['QS_STATE_MACHINE_ARN'] = settings.QS_STATE_MACHINE_ARN
    flask_app.config['QS_RESULT_BUCKET'] = settings.QS_RESULT_BUCKET
    flask_app.config['SESSION_TYPE'] = 'filesystem'


def initialize_app(flask_app):
    configure_app(flask_app)

    blueprint = Blueprint('api', __name__, url_prefix='/api')
    api.init_app(blueprint)
    api.add_namespace(cmr_collections_namespace)
    api.add_namespace(algorithm_namespace)
    api.add_namespace(ogc_namespace)
    api.add_namespace(job_namespace)
    api.add_namespace(wmts_namespace)
    api.add_namespace(wms_namespace)
    api.add_namespace(members_namespace)
    api.add_namespace(environment_namespace)
    api.add_namespace(organizations_namespace)
    api.add_namespace(admin_namespace)
    api.add_namespace(build_namespace)
    flask_app.register_blueprint(blueprint)


def main():
    initialize_app(app)
    log.info('>>>>> Starting development server at http://{}/api/ <<<<<'.format(app.config['SERVER_NAME']))
    app.run(debug=settings.FLASK_DEBUG)


if __name__ == "__main__":
    main()
