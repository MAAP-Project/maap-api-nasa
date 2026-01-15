import unittest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.role import Role
from api.models.process import Process
from api.models.deployment import Deployment


class TestOGCEndpoints(unittest.TestCase):
    """
    Comprehensive test suite for OGC compliant endpoints
    Tests process management, deployment monitoring, and job execution
    """

    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
            # Clear any existing test data
            db.session.query(Process).delete()
            db.session.query(Deployment).delete()
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
            db.session.query(Process).delete()
            db.session.query(Deployment).delete()
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

    def _create_test_member(self, username="testuser", role_id=Role.ROLE_MEMBER):
        """Create a test member with optional custom username and role"""
        member = Member(
            username=username,
            first_name="Test",
            last_name="User", 
            email=f"{username}@example.com",
            organization="NASA",
            role_id=role_id
        )
        db.session.add(member)
        db.session.commit()
        db.session.refresh(member)  # Ensure object is attached to current session
        
        return member

    def _create_test_process(self, member, process_id="test-process", version="1.0", author="test-author"):
        """Create a test deployed process"""
        process = Process(
            id=process_id,
            version=version,
            process_id=1,  # auto-incremented field
            title="Test Process",
            description="A test process for OGC testing",
            keywords="test,ogc",
            cwl_link="https://example.com/test.cwl",
            deployer=member.username,
            author=author,
            status="deployed",
            last_modified_time=datetime.now()
        )
        db.session.add(process)
        db.session.commit()
        db.session.refresh(process)  # Ensure object is attached to current session

        return process

    def _setup_auth_mock(self, member):
        """Create and return authentication mock session"""
        mock_session = MagicMock()
        mock_session.member = member
        mock_session.member.role_id = 2  # ROLE_MEMBER
        return mock_session

    def _create_mock_job_response(self, job_id='job-12345', status='job-completed', job_type='job-test-process', member_id=None, process_version='1.0'):
        """Create a standard mock job response for HySDS queries"""
        return {
            'jobs': [
                {
                    job_id: {
                        'status': status,
                        'type': f'{job_type}_{member_id}:{process_version}' if member_id else job_type,
                        'job_id': job_id
                    }
                }
            ]
        }

    def _assert_response_success(self, response, expected_status=200):
        """Assert response has expected status and returns JSON data"""
        self.assertEqual(response.status_code, expected_status)
        return response.get_json()

    def _make_authenticated_request(self, method, url, data=None, member=None):
        """Helper to make authenticated requests"""
        if member is None:
            member = self._create_test_member()

        with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
            mock_validate_proxy.return_value = self._setup_auth_mock(member)

            headers = {'proxy-ticket': 'test-ticket'}
            if data is not None:
                headers['Content-Type'] = 'application/json'

            if method.upper() == 'GET':
                return self.client.get(url, headers=headers)
            elif method.upper() == 'POST':
                return self.client.post(url, data=json.dumps(data) if data is not None else None, headers=headers)
            elif method.upper() == 'PUT':
                return self.client.put(url, data=json.dumps(data) if data is not None else None, headers=headers)
            elif method.upper() == 'DELETE':
                return self.client.delete(url, headers=headers)

    def test_processes_get_returns_deployed_processes(self):
        """Test: GET /ogc/processes returns list of deployed processes"""
        with app.app_context():
            # Given a deployed process
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            # When requesting all processes
            response = self.client.get('/api/ogc/processes')
            
            # Then deployed processes should be returned
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('processes', data)
            self.assertEqual(len(data['processes']), 1)
            self.assertEqual(data['processes'][0]['id'], 'test-process')
            self.assertEqual(data['processes'][0]['title'], 'Test Process')
            self.assertEqual(data['processes'][0]['author'], 'test-author')

    def test_processes_get_returns_empty_when_no_deployed_processes(self):
        """Test: GET /ogc/processes returns empty list when no deployed processes"""
        # When requesting all processes with none deployed
        response = self.client.get('/api/ogc/processes')
        
        # Then empty process list should be returned
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('processes', data)
        self.assertEqual(len(data['processes']), 0)

    @patch('api.auth.security.get_authorized_user')
    def test_processes_post_requires_authentication(self, mock_get_user):
        """Test: POST /ogc/processes requires authentication"""
        with app.app_context():
            # Given no authenticated user
            mock_get_user.return_value = None
            
            # When attempting to post a process without authentication
            process_data = {
                "executionUnit": {
                    "href": "https://example.com/test.cwl"
                }
            }
            
            response = self.client.post('/api/ogc/processes',
                                      data=json.dumps(process_data),
                                      content_type='application/json')
            
            # Then authentication should be required
            self.assertEqual(response.status_code, 401)

    @patch('api.utils.ogc_process_util.trigger_gitlab_pipeline')
    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    @patch('api.auth.security.get_authorized_user')
    def test_processes_post_creates_new_process_deployment(self, mock_get_user, mock_metadata, mock_pipeline):
        """Test: POST /ogc/processes creates new process deployment"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user and valid CWL metadata
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)

                # Mock CWL metadata
                mock_metadata.return_value = MagicMock(
                    id="new-process",
                    version="1.0",
                    title="New Process",
                    description="A new process",
                    author="Author",
                    keywords="test,new",
                    cwl_link="https://example.com/new.cwl",
                    github_url="https://github.com/test/repo",
                    git_commit_hash="abc123",
                    ram_min=1024,
                    cores_min=1,
                    base_command="python"
                )

                # Mock GitLab pipeline
                mock_pipeline_obj = MagicMock()
                mock_pipeline_obj.id = 12345
                mock_pipeline_obj.web_url = "https://gitlab.com/pipeline/12345"
                mock_pipeline.return_value = mock_pipeline_obj

                # When posting a new process
                process_data = {
                    "executionUnit": {
                        "href": "https://example.com/new.cwl"
                    }
                }

                response = self.client.post('/api/ogc/processes',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then deployment should be created with accepted status
                self.assertEqual(response.status_code, 202)
                data = response.get_json()
                self.assertEqual(data['id'], 'new-process')
                self.assertEqual(data['version'], '1.0')
                self.assertIn('links', data)
                self.assertIn('processPipelineLink', data)

    @patch('api.auth.security.get_authorized_user')
    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    def test_processes_post_returns_409_for_duplicate_process(self, mock_metadata, mock_get_user):
        """Test: POST /ogc/processes returns 409 for duplicate process"""
        with app.app_context():
            # Given an authenticated user and existing process
            member = self._create_test_member()
            mock_get_user.return_value = member
            existing_process = self._create_test_process(member)
            
            mock_metadata.return_value = MagicMock()
            mock_metadata.return_value.id = "test-process"
            mock_metadata.return_value.version = "1.0"
            
            # When posting a process with same id and version
            process_data = {
                "executionUnit": {
                    "href": "https://example.com/test.cwl"
                }
            }
            
            response = self._make_authenticated_request('POST', '/api/ogc/processes', process_data, member)
            
            # Then conflict should be returned
            self.assertEqual(response.status_code, 409)
            data = response.get_json()
            self.assertIn('Duplicate process', data['detail'])
            self.assertIn('additionalProperties', data)
            self.assertIn('processID', data['additionalProperties'])

    def test_processes_post_returns_400_for_missing_execution_unit(self):
        """Test: POST /ogc/processes returns 400 for missing executionUnit"""
        with app.app_context():
            member = self._create_test_member()

            # When posting without executionUnit
            process_data = {}

            response = self._make_authenticated_request('POST', '/api/ogc/processes', process_data, member)

            # Then bad request should be returned
            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertIn('executionUnit', data['detail'])

    @patch('api.utils.ogc_process_util.trigger_gitlab_pipeline_with_cwl_text')
    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    @patch('api.auth.security.get_authorized_user')
    def test_processes_post_with_cwl_raw_text_creates_deployment(self, mock_get_user, mock_metadata, mock_pipeline):
        """Test: POST /ogc/processes with cwlRawText creates new process deployment"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user and valid CWL raw text
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)

                # Mock CWL metadata
                mock_metadata.return_value = MagicMock(
                    id="raw-text-process",
                    version="1.0",
                    title="Raw Text Process",
                    description="A process from raw CWL text",
                    author="Author",
                    keywords="test,raw",
                    cwl_link=None,
                    github_url="https://github.com/test/repo",
                    git_commit_hash="abc123",
                    ram_min=2048,
                    cores_min=2,
                    base_command="python"
                )

                # Mock GitLab pipeline
                mock_pipeline_obj = MagicMock()
                mock_pipeline_obj.id = 54321
                mock_pipeline_obj.web_url = "https://gitlab.com/pipeline/54321"
                mock_pipeline.return_value = mock_pipeline_obj

                # Sample CWL raw text
                cwl_raw_text = """
cwlVersion: v1.2
$graph:
  - class: Workflow
    id: raw-text-process
    label: Raw Text Process
    doc: A process from raw CWL text
    s:version: "1.0"
    s:author:
      s:name: Author
    s:codeRepository: https://github.com/test/repo
    s:commitHash: abc123
    s:keywords: test,raw
    inputs: []
    outputs: []
    steps: []
"""

                # When posting a process with cwlRawText
                process_data = {
                    "cwlRawText": cwl_raw_text
                }

                response = self.client.post('/api/ogc/processes',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then deployment should be created
                self.assertEqual(response.status_code, 202)
                data = response.get_json()
                self.assertEqual(data['id'], 'raw-text-process')
                self.assertEqual(data['version'], '1.0')
                self.assertIn('links', data)
                self.assertIn('processPipelineLink', data)

                # Verify get_cwl_metadata was called with raw text
                mock_metadata.assert_called_once_with(None, cwl_raw_text)
                # Verify trigger_gitlab_pipeline_with_cwl_text was called
                mock_pipeline.assert_called_once()

    @patch('api.auth.security.get_authorized_user')
    def test_processes_post_with_both_execution_unit_and_raw_text_returns_400(self, mock_get_user):
        """Test: POST /ogc/processes with both executionUnit and cwlRawText returns 400"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)

                # When posting with both executionUnit and cwlRawText
                process_data = {
                    "executionUnit": {
                        "href": "https://example.com/test.cwl"
                    },
                    "cwlRawText": "cwlVersion: v1.2\n..."
                }

                response = self.client.post('/api/ogc/processes',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then bad request should be returned
                self.assertEqual(response.status_code, 400)
                data = response.get_json()
                self.assertIn('Cannot pass a request body with a executionUnit and cwlRawText', data['detail'])

    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    @patch('api.auth.security.get_authorized_user')
    def test_processes_post_with_cwl_raw_text_invalid_returns_400(self, mock_get_user, mock_metadata):
        """Test: POST /ogc/processes with invalid cwlRawText returns 400"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user and invalid CWL
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)

                # Mock get_cwl_metadata to raise ValueError
                mock_metadata.side_effect = ValueError("CWL file is not in the right format or is invalid.")

                # When posting with invalid CWL raw text
                process_data = {
                    "cwlRawText": "invalid cwl content"
                }

                response = self.client.post('/api/ogc/processes',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then bad request should be returned
                self.assertEqual(response.status_code, 400)
                data = response.get_json()
                self.assertIn('CWL file is not in the right format', data['detail'])

    @patch('api.utils.ogc_process_util.create_and_commit_deployment')
    @patch('api.utils.ogc_process_util.trigger_gitlab_pipeline_with_cwl_text')
    @patch('api.utils.ogc_process_util.get_cwl_metadata')
    @patch('api.auth.security.get_authorized_user')
    def test_process_put_with_cwl_raw_text_updates_process(self, mock_get_user, mock_metadata, mock_pipeline, mock_create_deployment):
        """Test: PUT /ogc/processes/{process_id} with cwlRawText updates process"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user and existing process
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)
                process = self._create_test_process(member)

                # Mock CWL metadata with same id/version
                mock_metadata.return_value = MagicMock(
                    id="test-process",
                    version="1.0",
                    title="Updated Process",
                    description="Updated description",
                    author="Author",
                    keywords="test,updated",
                    cwl_link=None,
                    github_url="https://github.com/test/repo",
                    git_commit_hash="def456",
                    ram_min=4096,
                    cores_min=4,
                    base_command="python"
                )

                # Mock GitLab pipeline
                mock_pipeline_obj = MagicMock()
                mock_pipeline_obj.id = 99999
                mock_pipeline_obj.web_url = "https://gitlab.com/pipeline/99999"
                mock_pipeline.return_value = mock_pipeline_obj

                # Mock deployment creation to actually create in DB
                from api.models.deployment import Deployment as Deployment_db
                def create_real_deployment(metadata, pipeline, user, existing_process=None):
                    deployment = Deployment_db(
                        created=datetime.now(),
                        execution_venue='test-venue',
                        status='accepted',
                        cwl_link=metadata.cwl_link,
                        title=metadata.title,
                        description=metadata.description,
                        keywords=metadata.keywords,
                        deployer=user.username,
                        author=metadata.author,
                        pipeline_id=pipeline.id,
                        github_url=metadata.github_url,
                        git_commit_hash=metadata.git_commit_hash,
                        id=metadata.id if not existing_process else existing_process.id,
                        version=metadata.version if not existing_process else existing_process.version,
                        ram_min=metadata.ram_min,
                        cores_min=metadata.cores_min,
                        base_command=metadata.base_command
                    )
                    db.session.add(deployment)
                    db.session.commit()
                    return deployment

                mock_create_deployment.side_effect = create_real_deployment

                # Sample CWL raw text
                cwl_raw_text = """
cwlVersion: v1.2
$graph:
  - class: Workflow
    id: test-process
    label: Updated Process
    doc: Updated description
    s:version: "1.0"
    inputs: []
    outputs: []
    steps: []
"""

                # When updating process with cwlRawText
                process_data = {
                    "cwlRawText": cwl_raw_text
                }

                response = self.client.put(f'/api/ogc/processes/{process.process_id}',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then update should be accepted
                self.assertEqual(response.status_code, 202)
                data = response.get_json()
                self.assertEqual(data['id'], 'test-process')
                self.assertEqual(data['version'], '1.0')
                self.assertIn('links', data)
                self.assertIn('processPipelineLink', data)

                # Verify pipeline trigger was called
                mock_pipeline.assert_called_once()

    @patch('api.auth.security.get_authorized_user')
    def test_process_put_with_both_execution_unit_and_raw_text_returns_400(self, mock_get_user):
        """Test: PUT /ogc/processes/{process_id} with both executionUnit and cwlRawText returns 400"""
        with app.app_context():
            with patch('api.auth.security.validate_proxy') as mock_validate_proxy:
                # Given an authenticated user and existing process
                member = self._create_test_member()
                mock_get_user.return_value = member
                mock_validate_proxy.return_value = self._setup_auth_mock(member)
                process = self._create_test_process(member)

                # When updating with both executionUnit and cwlRawText
                process_data = {
                    "executionUnit": {
                        "href": "https://example.com/updated.cwl"
                    },
                    "cwlRawText": "cwlVersion: v1.2\n..."
                }

                response = self.client.put(f'/api/ogc/processes/{process.process_id}',
                                          data=json.dumps(process_data),
                                          content_type='application/json',
                                          headers={'proxy-ticket': 'test-ticket'})

                # Then bad request should be returned
                self.assertEqual(response.status_code, 400)
                data = response.get_json()
                self.assertIn('Cannot pass a request body with a executionUnit and cwlRawText', data['detail'])

    def test_process_describe_returns_process_details(self):
        """Test: GET /ogc/processes/{process_id} returns process details"""
        with app.app_context():
            # Given a deployed process and mock HySDS response
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            with patch('api.utils.hysds_util.get_hysds_io') as mock_hysds:
                mock_hysds.return_value = {
                    'success': True,
                    'result': {
                        'params': [
                            {
                                'name': 'input_file',
                                'description': 'Input file path',
                                'type': 'string',
                                'placeholder': '/path/to/file',
                                'default': None
                            }
                        ]
                    }
                }
                
                # When requesting process details
                response = self.client.get(f'/api/ogc/processes/{process.process_id}')
                
                # Then process details should be returned
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data['id'], 'test-process')
                self.assertEqual(data['processID'], str(process.process_id))
                self.assertEqual(data['title'], 'Test Process')
                self.assertEqual(data['author'], 'test-author')
                self.assertIn('inputs', data)
                self.assertIn('input_file', data['inputs'])

    def test_process_describe_returns_404_for_nonexistent_process(self):
        """Test: GET /ogc/processes/{process_id} returns 404 for nonexistent process"""
        # When requesting details for non-existent process
        response = self.client.get('/api/ogc/processes/999999')
        
        # Then not found should be returned
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('No process with that process ID found', data['detail'])

    @patch('api.auth.security.get_authorized_user')
    def test_process_put_requires_ownership(self, mock_get_user):
        """Test: PUT /ogc/processes/{process_id} requires process ownership"""
        with app.app_context():
            # Given a process owned by one user and different authenticated user
            owner = self._create_test_member("owner")
            different_user = self._create_test_member("different")
            process = self._create_test_process(owner)
            mock_get_user.return_value = different_user
            
            # When attempting to update process as different user
            process_data = {
                "executionUnit": {
                    "href": "https://example.com/updated.cwl"
                }
            }
            
            response = self._make_authenticated_request('PUT', f'/api/ogc/processes/{process.process_id}', process_data, different_user)
            
            # Then forbidden should be returned
            self.assertEqual(response.status_code, 403)
            data = response.get_json()
            if 'detail' in data:
                self.assertIn('You can only modify processes that you posted originally', data['detail'])

    @patch('api.auth.security.get_authorized_user')
    def test_process_delete_requires_ownership(self, mock_get_user):
        """Test: DELETE /ogc/processes/{process_id} requires process ownership"""
        with app.app_context():
            # Given a process owned by one user and different authenticated user
            owner = self._create_test_member("owner")
            different_user = self._create_test_member("different")
            process = self._create_test_process(owner)
            mock_get_user.return_value = different_user
            
            # When attempting to delete process as different user
            response = self._make_authenticated_request('DELETE', f'/api/ogc/processes/{process.process_id}', None, different_user)
            
            # Then forbidden should be returned
            self.assertEqual(response.status_code, 403)
            data = response.get_json()
            if 'detail' in data:
                self.assertIn('You can only modify processes that you posted originally', data['detail'])

    @patch('api.auth.security.get_authorized_user')
    def test_process_delete_sets_status_to_undeployed(self, mock_get_user):
        """Test: DELETE /ogc/processes/{process_id} sets status to undeployed"""
        with app.app_context():
            # Given a process owned by authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)
            mock_get_user.return_value = member
            
            # When deleting the process
            response = self._make_authenticated_request('DELETE', f'/api/ogc/processes/{process.process_id}', None, member)
            
            # Then process should be marked as undeployed
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('Deleted process', data['detail'])
            
            # And process status should be updated
            updated_process = db.session.query(Process).filter_by(process_id=process.process_id).first()
            self.assertEqual(updated_process.status, 'undeployed')

    def test_process_package_returns_execution_unit(self):
        """Test: GET /ogc/processes/{process_id}/package returns execution unit"""
        with app.app_context():
            # Given a deployed process
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            # When requesting process package
            response = self.client.get(f'/api/ogc/processes/{process.process_id}/package')
            
            # Then execution unit should be returned
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('processDescription', data)
            self.assertIn('executionUnit', data)
            self.assertEqual(data['executionUnit']['href'], 'https://example.com/test.cwl')

    @patch('api.utils.hysds_util.get_hysds_io')
    @patch('api.utils.hysds_util.validate_job_submit')
    @patch('api.utils.hysds_util.mozart_submit_job')
    @patch('api.utils.job_queue.validate_or_get_queue')
    def test_process_execution_submits_job(self, mock_queue, mock_submit, mock_validate, mock_hysds_io):
        """Test: POST /ogc/processes/{process_id}/execution submits job"""
        with app.app_context():
            # Given a deployed process and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            mock_hysds_io.return_value = {
                'result': {
                    'soft_time_limit': 3600
                }
            }
            mock_validate.return_value = {'input_file': '/test/path'}
            mock_submit.return_value = {'result': 'job-12345'}
            
            mock_queue_obj = MagicMock()
            mock_queue_obj.queue_name = 'test-queue'
            mock_queue_obj.time_limit_minutes = None
            mock_queue.return_value = mock_queue_obj
            
            # When submitting job execution
            job_data = {
                "inputs": {"input_file": "/test/path"},
                "queue": "test-queue",
                "tag": "test-execution"
            }
            
            response = self._make_authenticated_request('POST', f'/api/ogc/processes/{process.process_id}/execution', job_data, member)
            
            # Then job should be submitted and tracked
            self.assertEqual(response.status_code, 202)
            data = response.get_json()
            self.assertEqual(data['jobID'], 'job-12345')
            self.assertEqual(data['processID'], process.process_id)
            self.assertEqual(data['status'], 'accepted')
            self.assertIn('links', data)

    def test_process_execution_requires_queue_parameter(self):
        """Test: POST /ogc/processes/{process_id}/execution requires queue parameter"""
        with app.app_context():
            # Given a deployed process and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            # When submitting job without queue
            job_data = {
                "inputs": {"input_file": "/test/path"}
            }
            
            response = self._make_authenticated_request('POST', f'/api/ogc/processes/{process.process_id}/execution', job_data, member)
            
            # Then bad request should be returned
            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertIn('Need to specify a queue', data['detail'])

    @patch('api.auth.security.get_authorized_user')
    def test_deployment_status_can_be_queried(self, mock_get_user):
        """Test: GET /ogc/deploymentJobs/{deployment_id} returns deployment status"""
        with app.app_context():
            # Given a deployment record and authenticated user
            member = self._create_test_member()
            mock_get_user.return_value = member
            
            deployment = Deployment(
                id="test-process",
                version="1.0",
                job_id=1,  # auto-incremented field
                created=datetime.now(),
                execution_venue="test",
                status="running",
                cwl_link="https://example.com/test.cwl",
                title="Test Process",
                description="Test deployment",
                deployer=member.username, 
                author="test-author",
                pipeline_id=12345
            )
            db.session.add(deployment)
            db.session.commit()
            
            with patch('api.endpoints.ogc.update_status_post_process_if_applicable') as mock_update:
                mock_update.return_value = (
                    {
                        "created": deployment.created,
                        "status": "running",
                        "pipeline": {
                            "executionVenue": "test",
                            "pipelineId": 12345
                        }
                    },
                    200
                )
                
                # When querying deployment status
                response = self._make_authenticated_request('GET', f'/api/ogc/deploymentJobs/{deployment.job_id}', None, member)
                
                # Then deployment status should be returned
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data['status'], 'running')
                self.assertIn('pipeline', data)

    def test_deployment_webhook_updates_status(self):
        """Test: POST /ogc/deploymentJobs updates deployment status via webhook"""
        with app.app_context():
            # Given a deployment record and third-party authentication
            member = self._create_test_member()
            deployment = Deployment(
                id="test-process",
                version="1.0",
                job_id=1,
                created=datetime.now(),
                execution_venue="test",
                status="running",
                cwl_link="https://example.com/test.cwl",
                title="Test Process",
                description="Test deployment",
                deployer=member.username,
                author="test-author",
                pipeline_id=12345
            )
            db.session.add(deployment)
            db.session.commit()
            
            # When webhook updates deployment status
            webhook_data = {
                "object_attributes": {
                    "id": 12345,
                    "status": "success"
                }
            }
            
            # Mock the validation function to return True
            with patch('api.auth.cas_auth.validate_third_party', return_value=True):
                with patch('api.settings.THIRD_PARTY_SECRET_TOKEN_GITLAB', 'test-token'):
                    with patch('api.endpoints.ogc.update_status_post_process_if_applicable') as mock_update:
                        mock_update.return_value = (
                            {
                                "created": deployment.created,
                                "status": "successful",
                                "pipeline": {
                                    "executionVenue": "test",
                                    "pipelineId": 12345
                                }
                            },
                            200
                        )
                        
                        response = self.client.post('/api/ogc/deploymentJobs',
                                                  data=json.dumps(webhook_data),
                                                  content_type='application/json',
                                                  headers={'X-Gitlab-Token': 'test-token'})
                        
                        # Then deployment status should be updated
                        self.assertEqual(response.status_code, 200)

    def test_job_status_can_be_queried(self):
        """Test: GET /ogc/jobs/{job_id} returns minimal job status by default"""
        with app.app_context():
            # Given a process job and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)

            with patch('api.utils.hysds_util.mozart_job_status') as mock_status:
                with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
                    with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                        mock_status.return_value = {"status": "job-running"}
                        mock_get_job.return_value = {
                            "status": "job-running",
                            "type": f"job-test-process_{member.id}:1.0",
                            "job": {
                                "job_info": {
                                    "time_queued": "2023-01-01T12:00:00Z",
                                    "time_start": "2023-01-01T12:01:00Z",
                                    "time_end": "2023-01-01T13:00:00Z"
                                }
                            }
                        }
                        mock_translate.return_value = "running"

                        # When querying job status without fields parameter
                        response = self._make_authenticated_request('GET', '/api/ogc/jobs/job-12345', None, member)

                        # Then minimal job info should be returned (jobID, processID, type, status only)
                        self.assertEqual(response.status_code, 200)
                        data = response.get_json()
                        self.assertEqual(data['jobID'], 'job-12345')
                        self.assertEqual(data['status'], 'running')
                        self.assertEqual(data['processID'], process.process_id)
                        self.assertEqual(data['type'], None)
                        # Should not include additional fields by default
                        self.assertNotIn('created', data)
                        self.assertNotIn('started', data)
                        self.assertNotIn('finished', data)

    def test_job_results_can_be_retrieved(self):
        """Test: GET /ogc/jobs/{job_id}/results returns job results"""
        with app.app_context():
            # Given a completed job and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)

            with patch('api.utils.hysds_util.mozart_job_status') as mock_status:
                with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
                    mock_status.return_value = {"status": "job-completed"}
                    mock_get_job.return_value = {
                        'job': {
                            'job_info': {
                                'metrics': {
                                    'products_staged': [
                                        {
                                            'id': 'output-product-123',
                                            'urls': ['s3://bucket:80/output/product-123.tif']
                                        }
                                    ]
                                }
                            }
                        },
                        'traceback': None
                    }

                    # When requesting job results
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs/job-12345/results', None, member)

                    # Then job results should be returned
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertIn('additionalProp1', data)

    def test_job_can_be_cancelled(self):
        """Test: DELETE /ogc/jobs/{job_id} cancels running job"""
        with app.app_context():
            # Given a running job and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)
            
            with patch('api.utils.hysds_util.mozart_job_status') as mock_status:
                with patch('api.utils.hysds_util.revoke_mozart_job') as mock_revoke:
                    with patch('api.utils.ogc_translate.status_response') as mock_response:
                        mock_status.return_value = {"status": "job-started"}
                        mock_revoke.return_value = ("purge-123", {"status": "job-completed"})
                        mock_response.return_value = b"Job cancelled successfully"
                        
                        # When cancelling the job
                        response = self._make_authenticated_request('DELETE', '/api/ogc/jobs/job-12345', None, member)
                        
                        # Then job should be cancelled
                        self.assertEqual(response.status_code, 202)
                        data = response.get_json()
                        self.assertEqual(data['jobID'], 'job-12345')
                        self.assertEqual(data['status'], 'dismissed')

    def test_job_metrics_can_be_retrieved(self):
        """Test: GET /ogc/jobs/{job_id}/metrics returns job metrics"""
        with app.app_context():
            # Given a completed job and authenticated user
            member = self._create_test_member()
            process = self._create_test_process(member)

            with patch('api.utils.hysds_util.mozart_job_status') as mock_status:
                with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
                    mock_status.return_value = {"status": "job-completed"}
                    mock_get_job.return_value = {
                        'job': {
                            'job_info': {
                                'metrics': {
                                    'job_dir_size': 2048,
                                    'usage_stats': [{
                                        'cgroups': {
                                            'cpu_stats': {'cpu_usage': {'total_usage': 54321}},
                                            'memory_stats': {
                                                'cache': 1024,
                                                'usage': {'usage': 2048, 'max_usage': 4096},
                                                'stats': {'swap': 0}
                                            },
                                            'blkio_stats': {'io_service_bytes_recursive': [
                                                {'op': 'Read', 'value': 2000},
                                                {'op': 'Write', 'value': 4000},
                                                {'op': 'Sync', 'value': 1000},
                                                {'op': 'Async', 'value': 1000},
                                                {'op': 'Total', 'value': 6000}
                                            ]}
                                        }
                                    }]
                                },
                                'cmd_start': '2023-01-01T12:00:00Z',
                                'cmd_end': '2023-01-01T13:00:00Z',
                                'cmd_duration': 3600,
                                'facts': {
                                    'architecture': 'amd64',
                                    'operatingsystem': 'CentOS',
                                    'memorysize': '16 GB',
                                    'ec2_instance_type': 'c5.large'
                                }
                            }
                        }
                    }

                    # When requesting job metrics
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs/job-12345/metrics', None, member)

                    # Then job metrics should be returned
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertEqual(data['machine_type'], 'c5.large')
                    self.assertEqual(data['architecture'], 'amd64')
                    self.assertEqual(data['directory_size'], 2048)

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_returns_user_jobs(self, mock_get_user):
        """Test: GET /ogc/jobs returns minimal list of user jobs by default"""
        with app.app_context():
            # Given an authenticated user and their jobs
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (self._create_mock_job_response(), 200)
                    mock_translate.return_value = 'successful'

                    # When requesting job list without getJobDetails parameter
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs', None, member)

                    # Then minimal user jobs should be returned (jobID, type, status, job_type only)
                    data = self._assert_response_success(response)
                    self.assertIn('jobs', data)
                    self.assertEqual(len(data['jobs']), 1)
                    self.assertEqual(data['jobs'][0]['jobID'], 'job-12345')
                    self.assertEqual(data['jobs'][0]['status'], 'successful')
                    self.assertEqual(data['jobs'][0]['type'], 'process')
                    # Should not include additional fields by default
                    self.assertNotIn('title', data['jobs'][0])
                    self.assertNotIn('description', data['jobs'][0])
                    self.assertNotIn('keywords', data['jobs'][0])

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_with_fields_parameter(self, mock_get_user):
        """Test: GET /ogc/jobs?fields=... returns requested fields for each job"""
        with app.app_context():
            # Given an authenticated user and their jobs
            member = self._create_test_member()
            mock_get_user.return_value = member
            process = self._create_test_process(member)

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (
                        {
                            'jobs': [
                                {
                                    'job-12345': {
                                        'status': 'job-completed',
                                        'type': f'job-test-process_{member.id}:1.0',
                                        'job_id': 'job-12345',
                                        'job': {
                                            'job_info': {
                                                'time_queued': '2023-01-01T12:00:00Z',
                                                'time_start': '2023-01-01T12:01:00Z',
                                                'time_end': '2023-01-01T13:00:00Z'
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        200
                    )
                    mock_translate.return_value = 'successful'

                    # When requesting job list with fields parameter
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs?fields=title,description,created', None, member)

                    # Then specified fields should be included
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertIn('jobs', data)
                    self.assertEqual(len(data['jobs']), 1)
                    self.assertIn('title', data['jobs'][0])
                    self.assertIn('description', data['jobs'][0])
                    self.assertIn('created', data['jobs'][0])

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_with_get_job_details_parameter(self, mock_get_user):
        """Test: GET /ogc/jobs?getJobDetails=true returns all job details"""
        with app.app_context():
            # Given an authenticated user and their jobs
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (
                        {
                            'jobs': [
                                {
                                    'job-12345': {
                                        'status': 'job-completed',
                                        'type': 'job-test-process',
                                        'job_id': 'job-12345',
                                        'job': {
                                            'job_info': {
                                                'time_queued': '2023-01-01T12:00:00Z'
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        200
                    )
                    mock_translate.return_value = 'successful'

                    # When requesting job list with getJobDetails=true
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs?getJobDetails=true', None, member)

                    # Then all job details should be returned
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertIn('jobs', data)
                    self.assertEqual(len(data['jobs']), 1)
                    # With getJobDetails=true, the full job info should be included
                    self.assertIn('job', data['jobs'][0])
                    self.assertIn('job_info', data['jobs'][0]['job'])

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_filters_by_process_id(self, mock_get_user):
        """Test: GET /ogc/jobs filters by processID parameter"""
        with app.app_context():
            # Given an authenticated user and a deployed process
            member = self._create_test_member()
            mock_get_user.return_value = member
            process = self._create_test_process(member)

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                mock_jobs.return_value = (self._create_mock_job_response(), 200)

                # When requesting jobs with processID filter
                response = self._make_authenticated_request('GET', f'/api/ogc/jobs?processID={process.process_id}', None, member)

                # Then filtered jobs should be returned and correct params passed to HySDS
                # deployer field stores username, but HySDS job_type uses deployer's numeric ID
                self._assert_response_success(response)
                mock_jobs.assert_called_once()
                args, kwargs = mock_jobs.call_args
                params = args[0]  # First argument is params dict
                self.assertIn('job_type', params)
                # Process name format: job-{id}_{deployer_id}:{version}
                self.assertEqual(params['job_type'], f"job-{process.id}_{member.id}:{process.version}")

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_filters_by_status(self, mock_get_user):
        """Test: GET /ogc/jobs filters by status parameter"""
        with app.app_context():
            # Given an authenticated user
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.get_hysds_status_from_ogc') as mock_translate:
                    with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate_hysds:
                        mock_translate.return_value = ('job-completed', None)  # Returns tuple (status, error)
                        mock_translate_hysds.return_value = 'successful'
                        mock_jobs.return_value = (self._create_mock_job_response(), 200)

                        # When requesting jobs with status filter
                        response = self._make_authenticated_request('GET', '/api/ogc/jobs?status=successful', None, member)

                        # Then status should be translated and passed to HySDS
                        self._assert_response_success(response)
                        mock_translate.assert_called_once_with('successful')
                        mock_jobs.assert_called_once()
                        args, kwargs = mock_jobs.call_args
                        params = args[0]
                        self.assertIn('status', params)
                        self.assertEqual(params['status'], 'job-completed')

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_filters_by_duration_range(self, mock_get_user):
        """Test: GET /ogc/jobs filters by minDuration and maxDuration"""
        with app.app_context():
            # Given an authenticated user and jobs with different durations
            member = self._create_test_member()
            mock_get_user.return_value = member
            
            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                mock_jobs.return_value = (
                    {
                        'jobs': [
                            {
                                'job-short': {
                                    'status': 'job-completed',
                                    'job': {
                                        'job_info': {
                                            'time_start': '2023-01-01T12:00:00.000000Z',
                                            'time_end': '2023-01-01T12:01:30.000000Z'  # 90 seconds
                                        }
                                    }
                                }
                            },
                            {
                                'job-long': {
                                    'status': 'job-completed', 
                                    'job': {
                                        'job_info': {
                                            'time_start': '2023-01-01T12:00:00.000000Z',
                                            'time_end': '2023-01-01T13:00:00.000000Z'  # 3600 seconds
                                        }
                                    }
                                }
                            }
                        ]
                    },
                    200
                )
                
                # When requesting jobs with duration filter (2-4 minutes = 120-240 seconds)
                response = self._make_authenticated_request('GET', '/api/ogc/jobs?minDuration=120&maxDuration=240', None, member)
                
                # Then only jobs within duration range should be returned
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertIn('jobs', data)
                # Neither job should match (90s < 120s, 3600s > 240s)
                self.assertEqual(len(data['jobs']), 0)

    @patch('api.auth.security.get_authorized_user') 
    def test_jobs_list_filters_by_datetime_interval(self, mock_get_user):
        """Test: GET /ogc/jobs filters by datetime interval"""
        with app.app_context():
            # Given an authenticated user and jobs at different times
            member = self._create_test_member()
            mock_get_user.return_value = member
            
            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (
                        {
                            'jobs': [
                                {
                                    'job-in-range': {
                                        'status': 'job-completed',
                                        'type': 'job-test-process',
                                        'job': {
                                            'job_info': {
                                                'time_start': '2023-01-01T12:00:00.000000Z',
                                                'time_end': '2023-01-01T13:00:00.000000Z'
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        200
                    )
                    mock_translate.return_value = 'successful'

                    # When requesting jobs with datetime filter
                    datetime_param = '2023-01-01T12:30:00Z/2023-01-01T14:00:00Z'
                    response = self._make_authenticated_request('GET', f'/api/ogc/jobs?datetime={datetime_param}', None, member)

                    # Then datetime filtering should be applied
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertIn('jobs', data)
                    # The job should be filtered based on datetime logic
                    self.assertEqual(len(data['jobs']), 1)

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_applies_limit(self, mock_get_user):
        """Test: GET /ogc/jobs applies limit parameter"""
        with app.app_context():
            # Given an authenticated user and multiple jobs
            member = self._create_test_member()
            mock_get_user.return_value = member
            
            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                mock_jobs.return_value = (
                    {
                        'jobs': [
                            {
                                'job-1': {
                                    'status': 'job-completed',
                                    'type': 'job-test-process',
                                    'job_id': 'job-1'
                                }
                            },
                            {
                                'job-2': {
                                    'status': 'job-completed',
                                    'type': 'job-test-process',
                                    'job_id': 'job-2'
                                }
                            },
                            {
                                'job-3': {
                                    'status': 'job-completed',
                                    'type': 'job-test-process',
                                    'job_id': 'job-3'
                                }
                            }
                        ]
                    },
                    200
                )
                
                # When requesting jobs with limit
                response = self._make_authenticated_request('GET', '/api/ogc/jobs?limit=2', None, member)
                
                # Then only limited number of jobs should be returned
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertIn('jobs', data)
                self.assertEqual(len(data['jobs']), 2)

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_handles_nonexistent_process_id(self, mock_get_user):
        """Test: GET /ogc/jobs returns empty list for nonexistent processID"""
        with app.app_context():
            # Given an authenticated user
            member = self._create_test_member()
            mock_get_user.return_value = member

            # When requesting jobs for nonexistent process
            response = self._make_authenticated_request('GET', '/api/ogc/jobs?processID=999999', None, member)

            # Then empty job list should be returned
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('jobs', data)
            self.assertEqual(len(data['jobs']), 0)

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_handles_invalid_duration_parameters(self, mock_get_user):
        """Test: GET /ogc/jobs handles invalid duration parameters"""
        with app.app_context():
            # Given an authenticated user
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                mock_jobs.return_value = (
                    {
                        'jobs': []
                    },
                    200
                )

                # When requesting jobs with invalid duration
                response = self._make_authenticated_request('GET', '/api/ogc/jobs?minDuration=invalid', None, member)

                # Then error should be returned
                self.assertEqual(response.status_code, 500)
                data = response.get_json()
                # Check for the error message structure that actually gets returned
                if 'detail' in data:
                    self.assertIn('Min/ max duration must be able to be converted', data['detail'])
                elif 'message' in data:
                    # Handle the case where the error is wrapped differently
                    self.assertIn('duration', data['message'].lower())

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_converts_camel_case_to_snake_case(self, mock_get_user):
        """Test: GET /ogc/jobs converts camelCase parameters to snake_case for HySDS"""
        with app.app_context():
            # Given an authenticated user
            member = self._create_test_member()
            mock_get_user.return_value = member
            
            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                mock_jobs.return_value = (
                    {
                        'jobs': []
                    },
                    200
                )
                
                # When requesting jobs with camelCase parameters
                response = self._make_authenticated_request('GET', '/api/ogc/jobs?pageSize=10&getJobDetails=true', None, member)
                
                # Then parameters should be converted to snake_case
                self.assertEqual(response.status_code, 200)
                mock_jobs.assert_called_once()
                args, kwargs = mock_jobs.call_args
                params = args[0]
                self.assertIn('page_size', params)
                # get_job_details is excluded from params passed to HySDS
                self.assertNotIn('get_job_details', params)
                self.assertNotIn('pageSize', params)
                self.assertNotIn('getJobDetails', params)

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_includes_proper_ogc_status_translation(self, mock_get_user):
        """Test: GET /ogc/jobs properly translates HySDS status to OGC status"""
        with app.app_context():
            # Given an authenticated user and jobs with HySDS status
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (self._create_mock_job_response(), 200)
                    mock_translate.return_value = 'successful'

                    # When requesting jobs
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs', None, member)

                    # Then status should be translated to OGC format
                    data = self._assert_response_success(response)
                    self.assertIn('jobs', data)
                    self.assertGreater(len(data['jobs']), 0)
                    self.assertEqual(data['jobs'][0]['status'], 'successful')
                    mock_translate.assert_called_with('job-completed')

    @patch('api.auth.security.get_authorized_user')
    def test_jobs_list_includes_proper_links(self, mock_get_user):
        """Test: GET /ogc/jobs includes proper links for each job"""
        with app.app_context():
            # Given an authenticated user and jobs
            member = self._create_test_member()
            mock_get_user.return_value = member

            with patch('api.utils.hysds_util.get_mozart_jobs_from_query_params') as mock_jobs:
                with patch('api.utils.ogc_translate.hysds_to_ogc_status') as mock_translate:
                    mock_jobs.return_value = (self._create_mock_job_response(), 200)
                    mock_translate.return_value = 'successful'

                    # When requesting jobs
                    response = self._make_authenticated_request('GET', '/api/ogc/jobs', None, member)

                    # Then proper links should be included
                    data = self._assert_response_success(response)
                    self.assertIn('links', data)
                    self.assertEqual(len(data['links']), 1)
                    self.assertEqual(data['links'][0]['href'], '/ogc/job/job-12345')
                    self.assertEqual(data['links'][0]['rel'], 'self')
                    self.assertEqual(data['links'][0]['type'], 'application/json')


if __name__ == '__main__':
    unittest.main()