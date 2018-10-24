import logging
import traceback

from flask_restplus import Api
from api import settings

log = logging.getLogger(__name__)

api = Api(version='0.1', title='MAAP API',
          description='API for querying multi-mission data and algorithms collaboration.')


@api.errorhandler
def default_error_handler(e):
    message = 'An unhandled exception occurred.'
    log.exception(message)

    if not settings.FLASK_DEBUG:
        return {'message': message}, 500


