import unittest
import json
from flask import Flask, Blueprint
from flask_restx import Api, Resource
from api.maapapp import app as main_app # For FLASK_DEBUG setting
from api.restplus import api as main_api # The actual api instance from restplus
from api.utils.security_utils import (
    InvalidFileTypeError,
    FileSizeTooLargeError,
    InvalidRequestError,
    AuthenticationError,
    ExternalServiceError,
)
from api import settings # To manipulate FLASK_DEBUG

# Create a new Flask app instance for testing error handlers in isolation if needed,
# or use the main app's test client. Using main_app to ensure it uses the same error handlers.
# However, main_api is already initialized with main_app. We need to add a test namespace.

# Test Namespace for triggering errors
ns_test_errors = main_api.namespace('test_errors', description='Namespace for testing error handlers')

@ns_test_errors.route('/invalid_file_type')
class TriggerInvalidFileType(Resource):
    def get(self):
        raise InvalidFileTypeError("Test: Invalid file type triggered.")

@ns_test_errors.route('/file_size_too_large')
class TriggerFileSizeTooLarge(Resource):
    def get(self):
        raise FileSizeTooLargeError("Test: File size too large triggered.")

@ns_test_errors.route('/invalid_request')
class TriggerInvalidRequest(Resource):
    def get(self):
        raise InvalidRequestError("Test: Invalid request triggered.")

@ns_test_errors.route('/authentication_error')
class TriggerAuthenticationError(Resource):
    def get(self):
        raise AuthenticationError("Test: Authentication error triggered.")

@ns_test_errors.route('/external_service_error')
class TriggerExternalServiceError(Resource):
    def get(self):
        raise ExternalServiceError("Test: External service error triggered.")

@ns_test_errors.route('/generic_exception')
class TriggerGenericException(Resource):
    def get(self):
        raise Exception("Test: Generic exception triggered.")

@ns_test_errors.route('/http_exception_werkzeug')
class TriggerHttpExceptionWerkzeug(Resource):
    def get(self):
        from werkzeug.exceptions import NotFound # Example of a standard HTTPException
        raise NotFound("Test: Werkzeug HTTP exception triggered.")


class TestErrorHandlers(unittest.TestCase):

    def setUp(self):
        self.app = main_app.test_client()
        # Ensure our test namespace is on the main api for these tests
        # This should ideally be part of app setup for tests if not already.
        # For this test, we assume main_api used by main_app.test_client() includes ns_test_errors.
        # If api.init_app(blueprint) was called in maapapp.py AFTER api.add_namespace(ns_test_errors)
        # it might not be registered. Let's assume it is.
        # A better way would be to have a fixture that yields a test client with the ns registered.

        self.original_flask_debug = settings.FLASK_DEBUG

    def tearDown(self):
        settings.FLASK_DEBUG = self.original_flask_debug


    def _check_error_response(self, response, expected_status_code, expected_message_substring):
        self.assertEqual(response.status_code, expected_status_code)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("message", response_data)
        self.assertIn(expected_message_substring, response_data["message"])
        self.assertEqual(response_data.get("code"), expected_status_code)

    def test_invalid_file_type_error_handler(self):
        response = self.app.get('/api/test_errors/invalid_file_type')
        self._check_error_response(response, 400, "Test: Invalid file type triggered.")

    def test_file_size_too_large_error_handler(self):
        response = self.app.get('/api/test_errors/file_size_too_large')
        self._check_error_response(response, 413, "Test: File size too large triggered.")

    def test_invalid_request_error_handler(self):
        response = self.app.get('/api/test_errors/invalid_request')
        self._check_error_response(response, 400, "Test: Invalid request triggered.")

    def test_authentication_error_handler(self):
        response = self.app.get('/api/test_errors/authentication_error')
        self._check_error_response(response, 401, "Test: Authentication error triggered.")

    def test_external_service_error_handler(self):
        response = self.app.get('/api/test_errors/external_service_error')
        self._check_error_response(response, 503, "Test: External service error triggered.")

    def test_werkzeug_http_exception_handler(self):
        """ Test that a standard werkzeug HTTPException is handled correctly. """
        response = self.app.get('/api/test_errors/http_exception_werkzeug')
        # NotFound is a 404
        self._check_error_response(response, 404, "Test: Werkzeug HTTP exception triggered.")


    def test_generic_exception_handler_debug_true(self):
        settings.FLASK_DEBUG = True
        main_app.config['DEBUG'] = True # Ensure app itself is in debug mode

        response = self.app.get('/api/test_errors/generic_exception')
        self.assertEqual(response.status_code, 500)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("message", response_data)
        self.assertEqual(response_data["message"], "Test: Generic exception triggered.") # Debug shows actual message
        self.assertEqual(response_data.get("code"), 500) # Should include code field
        self.assertEqual(response_data.get("type"), "Exception") # Debug shows type

    def test_generic_exception_handler_debug_false(self):
        settings.FLASK_DEBUG = False
        main_app.config['DEBUG'] = False # Ensure app itself is NOT in debug mode

        response = self.app.get('/api/test_errors/generic_exception')
        self.assertEqual(response.status_code, 500)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("message", response_data)
        self.assertEqual(response_data["message"], "An internal server error occurred. Please try again later.")
        self.assertEqual(response_data.get("code"), 500) # Should include code field
        self.assertNotIn("type", response_data) # Type should not be exposed


if __name__ == '__main__':
    # This is tricky because main_api is already configured.
    # We need to ensure ns_test_errors is added before running tests.
    # One way:
    # with main_app.app_context():
    #    main_api.add_namespace(ns_test_errors) # This might be too late or not work as expected
    # Or, structure test app setup more carefully.
    # For now, assume the test runner (e.g. pytest) handles app context or it's run via flask test.
    # If running this file directly:
    if not main_api.namespaces or ns_test_errors.name not in [ns.name for ns in main_api.namespaces]:
         # This is a bit of a hack for direct execution. Proper test setup is better.
         # It might not work if the blueprint is already registered.
         print("Manually adding test namespace for direct script execution (might not be fully effective).")
         main_api.add_namespace(ns_test_errors)
         # If blueprint is already registered, adding namespace might not update routes.
         # This highlights complexity of modifying live Flask app for tests this way.

    unittest.main()
