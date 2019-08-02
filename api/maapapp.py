#!/usr/bin/env python

import logging.config

import os
import requests
from flask import Flask, Blueprint, jsonify, request, make_response
from api import settings
from api.endpoints.cmr import ns as cmr_collections_namespace
from api.endpoints.algorithm import ns as algorithm_namespace
from api.endpoints.job import ns as job_namespace
from api.endpoints.wmts import ns as wmts_namespace
from api.endpoints.wms import ns as wms_namespace
from api.endpoints.members import ns as members_namespace
from api.restplus import api
import jwt
import datetime
from flask_cas import CAS

app = Flask(__name__)
cas = CAS(app)
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


@app.route('/token', methods=['POST'])
def token():
    req_data = request.get_json()
    return issue_token(req_data["username"], req_data["password"])


def issue_token(username, password):

    # TODO: replace with MAAP ldap credential validation
    token_body = '<token><username>' + username + \
                 '</username><password>' + password + \
                 '</password><client_id>maap_api</client_id><user_ip_address>127.0.0.0</user_ip_address></token>'
    response = requests.post(
        settings.CMR_TOKEN_SERVICE_URL,
        data=token_body,
        headers={'Content-Type': 'application/xml'})

    # Until MAAP account integration is in place, just verify user's URS authorization
    if response.status_code == 200 or response.status_code == 201:
        token = jwt.encode({'user' : username, 'exp' : datetime.datetime.utcnow() + datetime.timedelta(weeks=24)}, settings.APP_AUTH_KEY)

        return jsonify({'token' : token.decode('UTF-8')})

    return make_response('Could not verify!', 401, {'WWW-Authenticate' : 'Basic realm="Login Required"'})


@app.route('/')
def index():
    return '<a href=/api/>MAAP API</a>'


def configure_app(flask_app):
    flask_app.config['SERVER_NAME'] = settings.FLASK_SERVER_NAME
    flask_app.config['CMR_API_TOKEN'] = settings.CMR_API_TOKEN
    flask_app.config['CMR_CLIENT_ID'] = settings.CMR_CLIENT_ID
    flask_app.config['SWAGGER_UI_DOC_EXPANSION'] = settings.RESTPLUS_SWAGGER_UI_DOC_EXPANSION
    flask_app.config['RESTPLUS_VALIDATE'] = settings.RESTPLUS_VALIDATE
    flask_app.config['RESTPLUS_MASK_SWAGGER'] = settings.RESTPLUS_MASK_SWAGGER
    flask_app.config['ERROR_404_HELP'] = settings.RESTPLUS_ERROR_404_HELP
    flask_app.config['TILER_ENDPOINT'] = settings.TILER_ENDPOINT


def initialize_app(flask_app):
    configure_app(flask_app)

    blueprint = Blueprint('api', __name__, url_prefix='/api')
    api.init_app(blueprint)
    api.add_namespace(cmr_collections_namespace)
    api.add_namespace(algorithm_namespace)
    api.add_namespace(job_namespace)
    api.add_namespace(wmts_namespace)
    api.add_namespace(wms_namespace)
    api.add_namespace(members_namespace)
    flask_app.register_blueprint(blueprint)


def main():
    initialize_app(app)
    #service
    log.info('>>>>> Starting development server at http://{}/api/ <<<<<'.format(app.config['SERVER_NAME']))
    app.run(debug=settings.FLASK_DEBUG)


if __name__ == "__main__":
    main()


