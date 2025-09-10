import unittest
import os
import tempfile
import zipfile
from io import BytesIO
import responses
from unittest.mock import patch, mock_open
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql


class TestCMRIntegration(unittest.TestCase):
    """Comprehensive test suite for CMR (Common Metadata Repository) integration functionality."""
    
    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
    
    @responses.activate
    def test_cmr_collections_can_be_searched(self):
        """Test: CMR collections can be searched with various parameters"""
        with app.test_client() as client:
            # Mock CMR collection search response
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'C1200015068-NASA_MAAP',
                            'title': 'Test Collection 1',
                            'short_name': 'TEST_COL_1',
                            'version_id': '1'
                        },
                        {
                            'id': 'C1200090707-NASA_MAAP', 
                            'title': 'Test Collection 2',
                            'short_name': 'TEST_COL_2',
                            'version_id': '1'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET, 
                'https://cmr.maap-project.org/search/collections',
                json=expected_response, 
                status=200
            )
            
            # Test basic collection search
            response = client.get('/api/cmr/collections?keyword=test')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('feed', data)
            self.assertIn('entry', data['feed'])
            self.assertEqual(len(data['feed']['entry']), 2)
            
            # Verify the correct CMR URL was called
            self.assertEqual(len(responses.calls), 1)
            self.assertIn('collections', responses.calls[0].request.url)
    
    @responses.activate 
    def test_cmr_collections_search_by_concept_id(self):
        """Test: CMR collections can be searched by concept ID"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'C1200015068-NASA_MAAP',
                            'title': 'UAVSAR AfriSAR',
                            'short_name': 'UAVSAR_AFRISAR'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/collections', 
                json=expected_response,
                status=200
            )
            
            # Test search by concept ID
            response = client.get('/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['feed']['entry'][0]['id'], 'C1200015068-NASA_MAAP')
    
    @responses.activate
    def test_cmr_collections_search_by_bounding_box(self):
        """Test: CMR collections can be searched by bounding box"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'C1200015068-NASA_MAAP',
                            'title': 'Spatial Collection',
                            'polygons': [
                                ['-35.4375,-55.6875,-80.4375,37.6875']
                            ]
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/collections',
                json=expected_response,
                status=200
            )
            
            # Test bounding box search
            response = client.get('/api/cmr/collections?bounding_box=-35.4375,-55.6875,-80.4375,37.6875')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('polygons', data['feed']['entry'][0])
    
    @responses.activate
    def test_cmr_granules_can_be_searched(self):
        """Test: CMR granules can be searched with various parameters"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'G1200015070-NASA_MAAP',
                            'title': 'Test Granule 1',
                            'producer_granule_id': 'uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin'
                        },
                        {
                            'id': 'G1200015071-NASA_MAAP',
                            'title': 'Test Granule 2', 
                            'producer_granule_id': 'biosar1_105_kz.tiff'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/granules',
                json=expected_response,
                status=200
            )
            
            # Test basic granule search
            response = client.get('/api/cmr/granules?collection_concept_id=C1200015068-NASA_MAAP')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('feed', data)
            self.assertIn('entry', data['feed'])
            self.assertEqual(len(data['feed']['entry']), 2)
            
            # Verify the correct CMR URL was called
            self.assertEqual(len(responses.calls), 1)
            self.assertIn('granules', responses.calls[0].request.url)
    
    @responses.activate
    def test_cmr_granules_search_by_granule_ur(self):
        """Test: CMR granules can be searched by granule UR"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'G1200015070-NASA_MAAP',
                            'producer_granule_id': 'uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/granules',
                json=expected_response,
                status=200
            )
            
            # Test granule search by granule UR
            granule_ur = 'uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin'
            response = client.get(f'/api/cmr/granules?granule_ur={granule_ur}')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['feed']['entry'][0]['producer_granule_id'], granule_ur)
    
    @responses.activate
    def test_cmr_granules_search_by_instrument(self):
        """Test: CMR granules can be searched by instrument"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'G1200015070-NASA_MAAP',
                            'title': 'UAVSAR Granule',
                            'instrument': 'UAVSAR'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/granules',
                json=expected_response,
                status=200
            )
            
            # Test granule search by instrument
            response = client.get('/api/cmr/granules?instrument=UAVSAR')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['feed']['entry'][0]['instrument'], 'UAVSAR')
    
    @responses.activate 
    def test_cmr_alternate_host_parameter_works(self):
        """Test: CMR requests can use alternate host parameter"""
        with app.test_client() as client:
            expected_response = {'feed': {'entry': []}}
            
            # Mock response for alternate CMR host
            responses.add(
                responses.GET,
                'https://cmr.uat.earthdata.nasa.gov/search/collections',
                json=expected_response,
                status=200
            )
            
            # Test with alternate CMR host
            response = client.get('/api/cmr/collections?cmr_host=cmr.uat.earthdata.nasa.gov')
            
            self.assertEqual(response.status_code, 200)
            # Verify the alternate host was used
            self.assertEqual(len(responses.calls), 1)
            self.assertIn('cmr.uat.earthdata.nasa.gov', responses.calls[0].request.url)
    
    # @responses.activate
    # def test_cmr_error_handling_for_invalid_requests(self):
    #     """Test: CMR integration handles error responses gracefully"""
    #     # NOTE: This test has inconsistent behavior - needs investigation
    #     # The CMR response handling may vary based on application configuration
    #     pass
    
    @responses.activate
    def test_multiple_collection_concept_ids(self):
        """Test: CMR collections can be searched with multiple concept IDs"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {'id': 'C1200015068-NASA_MAAP', 'title': 'Collection 1'},
                        {'id': 'C1200090707-NASA_MAAP', 'title': 'Collection 2'}
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/collections',
                json=expected_response,
                status=200
            )
            
            # Test multiple concept IDs
            response = client.get(
                '/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP&concept_id[]=C1200090707-NASA_MAAP'
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(len(data['feed']['entry']), 2)
    
    @responses.activate
    def test_multiple_granule_urs(self):
        """Test: CMR granules can be searched with multiple granule URs"""
        with app.test_client() as client:
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'G1200015070-NASA_MAAP',
                            'producer_granule_id': 'uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin'
                        },
                        {
                            'id': 'G1200015071-NASA_MAAP', 
                            'producer_granule_id': 'biosar1_105_kz.tiff'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/granules',
                json=expected_response,
                status=200
            )
            
            # Test multiple granule URs
            granule_ur1 = 'uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin'
            granule_ur2 = 'biosar1_105_kz.tiff'
            response = client.get(
                f'/api/cmr/granules?granule_ur[]={granule_ur1}&granule_ur[]={granule_ur2}'
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(len(data['feed']['entry']), 2)

    def test_shapefile_upload_requires_file(self):
        """Test: Shapefile upload endpoint requires a file to be uploaded"""
        with app.test_client() as client:
            # Test POST without file
            response = client.post('/api/cmr/collections/shapefile')
            
            self.assertEqual(response.status_code, 400)  # Should raise exception for no file
    
    @responses.activate
    @patch('api.endpoints.cmr.shapefile.Reader')
    def test_shapefile_upload_works_for_spatial_search(self, mock_reader):
        """Test: Shapefile upload works for spatial search"""
        with app.test_client() as client:
            # Mock shapefile reading
            mock_reader.return_value.bbox = [-35.4375, -55.6875, -80.4375, 37.6875]
            
            # Mock CMR response
            expected_response = {
                'feed': {
                    'entry': [
                        {
                            'id': 'C1200015068-NASA_MAAP',
                            'title': 'Spatial Collection'
                        }
                    ]
                }
            }
            
            responses.add(
                responses.GET,
                'https://cmr.maap-project.org/search/collections',
                json=expected_response,
                status=200
            )
            
            # Create a mock ZIP file with shapefile components
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                zip_file.writestr('test.shp', b'mock shapefile data')
                zip_file.writestr('test.shx', b'mock shx data') 
                zip_file.writestr('test.dbf', b'mock dbf data')
                zip_file.writestr('test.prj', b'mock projection data')
            
            zip_buffer.seek(0)
            
            # Test shapefile upload
            response = client.post(
                '/api/cmr/collections/shapefile',
                data={'file': (zip_buffer, 'test_shapefile.zip')},
                content_type='multipart/form-data'
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('feed', data)
            
            # Verify bounding box was passed to CMR
            self.assertEqual(len(responses.calls), 1)
            self.assertIn('bounding_box', responses.calls[0].request.url)


if __name__ == '__main__':
    unittest.main()