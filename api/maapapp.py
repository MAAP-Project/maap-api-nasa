import logging.config

import os
from flask import Flask, Blueprint, jsonify, request, make_response
from api import settings
from api.endpoints.cmr import ns as cmr_collections_namespace
from api.endpoints.algorithm import ns as algorithm_namespace
from api.endpoints.job import ns as job_namespace
from api.restplus import api
import jwt
import datetime

app = Flask(__name__)
logging_conf_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '../logging.conf'))
logging.config.fileConfig(logging_conf_path)
log = logging.getLogger(__name__)

blueprint = Blueprint('baseapi', __name__, url_prefix='/api')
api.init_app(blueprint)
api.add_namespace(cmr_collections_namespace)
app.register_blueprint(blueprint)


@app.route('/login')
def login():
    auth = request.authorization
    return issue_token(auth.username, auth.password)


@app.route('/token', methods=['POST'])
def token():
    req_data = request.get_json()
    return issue_token(req_data["username"], req_data["password"])


def issue_token(username, password):
    #TODO: replace with MAAP ldap credential validation
    if password == 'secret':
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


def initialize_app(flask_app):
    configure_app(flask_app)

    blueprint = Blueprint('api', __name__, url_prefix='/api')
    api.init_app(blueprint)
    api.add_namespace(cmr_collections_namespace)
    api.add_namespace(algorithm_namespace)
    api.add_namespace(job_namespace)
    flask_app.register_blueprint(blueprint)


def main():
    initialize_app(app)
    log.info('>>>>> Starting development server at http://{}/api/ <<<<<'.format(app.config['SERVER_NAME']))
    app.run(debug=settings.FLASK_DEBUG)


if __name__ == "__main__":
    main()


