import unittest
import json
import responses
from unittest.mock import patch, MagicMock
from datetime import datetime
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.role import Role
from api.models.member_job import MemberJob
from api.models.member_session import MemberSession


class TestJobManagement(unittest.TestCase):
    """
    Comprehensive test suite for Job Management functionality
    Tests job submission, monitoring, access control, and HySDS integration
    """

    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
            # Clear any existing test data
            db.session.query(MemberJob).delete()
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
            db.session.query(MemberJob).delete()
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

    def _create_test_member(self, username="testuser", role_id=Role.ROLE_MEMBER):
        """Create a test member with optional custom username and role"""
        with app.app_context():
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
            
            return member.id

    def test_job_status_can_be_queried(self):
        """Test: Job status can be queried"""
        # Mock HySDS job status response
        with patch('api.utils.hysds_util.mozart_job_status') as mock_status, \
             patch('api.utils.ogc_translate.status_response') as mock_response:
            
            mock_status.return_value = {
                'status': 'job-running',
                'job_id': 'test-job-12345'
            }
            mock_response.return_value = '''<?xml version="1.0" encoding="UTF-8"?>
            <wps:StatusInfo>
                <wps:JobID>test-job-12345</wps:JobID>
                <wps:Status>Running</wps:Status>
            </wps:StatusInfo>'''
            
            # When job status is requested
            response = self.client.get('/api/dps/job/test-job-12345/status')
            
            # Then current job status should be returned
            self.assertEqual(response.status_code, 200)
            self.assertIn('test-job-12345', response.get_data(as_text=True))

    def test_job_status_handles_missing_job(self):
        """Test: Job status handles missing job gracefully"""
        # Mock HySDS job status failure
        with patch('api.utils.hysds_util.mozart_job_status') as mock_status:
            mock_status.side_effect = Exception("Job not found")
            
            # When status is requested for non-existent job
            response = self.client.get('/api/dps/job/nonexistent-job/status')
            
            # Then error should be returned gracefully
            self.assertEqual(response.status_code, 500)
            self.assertIn('Failed to get job status', response.get_data(as_text=True))

    def test_job_result_retrieval_works_correctly(self):
        """Test: Job result retrieval works correctly"""
        # Mock HySDS job result response with the actual return structure
        with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
            
            mock_get_job.return_value = {
                'job': {
                    'job_info': {
                        'metrics': {
                            'products_staged': [
                                {
                                    'id': 'product-123',
                                    'urls': ['s3://s3.us-west-2.amazonaws.com:80/bucket/path/product-123']
                                }
                            ]
                        }
                    }
                },
                'traceback': None
            }
            
            # When job results are requested
            response = self.client.get('/api/dps/job/test-job-12345')
            
            # Then results should be returned correctly (XML response)
            self.assertEqual(response.status_code, 200)
            self.assertIn('xml', response.content_type)
            response_text = response.get_data(as_text=True)
            self.assertIn('product-123', response_text)

    def test_job_capabilities_can_be_retrieved(self):
        """Test: Job capabilities can be retrieved"""
        # Mock HySDS algorithms response
        with patch('api.utils.hysds_util.get_algorithms') as mock_algorithms, \
             patch('api.utils.ogc_translate.get_capabilities') as mock_capabilities:
            
            mock_algorithms.return_value = [
                {'id': 'algo1', 'name': 'Test Algorithm 1'},
                {'id': 'algo2', 'name': 'Test Algorithm 2'}
            ]
            mock_capabilities.return_value = '''<?xml version="1.0" encoding="UTF-8"?>
            <wps:Capabilities service="WPS" version="1.0.0">
                <wps:Process>
                    <ows:Identifier>algo1</ows:Identifier>
                    <ows:Title>Test Algorithm 1</ows:Title>
                </wps:Process>
            </wps:Capabilities>'''
            
            # When job capabilities are requested
            response = self.client.get('/api/dps/job')
            
            # Then capabilities document should be returned
            self.assertEqual(response.status_code, 200)
            self.assertIn('xml', response.content_type)

    def test_algorithm_description_can_be_retrieved(self):
        """Test: Algorithm description can be retrieved"""
        # Mock HySDS job spec response
        with patch('api.utils.hysds_util.get_job_spec') as mock_spec, \
             patch('api.utils.ogc_translate.describe_process_response') as mock_describe:
            
            mock_spec.return_value = {
                'result': {
                    'params': [
                        {'name': 'param1', 'type': 'string'},
                        {'name': 'param2', 'type': 'integer'}
                    ],
                    'recommended-queues': ['standard-queue']
                }
            }
            mock_describe.return_value = '''<?xml version="1.0" encoding="UTF-8"?>
            <wps:ProcessDescriptions>
                <ProcessDescription>
                    <ows:Identifier>test-algorithm</ows:Identifier>
                    <DataInputs>
                        <Input>
                            <ows:Identifier>param1</ows:Identifier>
                            <LiteralData>
                                <ows:DataType>string</ows:DataType>
                            </LiteralData>
                        </Input>
                    </DataInputs>
                </ProcessDescription>
            </wps:ProcessDescriptions>'''
            
            # When algorithm description is requested
            response = self.client.get('/api/dps/job/describeprocess/test-algorithm')
            
            # Then algorithm parameters should be returned
            self.assertEqual(response.status_code, 200)
            self.assertIn('xml', response.content_type)

    @patch('api.auth.security.get_authorized_user')
    def test_job_submission_requires_authentication(self, mock_get_user):
        """Test: Job submission requires authentication"""
        # Given no authenticated user
        mock_get_user.return_value = None
        
        # When a job is submitted without authentication
        job_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <wps:Execute service="WPS" version="1.0.0" xmlns:wps="http://www.opengis.net/wps/1.0.0">
            <ows:Identifier>test-algorithm</ows:Identifier>
        </wps:Execute>'''
        
        response = self.client.post('/api/dps/job', 
                                  data=job_xml,
                                  content_type='application/xml')
        
        # Then authentication should be required
        # 401 is correct code to return here for unauthenticated users, 
        # 403 is used for authenticated users lacking necessary permissions
        self.assertEqual(response.status_code, 401)

    @patch('api.auth.security.get_authorized_user')
    def test_job_listing_requires_authentication(self, mock_get_user):
        """Test: Job listing requires authentication"""
        # Given no authenticated user
        mock_get_user.return_value = None
        
        # When job listing is requested without authentication
        response = self.client.get('/api/dps/job/list')
        
        # Then authentication should be required
        self.assertEqual(response.status_code, 401)

    @patch('api.auth.security.get_authorized_user')
    def test_job_cancellation_requires_authentication(self, mock_get_user):
        """Test: Job cancellation requires authentication"""
        # Given no authenticated user
        mock_get_user.return_value = None
        
        # When job cancellation is attempted without authentication
        response = self.client.post('/api/dps/job/cancel/test-job-12345')
        
        # Then authentication should be required
        self.assertEqual(response.status_code, 401)

    def test_member_job_model_functionality(self):
        """Test: MemberJob model functionality"""
        with app.app_context():
            # Given a member and job tracking
            member_id = self._create_test_member()
            
            # When a job is tracked for the member
            member_job = MemberJob(
                member_id=member_id,
                job_id='test-job-789',
                submitted_date=datetime.utcnow()
            )
            db.session.add(member_job)
            db.session.commit()
            
            # Then job should be linked to member
            saved_job = db.session.query(MemberJob).filter_by(job_id='test-job-789').first()
            self.assertIsNotNone(saved_job)
            self.assertEqual(saved_job.member_id, member_id)
            self.assertEqual(saved_job.job_id, 'test-job-789')
            self.assertEqual(saved_job.member.username, 'testuser')

    def test_job_metrics_endpoint_works_correctly(self):
        """Test: Job metrics endpoint works correctly"""
        # Mock HySDS job metrics response
        with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
            mock_get_job.return_value = {
                'job': {
                    'job_info': {
                        'metrics': {
                            'job_dir_size': 1024,
                            'usage_stats': [{
                                'cgroups': {
                                    'cpu_stats': {'cpu_usage': {'total_usage': 12345}},
                                    'memory_stats': {'cache': 512, 'usage': {'usage': 1024, 'max_usage': 2048}, 'stats': {'swap': 0}},
                                    'blkio_stats': {'io_service_bytes_recursive': [
                                        {'op': 'Read', 'value': 1000},
                                        {'op': 'Write', 'value': 2000},
                                        {'op': 'Sync', 'value': 500},
                                        {'op': 'Async', 'value': 750},
                                        {'op': 'Total', 'value': 3000}
                                    ]}
                                }
                            }]
                        },
                        'cmd_start': '2023-01-01T10:00:00Z',
                        'cmd_end': '2023-01-01T11:00:00Z',
                        'cmd_duration': 3600,
                        'facts': {
                            'architecture': 'x86_64',
                            'operatingsystem': 'Ubuntu',
                            'memorysize': '8 GB',
                            'ec2_instance_type': 't3.medium'
                        }
                    }
                }
            }
            
            # When job metrics are requested
            response = self.client.get('/api/dps/job/test-job-12345/metrics')
            
            # Then metrics should be returned correctly
            self.assertEqual(response.status_code, 200)
            self.assertIn('xml', response.content_type)
            response_text = response.get_data(as_text=True)
            self.assertIn('t3.medium', response_text)
            self.assertIn('x86_64', response_text)

    def test_job_metrics_handles_missing_job(self):
        """Test: Job metrics handles missing job gracefully"""
        # Mock HySDS job metrics failure
        with patch('api.utils.hysds_util.get_mozart_job') as mock_get_job:
            mock_get_job.side_effect = Exception("Job not found")
            
            # When metrics are requested for non-existent job
            response = self.client.get('/api/dps/job/nonexistent-job/metrics')
            
            # Then error should be returned gracefully
            self.assertEqual(response.status_code, 500)
            self.assertIn('Failed to get job metrics', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()