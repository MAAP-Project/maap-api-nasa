import unittest
import json
import uuid
from unittest.mock import patch, MagicMock, ANY as mock_any
from datetime import datetime
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.role import Role
from api.models.build import Build
from api.endpoints.build import _validate_algorithm_name, _validate_algorithm_version
from api.utils.ogc_process_util import create_process_deployment


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
        
        # Use unique session key for each user
        session_key = f"test-session-token-{member_id}"
        session = self._create_test_session(member_id, session_key)
        headers = {'proxy-ticket': session_key}
        
        with patch('api.auth.cas_auth.decrypt_proxy_ticket') as mock_decrypt:
            mock_decrypt.return_value = session_key
            
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
            'build_command': 'make build',
            'base_container_url': 'ubuntu:20.04'
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
            'algorithm_version': 'main',
            'base_container_url': 'ubuntu:20.04'
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

    # Algorithm validation tests
    def test_validate_algorithm_name_success(self):
        """Test successful algorithm name validation"""
        valid_names = ['test-algo', 'my_algorithm', 'algo123', 'a1', 'test-algo-123_test']
        for name in valid_names:
            with self.subTest(name=name):
                result = _validate_algorithm_name(name)
                self.assertEqual(result, name)

    def test_validate_algorithm_name_failures(self):
        """Test algorithm name validation failures"""
        invalid_cases = [
            ('', 'algorithm_name is required'),
            (None, 'algorithm_name is required'),
            ('a', 'algorithm_name must be between 2 and 255 characters long'),
            ('a' * 256, 'algorithm_name must be between 2 and 255 characters long'),
            ('Test-Algorithm', 'algorithm_name can only contain lowercase letters'),
            ('test algo', 'algorithm_name can only contain lowercase letters'),
            ('test@algo', 'algorithm_name can only contain lowercase letters'),
            ('test.algo', 'algorithm_name can only contain lowercase letters')
        ]
        
        for name, expected_error in invalid_cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    _validate_algorithm_name(name)
                self.assertIn(expected_error.split()[0], str(cm.exception))

    def test_validate_algorithm_version_success(self):
        """Test successful algorithm version validation"""
        valid_versions = ['v1.0.0', 'main', 'dev-branch', 'V2.1_beta', '1.0', 'release_1.0-rc1']
        for version in valid_versions:
            with self.subTest(version=version):
                result = _validate_algorithm_version(version)
                self.assertEqual(result, version)

    def test_validate_algorithm_version_failures(self):
        """Test algorithm version validation failures"""
        invalid_cases = [
            ('', 'algorithm_version is required'),
            (None, 'algorithm_version is required'),
            ('a' * 129, 'algorithm_version can be up to 128 characters long'),
            ('-invalid', 'algorithm_version must start with a letter'),
            ('.invalid', 'algorithm_version must start with a letter'),
            ('тест', 'algorithm_version must contain only valid ASCII characters')
        ]
        
        for version, expected_error in invalid_cases:
            with self.subTest(version=version):
                with self.assertRaises(ValueError) as cm:
                    _validate_algorithm_version(version)
                self.assertIn(expected_error.split()[0], str(cm.exception))

    @patch('api.endpoints.build._trigger_build_pipeline')
    def test_create_build_with_algorithm_container_url(self, mock_trigger):
        """Test build creation with algorithm_container_url"""
        mock_pipeline = MagicMock()
        mock_pipeline.id = 12345
        mock_pipeline.web_url = 'https://gitlab.com/pipeline/12345'
        mock_trigger.return_value = mock_pipeline
        
        payload = {
            'code_repository': 'https://gitlab.com/test/repo.git',
            'algorithm_name': 'test-algorithm',
            'algorithm_version': 'v1.0',
            'algorithm_container_url': 'docker.io/myorg/myalgo:v1.0'
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

    @patch('api.endpoints.build._trigger_build_pipeline')
    def test_create_build_both_container_urls(self, mock_trigger):
        """Test build creation with both algorithm_container_url and base_container_url (should fail)"""
        mock_pipeline = MagicMock()
        mock_trigger.return_value = mock_pipeline
        
        payload = {
            'code_repository': 'https://gitlab.com/test/repo.git',
            'algorithm_name': 'test-algorithm',
            'algorithm_version': 'v1.0',
            'algorithm_container_url': 'docker.io/myorg/myalgo:v1.0',
            'base_container_url': 'ubuntu:20.04'
        }
        
        response = self._make_authenticated_request(
            'POST',
            '/api/build',
            data=json.dumps(payload)
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('mutually exclusive', data['detail'])

    @patch('api.endpoints.build._trigger_build_pipeline')
    def test_create_build_no_container_urls(self, mock_trigger):
        """Test build creation with neither container URL (should fail)"""
        mock_pipeline = MagicMock()
        mock_trigger.return_value = mock_pipeline
        
        payload = {
            'code_repository': 'https://gitlab.com/test/repo.git',
            'algorithm_name': 'test-algorithm',
            'algorithm_version': 'v1.0'
        }
        
        response = self._make_authenticated_request(
            'POST',
            '/api/build',
            data=json.dumps(payload)
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('algorithm_container_url or base_container_url is required', data['detail'])

    # TODO: Enable these tests once deployment_link and deployment_error columns are added to the database schema
    # def test_get_builds_with_deployment_info(self):
    #     """Test builds list includes deployment information"""
    #     user_id = self._create_test_user()
    #     
    #     with app.app_context():
    #         build_id = str(uuid.uuid4())
    #         build = Build(
    #             build_id=build_id,
    #             requester=user_id,
    #             repository_url='https://gitlab.com/test/repo.git',
    #             branch_ref='main',
    #             status='successful',
    #             deployment_link='https://api.example.com/ogc/deploymentJobs/123',
    #             deployment_error=None
    #         )
    #         db.session.add(build)
    #         db.session.commit()
    #     
    #     response = self._make_authenticated_request('GET', '/api/build', member_id=user_id)
    #     
    #     self.assertEqual(response.status_code, 200)
    #     data = json.loads(response.data)
    #     self.assertEqual(len(data['builds']), 1)
    #     
    #     build_data = data['builds'][0]
    #     self.assertIn('deploymentLink', build_data)
    #     self.assertEqual(build_data['deploymentLink']['href'], 'https://api.example.com/ogc/deploymentJobs/123')
    #     self.assertNotIn('deploymentError', build_data)

    # def test_get_builds_with_deployment_error(self):
    #     """Test builds list includes deployment error"""
    #     user_id = self._create_test_user()
    #     
    #     with app.app_context():
    #         build_id = str(uuid.uuid4())
    #         build = Build(
    #             build_id=build_id,
    #             requester=user_id,
    #             repository_url='https://gitlab.com/test/repo.git',
    #             branch_ref='main',
    #             status='successful',
    #             deployment_link=None,
    #             deployment_error='Failed to deploy OGC process: timeout'
    #         )
    #         db.session.add(build)
    #         db.session.commit()
    #     
    #     response = self._make_authenticated_request('GET', '/api/build', member_id=user_id)
    #     
    #     self.assertEqual(response.status_code, 200)
    #     data = json.loads(response.data)
    #     self.assertEqual(len(data['builds']), 1)
    #     
    #     build_data = data['builds'][0]
    #     self.assertNotIn('deploymentLink', build_data)
    #     self.assertIn('deploymentError', build_data)
    #     self.assertEqual(build_data['deploymentError'], 'Failed to deploy OGC process: timeout')

    # TODO: Enable this test once deployment functionality is working with the database schema
    # @patch('api.endpoints.build.requests.post')
    # def test_webhook_with_ogc_deployment_success(self, mock_post):
    #     """Test webhook handling with successful OGC deployment"""
    #     # Setup mock response for OGC deployment
    #     mock_response = MagicMock()
    #     mock_response.status_code = 201
    #     mock_response.json.return_value = {
    #         'links': [
    #             {'rel': 'monitor', 'href': 'https://api.example.com/ogc/deploymentJobs/123'}
    #         ]
    #     }
    #     mock_post.return_value = mock_response
    #     
    #     user_id = self._create_test_user()
    #     
    #     with app.app_context():
    #         # Create a build with successful status
    #         build_id = str(uuid.uuid4())
    #         build = Build(
    #             build_id=build_id,
    #             requester=user_id,
    #             repository_url='https://gitlab.com/test/repo.git',
    #             branch_ref='main',
    #             status='running',
    #             pipeline_id=12345
    #         )
    #         db.session.add(build)
    #         db.session.commit()
    #     
    #     # Webhook payload simulating successful pipeline
    #     webhook_payload = {
    #         'object_kind': 'pipeline',
    #         'object_attributes': {
    #             'id': 12345,
    #             'status': 'success',
    #             'variables': [
    #                 {
    #                     'key': 'OGC_PROCESS_FILE_PUBLISH_URL',
    #                     'value': 'https://gitlab.com/api/v4/projects/456/repository/files/test-algo%2Fv1.0%2Fprocess.cwl'
    #                 }
    #             ]
    #         }
    #     }
    #     
    #     with patch('api.auth.security.authenticate_third_party'):
    #         response = self.client.post(
    #             '/api/build/webhook',
    #             data=json.dumps(webhook_payload),
    #             content_type='application/json',
    #             headers={'Authorization': 'Bearer test-token'}
    #         )
    #     
    #     self.assertEqual(response.status_code, 200)
    #     data = json.loads(response.data)
    #     self.assertEqual(data['status'], 'successful')
    #     
    #     # Verify OGC deployment was attempted
    #     mock_post.assert_called_once()

    # TODO: Add webhook tests once authentication mocking is resolved
    # The webhook endpoint requires third-party authentication which is complex to mock in tests
    # These tests should be added once we can properly mock the GitLab webhook authentication
    # 
    # def test_webhook_non_pipeline_event(self):
    #     """Test webhook ignores non-pipeline events"""
    # 
    # def test_webhook_missing_pipeline_id(self):
    #     """Test webhook with missing pipeline ID"""
    # 
    # def test_webhook_with_ogc_deployment_success(self):
    #     """Test webhook handling with successful OGC deployment"""

    @patch('api.endpoints.build._update_build_status')
    def test_get_build_access_control(self, mock_update_build_status):
        """Test build access control - user2 cannot access user1's build"""
        # Mock _update_build_status to return a simple response without GitLab calls
        mock_update_build_status.return_value = ({
            "build_id": "test-build-id",
            "status": "running",
            "links": {
                "href": "/build/test-build-id",
                "rel": "self",
                "type": "application/json",
                "hreflang": "en",
                "title": "Build Status"
            }
        }, 200)
        
        # Create user1 
        user1_id = self._create_test_user('user1')
        
        # Create user2 with different email
        with app.app_context():
            role = db.session.query(Role).filter_by(role_name=Role.ROLE_NAME_MEMBER).first()
            user2 = Member(
                username='user2',
                first_name='Test',
                last_name='User2',
                email='user2@example.com',
                role_id=role.id
            )
            db.session.add(user2)
            db.session.commit()
            user2_id = user2.id
        
        with app.app_context():
            # Create a build for user1
            build_id = str(uuid.uuid4())
            build = Build(
                build_id=build_id,
                requester=user1_id,
                repository_url='https://gitlab.com/test/repo.git',
                branch_ref='main',
                status='running'
            )
            db.session.add(build)
            db.session.commit()
        
        # User1 should be able to access their own build
        response = self._make_authenticated_request('GET', f'/api/build/{build_id}', member_id=user1_id)
        self.assertEqual(response.status_code, 200)
        
        # User2 should be denied access to user1's build (should return 403)
        response = self._make_authenticated_request('GET', f'/api/build/{build_id}', member_id=user2_id)
        self.assertEqual(response.status_code, 403)

    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    @patch('api.utils.ogc_process_util.trigger_gitlab_pipeline')
    @patch('api.utils.ogc_process_util.create_and_commit_deployment')
    def test_create_process_deployment_success(self, mock_create_deployment, mock_trigger_pipeline, mock_get_cwl):
        """Test successful OGC process deployment using shared utility function"""
        
        # Create test user
        user_id = self._create_test_user()
        
        # Mock CWL metadata
        mock_metadata = MagicMock()
        mock_metadata.id = 'test-process'
        mock_metadata.version = 'v1.0'
        mock_metadata.title = 'Test Process'
        mock_metadata.description = 'Test Description'
        mock_metadata.keywords = 'test,process'
        mock_get_cwl.return_value = mock_metadata
        
        # Mock GitLab pipeline
        mock_pipeline = MagicMock()
        mock_pipeline.id = 12345
        mock_pipeline.web_url = 'https://gitlab.com/pipeline/12345'
        mock_trigger_pipeline.return_value = (mock_pipeline, 'test-process-hysds')
        
        # Mock deployment creation
        mock_deployment = MagicMock()
        mock_deployment.job_id = 999
        mock_deployment.status = 'accepted'
        mock_deployment.created = datetime.now()
        mock_create_deployment.return_value = mock_deployment
        
        # Mock the re-query for deployment
        with patch('api.utils.ogc_process_util.db.session.query') as mock_query:
            mock_query.return_value.filter_by.return_value.first.return_value = mock_deployment
            
            with app.app_context():
                response_body, status_code = create_process_deployment(
                    cwl_link='https://example.com/test-process.cwl',
                    user_id=user_id,
                    ignore_existing=True
                )
        
        # Assertions
        self.assertEqual(status_code, 202)
        self.assertIn('jobID', response_body)
        self.assertEqual(response_body['jobID'], 999)
        self.assertIn('status', response_body)
        self.assertEqual(response_body['status'], 'accepted')
        self.assertIn('links', response_body)
        self.assertIn('title', response_body)
        self.assertEqual(response_body['title'], 'Test Process')
        
        # Verify function calls
        mock_get_cwl.assert_called_once_with('https://example.com/test-process.cwl')
        mock_trigger_pipeline.assert_called_once_with('https://example.com/test-process.cwl', 'v1.0', mock_metadata.id, mock_any)

    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    def test_create_process_deployment_invalid_cwl(self, mock_get_cwl):
        """Test OGC process deployment with invalid CWL link"""
        
        # Create test user
        user_id = self._create_test_user()
        
        # Mock CWL metadata to raise ValueError
        mock_get_cwl.side_effect = ValueError("Invalid CWL file")
        
        with app.app_context():
            with self.assertRaises(ValueError) as cm:
                create_process_deployment(
                    cwl_link='https://example.com/invalid.cwl',
                    user_id=user_id
                )
            
            self.assertIn("Invalid CWL file", str(cm.exception))

    def test_create_process_deployment_missing_cwl_link(self):
        """Test OGC process deployment with missing CWL link"""
        
        # Create test user
        user_id = self._create_test_user()
        
        with app.app_context():
            with self.assertRaises(ValueError) as cm:
                create_process_deployment(
                    cwl_link=None,
                    user_id=user_id
                )
            
            self.assertEqual(str(cm.exception), "CWL link is required")

    def test_create_process_deployment_invalid_user(self):
        """Test OGC process deployment with invalid user ID"""
        
        with app.app_context():
            with self.assertRaises(ValueError) as cm:
                create_process_deployment(
                    cwl_link='https://example.com/test.cwl',
                    user_id=99999  # Non-existent user ID
                )
            
            self.assertIn("User with ID 99999 not found", str(cm.exception))


if __name__ == '__main__':
    unittest.main()