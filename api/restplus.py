import logging
from flask import jsonify, current_app
from werkzeug.exceptions import HTTPException # Base for many Flask/Werkzeug errors

from flask_restx import Api
from api import settings
# Import custom exceptions to register handlers for them if not automatically handled by Flask-RESTX
from api.utils.security_utils import InvalidFileTypeError, FileSizeTooLargeError, \
                                     InvalidRequestError, AuthenticationError, \
                                     ExternalServiceError

log = logging.getLogger(__name__)

authorizations = {
    'ApiKeyAuth': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'proxy-ticket' # Primary auth for Swagger
    },
    'BearerAuth': { # Adding Bearer Auth for completeness in Swagger if used
        'type': 'apiKey', # Swagger 2.0 uses apiKey for bearer tokens too
        'in': 'header',
        'name': 'Authorization',
        'description': "JWT Authorization header using the Bearer scheme. Example: \"Authorization: Bearer {token}\""
    }
}

api = Api(version='0.1',
          title='MAAP API',
          description='API for querying multi-mission data and algorithms collaboration.',
          authorizations=authorizations,
          # doc='/api/doc/' # Optional: if you want to change the swagger UI path
         )

# Custom error class for CMR, if still needed, ensure it uses HTTPException structure
# or Flask-RESTX handles it well. For now, assuming it might be replaced or handled by generic handlers.
# class CmrError(HTTPException): # Better to inherit from HTTPException
#     code = 500 # Default code
#     description = "Error interacting with CMR service."

#     def __init__(self, message=None, status_code=None, payload=None):
#         super().__init__(description=message)
#         if message:
#             self.description = message # Overrides default description
#         if status_code:
#             self.code = status_code
#         self.payload = payload or {}

#     def get_response(self, environ=None):
#         response = jsonify({
#             'message': self.description,
#             **self.payload
#         })
#         response.status_code = self.code
#         return response

# General error handler for werkzeug.exceptions.HTTPException
# Flask-RESTX typically handles these well by default, creating JSON responses.
# This custom handler can ensure consistent formatting if needed.
@api.errorhandler(HTTPException)
def handle_http_exception(error):
    """Return JSON instead of HTML for HTTP errors."""
    log.error(f"HTTPException caught: {error.code} - {error.name} - {error.description}", exc_info=settings.FLASK_DEBUG)
    response_data = {
        "message": error.description or error.name, # Use description if available
        "code": error.code
    }
    # Add additional details if in debug mode and they exist (e.g. custom payload)
    if settings.FLASK_DEBUG and hasattr(error, 'data'):
        response_data['details'] = error.data.get('errors') if isinstance(error.data, dict) else str(error.data)

    return response_data, error.code

# Handler for our custom security exceptions if they don't get handled correctly by the above
# (They should, as they inherit from Werkzeug's HTTPException classes like BadRequest, Unauthorized etc.)
# Example:
# @api.errorhandler(AuthenticationError)
# def handle_authentication_error(error):
#     log.warning(f"AuthenticationError: {error.description}")
#     return {'message': error.description, "code": error.code}, error.code

# @api.errorhandler(ExternalServiceError)
# def handle_external_service_error(error):
#     log.error(f"ExternalServiceError: {error.description}")
#     return {'message': error.description, "code": error.code}, error.code

# Default error handler for any exception not specifically caught
@api.errorhandler(Exception)
def default_error_handler(e):
    # For werkzeug HTTPExceptions, let the specific handler or Flask-RESTX default do its job.
    # This check prevents our generic 500 handler from overriding more specific HTTP exception responses.
    if isinstance(e, HTTPException):
        # This case should ideally be handled by handle_http_exception or Flask-RESTX defaults
        # If it reaches here, it means it wasn't caught by a more specific werkzeug.exception handler
        # We can either re-raise it or handle it like handle_http_exception
        log.error(f"Unhandled HTTPException: {e.code} - {e.name} - {e.description}", exc_info=settings.FLASK_DEBUG)
        return {
            'message': e.description or e.name,
            "code": e.code
        }, e.code

    # For non-HTTP exceptions (true unexpected errors)
    message = 'An internal server error occurred. Please try again later.'
    log.exception("Unhandled Exception caught by default_error_handler:") # Logs full stack trace

    if settings.FLASK_DEBUG: # Provide more details in debug mode
        return {'message': str(e), 'type': type(e).__name__}, 500

    return {'message': message, "code": 500}, 500


# If CmrError is still used and NOT inheriting HTTPException, it needs its own handler.
# If it inherits HTTPException, the handle_http_exception above should cover it.
# Let's assume for now CmrError might be phased out or made an HTTPException.
# @api.errorhandler(CmrError)
# def handle_cmr_error(error):
#     log.error(f"CmrError: {error.description if hasattr(error,'description') else str(error)}")
#     status_code = error.code if hasattr(error, 'code') else 500
#     message = error.description if hasattr(error,'description') else str(error)
#     return {'message': message, "code": status_code}, status_code


