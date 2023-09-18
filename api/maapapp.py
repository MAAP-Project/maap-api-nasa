#!/usr/bin/env python

import logging.config

import os
from flask import Flask, Blueprint
from api import settings
from api.endpoints.cmr import ns as cmr_collections_namespace
from api.endpoints.algorithm import ns as algorithm_namespace
from api.endpoints.job import ns as job_namespace
from api.endpoints.wmts import ns as wmts_namespace
from api.endpoints.wms import ns as wms_namespace
from api.endpoints.members import ns as members_namespace
from api.endpoints.three_dimensional_tiles import ns as three_d_tiles_namespace
from api.endpoints.environment import ns as environment_namespace
from api.endpoints.ogcapi_features import ns as ogcapi_features_namespace
from api.restplus import api
from api.maap_database import db
from api.models import initialize_sql

app = Flask(__name__)
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
app.config['SQLALCHEMY_DATABASE_URI'] = settings.DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.app_context().push()
db.init_app(app)
initialize_sql(db.engine)
#Base.ini .metadata.create_all(db.engine)
# db.create_all()
# db.session.commit()


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
    flask_app.config['OGCAPI_FEATURES_ENDPOINT'] = settings.OGCAPI_FEATURES_ENDPOINT
    flask_app.config['_3DTILES_API_ENDPOINT'] = settings._3DTILES_API_ENDPOINT
    flask_app.config['DATA_SYSTEM_FILES_PATH'] = settings.DATA_SYSTEM_FILES_PATH
    flask_app.config['QS_STATE_MACHINE_ARN'] = settings.QS_STATE_MACHINE_ARN
    flask_app.config['QS_RESULT_BUCKET'] = settings.QS_RESULT_BUCKET


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
    api.add_namespace(three_d_tiles_namespace)
    api.add_namespace(environment_namespace)
    api.add_namespace(ogcapi_features_namespace)
    flask_app.register_blueprint(blueprint)


def main():
    initialize_app(app)
    log.info('>>>>> Starting development server at http://{}/api/ <<<<<'.format(app.config['SERVER_NAME']))
    app.run(debug=settings.FLASK_DEBUG)


if __name__ == "__main__":
    main()

