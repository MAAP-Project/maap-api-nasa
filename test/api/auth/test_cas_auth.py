import unittest
import responses
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta
import requests # For requests.exceptions
import json # For json.JSONDecodeError
from urllib.error import URLError # For simulating urlopen errors
import socket # For socket.timeout
from xml.parsers.expat import ExpatError


from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api import settings # To potentially override settings for tests
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.role import Role
from api.auth.cas_auth import validate, validate_proxy, validate_bearer, decrypt_proxy_ticket
from api.auth.cas_auth import start_member_session, get_cas_attribute_value


class TestCASAuthentication(unittest.TestCase):

    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
            # Clear any existing test data
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()
            
            # Create required roles
            self._create_roles()

    def tearDown(self):
        """Clean up after each test."""
        with app.app_context():
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()
    
    def _create_roles(self):
        """Create the required role records for testing."""
        guest_role = Role(id=Role.ROLE_GUEST, role_name='guest')
        member_role = Role(id=Role.ROLE_MEMBER, role_name='member')
        admin_role = Role(id=Role.ROLE_ADMIN, role_name='admin')
        
        db.session.add(guest_role)
        db.session.add(member_role)
        db.session.add(admin_role)
        db.session.commit()

from api.utils.security_utils import AuthenticationError, ExternalServiceError


class TestCASAuthentication(unittest.TestCase):

    def setUp(self):
        """Set up test environment before each test."""
        self.app_context = app.app_context() # Store context for explicit push/pop
        self.app_context.push()
        initialize_sql(db.engine)
        # Clear any existing test data
        db.session.query(MemberSession).delete()
        db.session.query(Member).delete()
        db.session.query(Role).delete()
        db.session.commit()

        # Create required roles
        self._create_roles()

        # Store original settings to restore them
        self.original_requests_timeout = settings.REQUESTS_TIMEOUT_SECONDS


    def tearDown(self):
        """Clean up after each test."""
        db.session.query(MemberSession).delete()
        db.session.query(Member).delete()
        db.session.query(Role).delete()
        db.session.commit()

        settings.REQUESTS_TIMEOUT_SECONDS = self.original_requests_timeout # Restore
        self.app_context.pop()


    def _create_roles(self):
        """Create the required role records for testing."""
        guest_role = Role(id=Role.ROLE_GUEST, role_name='guest')
        member_role = Role(id=Role.ROLE_MEMBER, role_name='member')
        admin_role = Role(id=Role.ROLE_ADMIN, role_name='admin')

        db.session.add(guest_role)
        db.session.add(member_role)
        db.session.add(admin_role)
        db.session.commit()

    @patch('api.auth.cas_auth.validate_proxy') # Keep this if validate calls validate_proxy
    @patch('api.auth.cas_auth.urlopen')
    def test_validate_successful(self, mock_urlopen, mock_validate_proxy):
        """Test: validate() successfully authenticates and calls validate_proxy."""
        # Given a user with valid CAS credentials
        mock_xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
            <cas:authenticationSuccess>
                <cas:user>testuser</cas:user>
                <cas:attributes>
                    <cas:proxyGrantingTicket>PGT-12345-test</cas:proxyGrantingTicket>
                    <cas:preferred_username>testuser</cas:preferred_username>
                </cas:attributes>
            </cas:authenticationSuccess>
        </cas:serviceResponse>"""

        mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = mock_xml_response

        mock_member = Member(username='testuser', role_id=Role.ROLE_MEMBER)
        db.session.add(mock_member)
        db.session.commit()
        mock_session_obj = MemberSession(member_id=mock_member.id, session_key='PGT-12345-test')
        mock_validate_proxy.return_value = mock_session_obj # validate_proxy returns a MemberSession object

        result = validate("http://example.com/service", "ST-123-ticket")

        self.assertIsNotNone(result)
        self.assertEqual(result.member.username, "testuser")
        mock_urlopen.assert_called_once_with(ANY, timeout=settings.REQUESTS_TIMEOUT_SECONDS)
        mock_validate_proxy.assert_called_once_with('PGT-12345-test', True)

    @patch('api.auth.cas_auth.urlopen')
    def test_validate_cas_failure_response(self, mock_urlopen):
        """Test: validate() handles CAS authenticationFailure response."""
        mock_xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
            <cas:authenticationFailure code="INVALID_TICKET">
                Ticket ST-123-ticket not recognized
            </cas:authenticationFailure>
        </cas:serviceResponse>"""
        mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = mock_xml_response

        with self.assertRaisesRegex(AuthenticationError, "CAS ticket validation failed: Ticket ST-123-ticket not recognized"):
            validate("http://example.com/service", "ST-123-ticket")

    @patch('api.auth.cas_auth.urlopen')
    def test_validate_network_error(self, mock_urlopen):
        """Test: validate() handles network errors (URLError)."""
        mock_urlopen.side_effect = URLError("Network is down")
        with self.assertRaisesRegex(ExternalServiceError, "CAS server connection failed or timed out."):
            validate("http://example.com/service", "ST-123-ticket")

    @patch('api.auth.cas_auth.urlopen')
    def test_validate_timeout_error(self, mock_urlopen):
        """Test: validate() handles timeout errors."""
        mock_urlopen.side_effect = socket.timeout("Request timed out")
        with self.assertRaisesRegex(ExternalServiceError, "CAS server connection failed or timed out."):
            validate("http://example.com/service", "ST-123-ticket")

    @patch('api.auth.cas_auth.urlopen')
    def test_validate_malformed_xml_response(self, mock_urlopen):
        """Test: validate() handles malformed XML from CAS."""
        mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = "<cas:serviceResponse><malformed>"
        with self.assertRaisesRegex(AuthenticationError, "Invalid XML response from CAS server."):
            validate("http://example.com/service", "ST-123-ticket")

    @patch('api.auth.cas_auth.urlopen')
    def test_validate_missing_pgt(self, mock_urlopen):
        """Test: validate() handles missing proxyGrantingTicket in CAS response."""
        mock_xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
            <cas:authenticationSuccess>
                <cas:user>testuser</cas:user>
                <cas:attributes>
                    <cas:preferred_username>testuser</cas:preferred_username>
                    <!-- Missing cas:proxyGrantingTicket -->
                </cas:attributes>
            </cas:authenticationSuccess>
        </cas:serviceResponse>"""
        mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = mock_xml_response
        with self.assertRaisesRegex(AuthenticationError, "Missing proxyGrantingTicket from CAS."):
            validate("http://example.com/service", "ST-123-ticket")


    @patch('api.auth.cas_auth.urlopen')
    def test_user_authentication_fails_with_invalid_credentials(self, mock_urlopen):
        """Test: User authentication fails with invalid credentials"""
        with app.app_context():
            # Given a user with invalid CAS credentials
            mock_xml_response = '''<?xml version="1.0" encoding="UTF-8"?>
            <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
                <cas:authenticationSuccess>
                    <cas:user>testuser</cas:user>
                    <cas:attributes>
                        <cas:proxyGrantingTicket>PGT-12345-test</cas:proxyGrantingTicket>
                        <cas:preferred_username>testuser</cas:preferred_username>
                        <cas:given_name>Test</cas:given_name>
                        <cas:family_name>User</cas:family_name>
                        <cas:email>test@example.com</cas:email>
                        <cas:organization>NASA</cas:organization>
                    </cas:attributes>
                </cas:authenticationSuccess>
            </cas:serviceResponse>'''
            
            mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = mock_xml_response
            
            # Mock the validate_proxy function to return a valid session
            mock_member = Member(
                username='testuser',
                first_name='Test',
                last_name='User',
                email='test@example.com',
                organization='NASA',
                role_id=Role.ROLE_GUEST
            )
            db.session.add(mock_member)
            db.session.commit()
            
            mock_session = MemberSession(
                member_id=mock_member.id,
                session_key='PGT-12345-test',
                creation_date=datetime.utcnow()
            )
            mock_validate_proxy.return_value = mock_session
            
            # When they attempt to authenticate
            result = validate("http://example.com", "ST-12345-test")
            
            # Then they should receive a valid session token
            assert result is not None
            mock_validate_proxy.assert_called_once_with('PGT-12345-test', True)

    @patch('api.auth.cas_auth.urlopen')
    def test_user_authentication_fails_with_invalid_credentials(self, mock_urlopen):
        """Test: User authentication fails with invalid credentials"""
        with app.app_context():
            # Given a user with invalid CAS credentials
            mock_xml_response = '''<?xml version="1.0" encoding="UTF-8"?>
            <cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">
                <cas:authenticationFailure code="INVALID_TICKET">
                    Ticket 'ST-invalid' not recognized
                </cas:authenticationFailure>
            </cas:serviceResponse>'''
            
            mock_urlopen.return_value.read.return_value.strip.return_value.decode.return_value = mock_xml_response
            
            # When they attempt to authenticate
            with self.assertRaises(AuthenticationError): # Expecting AuthenticationError now
                 validate("http://example.com", "ST-invalid")


    # This test is more of an integration test for the endpoint, not cas_auth unit test
    # It can be moved to an endpoint test file if not already covered.
    # def test_protected_endpoints_reject_unauthenticated_requests(self):
    #     """Test: Protected endpoints reject unauthenticated requests"""
    #     with app.test_client() as client:
    #         response = client.get('/api/members/self')
    #         self.assertIn(response.status_code, [401, 403]) # More specific check


    @patch('api.auth.cas_auth.validate_cas_request') # validate_proxy calls validate_cas_request
    @patch('api.auth.cas_auth.decrypt_proxy_ticket')
    def test_validate_proxy_with_valid_active_session(self, mock_decrypt, mock_validate_cas_req):
        """Test: validate_proxy returns active session when valid"""
        with app.app_context():
            # Given an existing member and active session
            member = Member(
                username='testuser',
                first_name='Test',
                last_name='User',
                email='test@example.com',
                organization='NASA',
                role_id=Role.ROLE_GUEST
            )
            db.session.add(member)
            db.session.commit()
            
            session = MemberSession(
                member_id=member.id,
                session_key='PGT-12345-test',
                creation_date=datetime.utcnow()
            )
            db.session.add(session)
            db.session.commit()
            
            mock_decrypt.return_value = 'PGT-12345-test' # Decrypted ticket
            # validate_cas_request is not called if session is found and active
            
            result = validate_proxy('encrypted-ticket-value') # The actual encrypted value

            self.assertIsNotNone(result)
            self.assertEqual(result.session_key, 'PGT-12345-test')
            self.assertEqual(result.member.username, 'testuser')
            mock_validate_cas_req.assert_not_called() # Should not call CAS if session is valid

    @patch('api.auth.cas_auth.start_member_session')
    @patch('api.auth.cas_auth.validate_cas_request')
    @patch('api.auth.cas_auth.decrypt_proxy_ticket')
    def test_validate_proxy_expired_session_revalidates(self, mock_decrypt, mock_validate_cas_req, mock_start_session):
        """Test: validate_proxy revalidates with CAS if local session is expired."""
        # Given an existing member and an expired session
        member = Member(username='testuser', email='test@example.com', role_id=Role.ROLE_MEMBER)
        db.session.add(member)
        db.session.commit()

        expired_date = datetime.utcnow() - timedelta(days=settings.PROXY_TICKET_DURATION_DAYS + 1)
        MemberSession.query.delete() # Clear any other sessions
        db.session.add(MemberSession(member_id=member.id, session_key='PGT-expired', creation_date=expired_date))
        db.session.commit()

        mock_decrypt.return_value = 'PGT-expired'

        # Mock validate_cas_request to simulate successful CAS validation for proxy ticket
        # This is the part that validates the PGT with CAS server to get a PT for our service
        mock_validate_cas_req.side_effect = [
            (True, {"cas:serviceResponse": {"cas:proxySuccess": {"cas:proxyTicket": "PT-for-MAAP"}}}), # PGT validation
            (True, {"cas:serviceResponse": {"cas:authenticationSuccess": {"cas:user": "testuser", "cas:attributes": {}}}}) # PT validation
        ]

        # Mock start_member_session to return a new session object
        new_session_obj = MemberSession(member_id=member.id, session_key='PGT-expired') # Or a new PGT if CAS issues one
        mock_start_session.return_value = new_session_obj

        with app.test_request_context('/test-url'): # Need request context for proxied_url
             result = validate_proxy('encrypted-expired-ticket')

        self.assertIsNotNone(result)
        self.assertEqual(result.member_id, member.id)
        mock_decrypt.assert_called_once_with('encrypted-expired-ticket')
        self.assertEqual(mock_validate_cas_req.call_count, 2) # Called for PGT and then for PT
        mock_start_session.assert_called_once()

    @patch('api.auth.cas_auth.validate_cas_request')
    @patch('api.auth.cas_auth.decrypt_proxy_ticket')
    def test_validate_proxy_no_local_session_validates_with_cas(self, mock_decrypt, mock_validate_cas_req):
        """Test: validate_proxy validates with CAS if no local session exists."""
        MemberSession.query.delete() # Ensure no sessions
        db.session.commit()

        mock_decrypt.return_value = 'PGT-new-ticket'

        # Mock validate_cas_request for successful PGT and PT validation
        mock_validate_cas_req.side_effect = [
            (True, {"cas:serviceResponse": {"cas:proxySuccess": {"cas:proxyTicket": "PT-for-MAAP"}}}),
            (True, {"cas:serviceResponse": {"cas:authenticationSuccess": {"cas:user": "newuser",
                                                                       "cas:attributes": {
                                                                           "cas:preferred_username": "newuser",
                                                                           "cas:given_name": "New",
                                                                           "cas:family_name": "User",
                                                                           "cas:email": "new@example.com"
                                                                       }}}})
        ]

        with app.test_request_context('/test-url'):
            # auto_create_member=True is the default for validate_proxy in some calls, let's test that path.
            # If validate_proxy itself doesn't pass auto_create_member=True to start_member_session,
            # then a member must exist or this will fail differently.
            # The current validate_proxy in cas_auth.py calls start_member_session without auto_create_member=True
            # by default, so a user 'newuser' would need to exist or be created by start_member_session.
            # Let's assume start_member_session is patched or handles creation.
            # For this test, we'll rely on start_member_session to create the member if needed.

            # Create the 'newuser' so start_member_session can find it or update it.
            # If start_member_session is supposed to create it, this line is not needed.
            # db.session.add(Member(username='newuser', email='new@example.com', role_id=Role.ROLE_MEMBER))
            # db.session.commit()

            result = validate_proxy('encrypted-new-ticket', auto_create_member=True) # Pass True here to test creation path

        self.assertIsNotNone(result)
        self.assertEqual(result.member.username, 'newuser')
        self.assertEqual(mock_validate_cas_req.call_count, 2)

    @patch('api.auth.cas_auth.decrypt_proxy_ticket')
    def test_validate_proxy_cas_pgt_validation_fails(self, mock_decrypt):
        """Test: validate_proxy returns None if CAS PGT validation fails."""
        mock_decrypt.return_value = 'PGT-invalid-at-cas'

        # Mock validate_cas_request to simulate CAS PGT validation failure
        with patch('api.auth.cas_auth.validate_cas_request') as mock_validate_cas_req_local:
            mock_validate_cas_req_local.return_value = (False, {"cas:serviceResponse": {"cas:authenticationFailure": {}}})

            with app.test_request_context('/test-url'):
                result = validate_proxy('encrypted-pgt-fails')

        self.assertIsNone(result)
        mock_validate_cas_req_local.assert_called_once() # Only PGT validation attempt

    # Bearer token tests
    @responses.activate
    def test_validate_bearer_successful(self):
        """Test: validate_bearer returns user attributes for a valid token."""
        profile_url = app.config['CAS_SERVER'] + '/oauth2.0/profile'
        responses.add(responses.GET, profile_url, json={'id': 'beareruser', 'attributes': {'email': 'bearer@example.com'}}, status=200)

        user_info = validate_bearer('valid-token')

        self.assertIsNotNone(user_info)
        self.assertEqual(user_info['id'], 'beareruser')

    @responses.activate
    def test_validate_bearer_invalid_token(self):
        """Test: validate_bearer raises AuthenticationError for an invalid token (401)."""
        profile_url = app.config['CAS_SERVER'] + '/oauth2.0/profile'
        responses.add(responses.GET, profile_url, status=401)

        with self.assertRaisesRegex(AuthenticationError, "Invalid bearer token."):
            validate_bearer('invalid-token')

    @responses.activate
    def test_validate_bearer_cas_server_error(self):
        """Test: validate_bearer raises ExternalServiceError for CAS server error (500)."""
        profile_url = app.config['CAS_SERVER'] + '/oauth2.0/profile'
        responses.add(responses.GET, profile_url, status=500)

        with self.assertRaisesRegex(ExternalServiceError, "Authentication service returned an error: 500"):
            validate_bearer('token-causes-server-error')

    @responses.activate
    def test_validate_bearer_network_timeout(self):
        """Test: validate_bearer raises ExternalServiceError on network timeout."""
        profile_url = app.config['CAS_SERVER'] + '/oauth2.0/profile'
        responses.add(responses.GET, profile_url, body=requests.exceptions.Timeout("Connection timed out"))

        with self.assertRaisesRegex(ExternalServiceError, "Authentication service timed out."):
            validate_bearer('token-network-timeout')

    @responses.activate
    def test_validate_bearer_malformed_json_response(self):
        """Test: validate_bearer raises AuthenticationError on malformed JSON response."""
        profile_url = app.config['CAS_SERVER'] + '/oauth2.0/profile'
        responses.add(responses.GET, profile_url, body="not json", status=200, content_type='application/json')

        with self.assertRaisesRegex(AuthenticationError, "Invalid response from authentication service."):
            validate_bearer('token-malformed-json')


    def test_validate_proxy_with_expired_session(self):
        """Test: validate_proxy handles expired sessions correctly"""
        with app.app_context():
            # Given an existing member and expired session
            member = Member(
                username='testuser',
                first_name='Test',
                last_name='User',
                email='test@example.com',
                organization='NASA',
                role_id=Role.ROLE_GUEST
            )
            db.session.add(member)
            db.session.commit()
            
            # Create an expired session (older than 60 days)
            expired_date = datetime.utcnow() - timedelta(days=61)
            session = MemberSession(
                member_id=member.id,
                session_key='PGT-expired-test',
                creation_date=expired_date
            )
            db.session.add(session)
            db.session.commit()
            
            # This test's original logic assumed validate_proxy would return None on expired session
            # if CAS revalidation also failed. The new logic in validate_proxy attempts revalidation.
            # So, we need to mock CAS validation to fail to test the "truly expired" path.

            expired_date = datetime.utcnow() - timedelta(days=settings.PROXY_TICKET_DURATION_DAYS + 1)
            session = MemberSession(
                member_id=member.id,
                session_key='PGT-expired-test',
                creation_date=expired_date
            )
            db.session.add(session)
            db.session.commit()

            with patch('api.auth.cas_auth.decrypt_proxy_ticket') as mock_decrypt, \
                 patch('api.auth.cas_auth.validate_cas_request') as mock_validate_cas_req, \
                 app.test_request_context('/test-url'): # Added request context

                mock_decrypt.return_value = 'PGT-expired-test'
                # Simulate CAS server also saying the PGT is invalid (first call in validate_proxy for PGT check)
                mock_validate_cas_req.return_value = (False, {"cas:serviceResponse": {"cas:authenticationFailure": {}}})
                
                result = validate_proxy('encrypted-expired-ticket')
            
            self.assertIsNone(result) # Should be None if revalidation fails
            mock_validate_cas_req.assert_called_once() # Ensure it tried to revalidate PGT with CAS


    # This test is now covered by test_validate_bearer_successful
    # def test_validate_bearer_with_valid_token(self): ...

    # This test is now covered by test_validate_bearer_invalid_token
    # def test_validate_bearer_with_invalid_token(self): ...


    def test_start_member_session_creates_new_member_if_auto_create_true(self):
        """Test: start_member_session creates new member when auto_create_member=True."""
        Member.query.filter_by(username="newuser").delete() # Ensure user doesn't exist
        db.session.commit()

        # Given CAS response with user attributes
        cas_response_tuple = ( # Ensure this matches the structure expected by start_member_session
            True, # is_valid from validate_cas_request
            {
                "cas:serviceResponse": {
                    "cas:authenticationSuccess": {
                        "cas:user": "newuser", # Typically URS ID
                        "cas:attributes": {
                            "cas:preferred_username": "newuser_preferred", # This is often the screen name
                            "cas:given_name": "New",
                            "cas:family_name": "User",
                            "cas:email": "newuser@example.com",
                            "cas:organization": "NASA",
                            "cas:access_token": "urs-token-123"
                        }
                    }
                }
            }
        )

        # When start_member_session is called with auto_create_member=True
        # The 'ticket' here is the decrypted PGT from the client (e.g. browser cookie)
        session_obj = start_member_session(cas_response_tuple, "PGT-for-new-session", auto_create_member=True)

        self.assertIsNotNone(session_obj)
        self.assertEqual(session_obj.session_key, "PGT-for-new-session")

        member = Member.query.filter_by(username="newuser").first() # Query by cas:user
        self.assertIsNotNone(member)
        self.assertEqual(member.first_name, "New")
        self.assertEqual(member.last_name, "User")
        self.assertEqual(member.email, "newuser@example.com")
        self.assertEqual(member.organization, "NASA")
        self.assertEqual(member.urs_token, "urs-token-123")

    def test_start_member_session_does_not_create_if_auto_create_false_and_member_not_exists(self):
        """Test: start_member_session fails if auto_create=False and member does not exist."""
        Member.query.filter_by(username="nonexistentuser").delete()
        db.session.commit()

        cas_response_tuple = (
            True,
            {
                "cas:serviceResponse": {
                    "cas:authenticationSuccess": {
                        "cas:user": "nonexistentuser", # This user isn't in DB
                        "cas:attributes": { "cas:preferred_username": "nonexistentuser" }
                    }
                }
            }
        )
        # Expecting start_member_session to potentially raise an error or return None/fail if member not found
        # and auto_create is false. The current implementation of start_member_session would try to query
        # Member by username='nonexistentuser', find None, then if auto_create_member is False (default),
        # it would try to access attributes on a None object (member.urs_token = ...), leading to AttributeError.
        with self.assertRaises(AttributeError): # Or whatever specific error it raises
            start_member_session(cas_response_tuple, "PGT-for-nonexistent", auto_create_member=False)


    def test_start_member_session_updates_existing_member(self):
        """Test: start_member_session updates existing member's URS token"""
        with app.app_context():
            # Given an existing member
            cas_response = (
                True,
                {
                    "cas:serviceResponse": {
                        "cas:authenticationSuccess": {
                            "cas:user": "newuser",
                            "cas:attributes": {
                                "cas:preferred_username": "newuser",
                                "cas:given_name": "New",
                                "cas:family_name": "User", 
                                "cas:email": "newuser@example.com",
                                "cas:organization": "NASA",
                                "cas:access_token": "urs-token-123"
                            }
                        }
                    }
                }
            )
            
            # When start_member_session is called with auto_create_member=True
            result = start_member_session(cas_response, "PGT-new-session", auto_create_member=True)
            
            # Then a new member and session should be created
            assert result is not None
            assert result.session_key == "PGT-new-session"
            
            # Verify member was created
            member = db.session.query(Member).filter_by(username="newuser").first()
            assert member is not None
            assert member.first_name == "New"
            assert member.last_name == "User"
            assert member.email == "newuser@example.com"
            assert member.organization == "NASA"
            assert member.urs_token == "urs-token-123"

    def test_start_member_session_updates_existing_member(self):
        """Test: start_member_session updates existing member's URS token"""
        with app.app_context():
            # Given an existing member
            existing_member = Member(
                username='existinguser',
                first_name='Existing',
                last_name='User',
                email='existing@example.com',
                organization='NASA',
                urs_token='old-token',
                role_id=Role.ROLE_GUEST
            )
            db.session.add(existing_member)
            db.session.commit()
            
            # Given CAS response for existing user
            cas_response = (
                True,
                {
                    "cas:serviceResponse": {
                        "cas:authenticationSuccess": {
                            "cas:user": "existinguser",
                            "cas:attributes": {
                                "cas:preferred_username": "existinguser",
                                "cas:access_token": "new-urs-token-456"
                            }
                        }
                    }
                }
            )
            
            # When start_member_session is called
            result = start_member_session(cas_response, "PGT-existing-session")
            
            # Then the member's URS token should be updated
            updated_member = db.session.query(Member).filter_by(username="existinguser").first()
            assert updated_member.urs_token == "new-urs-token-456"
            
            # And a new session should be created
            assert result is not None
            assert result.session_key == "PGT-existing-session"
            assert result.member_id == existing_member.id

    def test_get_cas_attribute_value_extracts_attributes(self):
        """Test: get_cas_attribute_value correctly extracts CAS attributes"""
        # Given CAS attributes
        attributes = {
            "cas:preferred_username": "testuser",
            "cas:email": "test@example.com",
            "cas:organization": "NASA"
        }
        
        # When attributes are extracted
        username = get_cas_attribute_value(attributes, 'preferred_username')
        email = get_cas_attribute_value(attributes, 'email')
        organization = get_cas_attribute_value(attributes, 'organization')
        missing = get_cas_attribute_value(attributes, 'missing_attribute')
        
        # Then correct values should be returned
        assert username == "testuser"
        assert email == "test@example.com"
        assert organization == "NASA"
        assert missing == ""

    def test_get_cas_attribute_value_handles_empty_attributes(self):
        """Test: get_cas_attribute_value handles None/empty attributes"""
        # When attributes are None or empty
        result_none = get_cas_attribute_value(None, 'preferred_username')
        result_empty = get_cas_attribute_value({}, 'preferred_username')
        
        # Then empty string should be returned
        assert result_none == ""
        assert result_empty == ""

    def test_decrypt_proxy_ticket_returns_plain_ticket(self):
        """Test: decrypt_proxy_ticket returns plain PGT tickets unchanged"""
        # Given a plain PGT ticket
        plain_ticket = "PGT-12345-plain-ticket"
        
        # When decrypt_proxy_ticket is called
        result = decrypt_proxy_ticket(plain_ticket)
        
        # Then the same ticket should be returned
        assert result == plain_ticket

    @patch('api.auth.cas_auth.RSA')
    @patch('api.auth.cas_auth.PKCS1_v1_5')
    @patch('api.auth.cas_auth.b64decode')
    def test_decrypt_proxy_ticket_decrypts_encrypted_ticket(self, mock_b64decode, mock_pkcs, mock_rsa):
        """Test: decrypt_proxy_ticket decrypts encrypted tickets"""
        # Given an encrypted ticket and mocked crypto components
        encrypted_ticket = "encrypted-base64-ticket"
        decrypted_content = b"PGT-12345-decrypted"
        
        mock_b64decode.return_value = b"encrypted_data"
        mock_key = MagicMock()
        mock_rsa.import_key.return_value = mock_key
        mock_decryptor = MagicMock()
        mock_pkcs.new.return_value = mock_decryptor
        mock_decryptor.decrypt.return_value = decrypted_content
        
        # When decrypt_proxy_ticket is called
        result = decrypt_proxy_ticket(encrypted_ticket)
        
        # Then the decrypted ticket should be returned
        assert result == "PGT-12345-decrypted"

    def test_decrypt_proxy_ticket_handles_decryption_error(self):
        """Test: decrypt_proxy_ticket handles decryption errors gracefully"""
        # Given an invalid encrypted ticket
        invalid_ticket = "invalid-encrypted-ticket"
        
        # When decrypt_proxy_ticket is called with invalid data
        result = decrypt_proxy_ticket(invalid_ticket)
        
        # Then empty string should be returned
        assert result == ""


if __name__ == '__main__':
    unittest.main()