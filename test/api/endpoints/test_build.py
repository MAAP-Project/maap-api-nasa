import unittest
import json
import uuid
from unittest.mock import patch, MagicMock
from datetime import datetime
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.role import Role
from api.models.build import Build


class TestBuildEndpoints(unittest.TestCase):
    """
    Test suite for build endpoints
    Tests build creation, status monitoring, and webhook handling
    """

    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
            # Clear any existing test data in proper order to respect foreign key constraints
            db.session.query(Build).delete()
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()
            
            # Create required roles
            self._create_roles()
            
        # Create test client
        self.client = app.test_client()

    def tearDown(self):
        """Clean up after each test."""
        with app.app_context():
            # Delete in proper order to respect foreign key constraints
            db.session.query(Build).delete()
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()

    def _create_roles(self):
        """Create the required role records for testing."""
        with app.app_context():
            guest_role = Role(role_name=Role.ROLE_NAME_GUEST, id=Role.ROLE_GUEST)
            member_role = Role(role_name=Role.ROLE_NAME_MEMBER, id=Role.ROLE_MEMBER)
            admin_role = Role(role_name=Role.ROLE_NAME_ADMIN, id=Role.ROLE_ADMIN)
            
            db.session.add(guest_role)
            db.session.add(member_role)
            db.session.add(admin_role)
            db.session.commit()

    def _create_test_user(self, username='testuser'):
        """Create a test user for authentication."""
        with app.app_context():
            role = db.session.query(Role).filter_by(role_name=Role.ROLE_NAME_MEMBER).first()
            user = Member(
                username=username,
                first_name='Test',
                last_name='User',
                email='test@example.com',
                role_id=role.id
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def _create_test_session(self, member_id, session_key="test-session-key"):
        """Create a test session for authentication tests."""
        with app.app_context():
            session = MemberSession(
                member_id=member_id,
                session_key=session_key,
                creation_date=datetime.now()
            )
            db.session.add(session)
            db.session.commit()
            return session

    def _make_authenticated_request(self, method, url, data=None, content_type='application/json', member_id=None):
        """Helper to make authenticated requests using proxy-ticket authentication."""
        if member_id is None:
            member_id = self._create_test_user()
        
        session_key = "test-session-token-12345"
        session = self._create_test_session(member_id, session_key)
        headers = {'proxy-ticket': session_key}
        
        with patch('api.auth.cas_auth.decrypt_proxy_ticket') as mock_decrypt:
            mock_decrypt.return_value = "test-session-token-12345"
            
            if method.upper() == 'GET':
                return self.client.get(url, headers=headers)
            elif method.upper() == 'POST':
                return self.client.post(url, data=data, content_type=content_type, headers=headers)
            elif method.upper() == 'PUT':
                return self.client.put(url, data=data, content_type=content_type, headers=headers)
            elif method.upper() == 'DELETE':
                return self.client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

    @patch('api.endpoints.build._trigger_build_pipeline')
    def test_create_build_success(self, mock_trigger):
        """Test successful build creation"""
        
        mock_pipeline = MagicMock()
        mock_pipeline.id = 12345
        mock_pipeline.web_url = 'https://gitlab.com/pipeline/12345'
        mock_trigger.return_value = mock_pipeline
        
        payload = {
            'code_repository': 'https://gitlab.com/test/repo.git',
            'algorithm_name': 'test-algorithm',
            'algorithm_version': 'main',
            'build_command': 'make build'
        }
        
        response = self._make_authenticated_request(
            'POST',
            '/api/build',
            data=json.dumps(payload)
        )
        
        self.assertEqual(response.status_code, 202)
        data = json.loads(response.data)
        self.assertIn('build_id', data)
        self.assertEqual(data['status'], 'accepted')
        self.assertIn('pipelineLink', data)
        self.assertEqual(data['pipelineLink']['href'], 'https://gitlab.com/pipeline/12345')

    @patch('api.endpoints.build._trigger_build_pipeline')
    def test_create_build_missing_code_repository(self, mock_trigger):
        """Test build creation with missing code repository"""
        
        mock_pipeline = MagicMock()
        mock_pipeline.id = 12345
        mock_pipeline.web_url = 'https://gitlab.com/pipeline/12345'
        mock_trigger.return_value = mock_pipeline
        payload = {
            'algorithm_name': 'test-algorithm',
            'algorithm_version': 'main'
        }
        
        response = self._make_authenticated_request(
            'POST',
            '/api/build',
            data=json.dumps(payload)
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('code_repository', data['detail'])

    def test_get_builds_list_success(self):
        """Test successful retrieval of user's builds list"""
        user_id = self._create_test_user()
        
        with app.app_context():
            # Create multiple test builds for the user
            build_id1 = str(uuid.uuid4())
            build1 = Build(
                build_id=build_id1,
                requester=user_id,
                repository_url='https://gitlab.com/test/repo1.git',
                branch_ref='main',
                status='running',
                pipeline_url='https://gitlab.com/pipeline/1'
            )
            
            build_id2 = str(uuid.uuid4())
            build2 = Build(
                build_id=build_id2,
                requester=user_id,
                repository_url='https://gitlab.com/test/repo2.git',
                branch_ref='dev',
                status='successful'
            )
            
            db.session.add(build1)
            db.session.add(build2)
            db.session.commit()
        
        response = self._make_authenticated_request('GET', '/api/build', member_id=user_id)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('builds', data)
        self.assertEqual(len(data['builds']), 2)
        
        # Check build data structure
        build_data = data['builds'][0]
        self.assertIn('build_id', build_data)
        self.assertIn('status', build_data)
        self.assertIn('created', build_data)
        self.assertIn('repository_url', build_data)
        self.assertIn('branch_ref', build_data)
        self.assertIn('links', build_data)

    def test_get_builds_list_empty(self):
        """Test retrieval of builds list when user has no builds"""
        
        response = self._make_authenticated_request('GET', '/api/build')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('builds', data)
        self.assertEqual(len(data['builds']), 0)

    def test_get_build_success(self):
        """Test successful build retrieval"""
        user_id = self._create_test_user()
        
        with app.app_context():
            # Create a test build
            build_id = str(uuid.uuid4())
            build = Build(
                build_id=build_id,
                requester=user_id,
                repository_url='https://gitlab.com/test/repo.git',
                branch_ref='main',
                status='running'
            )
            db.session.add(build)
            db.session.commit()
        
        response = self._make_authenticated_request('GET', f'/api/build/{build_id}', member_id=user_id)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['build_id'], build_id)
        self.assertEqual(data['status'], 'running')

    def test_get_build_not_found(self):
        """Test build retrieval for non-existent build"""
        build_id = str(uuid.uuid4())
        response = self._make_authenticated_request(
            'GET',
            f'/api/build/{build_id}'
        )
        
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()