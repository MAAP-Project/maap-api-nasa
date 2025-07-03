import unittest
import responses
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
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

    @patch('api.auth.cas_auth.urlopen')
    @patch('api.auth.cas_auth.validate_proxy')
    def test_user_can_authenticate_with_valid_cas_credentials(self, mock_validate_proxy, mock_urlopen):
        """Test: User can authenticate with valid CAS credentials"""
        with app.app_context():
            # Given a user with valid CAS credentials
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
            result = validate("http://example.com", "ST-invalid")
            
            # Then authentication should fail
            assert result is None

    def test_protected_endpoints_reject_unauthenticated_requests(self):
        """Test: Protected endpoints reject unauthenticated requests"""
        with app.test_client() as client:
            # Given an unauthenticated user
            # When they attempt to access a protected endpoint
            response = client.get('/api/members/self')
            
            # Then they should receive a 401 Unauthorized response
            # Note: The actual response might be 403 or 302 depending on implementation
            assert response.status_code in [401, 403, 302]

    def test_validate_proxy_with_valid_active_session(self):
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
            
            # When validate_proxy is called with the valid ticket
            with patch('api.auth.cas_auth.decrypt_proxy_ticket') as mock_decrypt:
                mock_decrypt.return_value = 'PGT-12345-test'
                result = validate_proxy('encrypted-ticket')
            
            # Then the active session should be returned
            assert result is not None
            assert result.session_key == 'PGT-12345-test'
            assert result.member.username == 'testuser'

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
            
            # When validate_proxy is called with the expired ticket
            with patch('api.auth.cas_auth.decrypt_proxy_ticket') as mock_decrypt, \
                 patch('api.auth.cas_auth.validate_cas_request') as mock_validate_cas, \
                 app.test_request_context('/test'):
                mock_decrypt.return_value = 'PGT-expired-test'
                mock_validate_cas.return_value = (False, {})
                
                result = validate_proxy('encrypted-expired-ticket')
            
            # Then None should be returned (session expired)
            assert result is None

    @responses.activate
    def test_validate_bearer_with_valid_token(self):
        """Test: validate_bearer works with valid bearer token"""
        with app.app_context():
            # Given a valid bearer token
            responses.add(
                responses.GET,
                app.config.get('CAS_SERVER', 'http://localhost') + '/oauth2.0/profile',
                json={'preferred_username': 'testuser', 'email': 'test@example.com'},
                status=200
            )
            
            # When validate_bearer is called
            result = validate_bearer('valid-bearer-token')
            
            # Then user profile should be returned
            assert result is not None
            assert result['preferred_username'] == 'testuser'
            assert result['email'] == 'test@example.com'

    @responses.activate
    def test_validate_bearer_with_invalid_token(self):
        """Test: validate_bearer fails with invalid bearer token"""
        with app.app_context():
            # Given an invalid bearer token
            responses.add(
                responses.GET,
                app.config.get('CAS_SERVER', 'http://localhost') + '/oauth2.0/profile',
                status=401
            )
            
            # When validate_bearer is called
            result = validate_bearer('invalid-bearer-token')
            
            # Then None should be returned
            assert result is None

    def test_start_member_session_creates_new_member(self):
        """Test: start_member_session creates new member when auto_create_member=True"""
        with app.app_context():
            # Given CAS response with user attributes
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