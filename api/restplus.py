import logging
from flask import jsonify


from flask_restx import Api
from api import settings

log = logging.getLogger(__name__)

api = Api(version='0.1', title='MAAP API',
          description='API for querying multi-mission data and algorithms collaboration.')


class CmrError(Exception):
    status_code = 500

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


@api.errorhandler
def default_error_handler(e):
    message = 'An unhandled exception occurred.'
    log.exception(message)

    if not settings.FLASK_DEBUG:
        return {'message': message}, 500


@api.errorhandler(CmrError)
def handle_cmr_error(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


