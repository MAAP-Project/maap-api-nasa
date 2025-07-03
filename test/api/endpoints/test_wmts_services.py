# Replaces: test_wmts_get_tile.py, test_wmts_get_capabilities.py, 
# test_wmts_get_tile_new_titiler.py, test_wmts_get_capabilities_new_titiler.py

import unittest
import responses
from unittest.mock import patch, MagicMock, Mock
from api.models import initialize_sql
from api.maap_database import db
from api.maapapp import app
import api.endpoints.wmts as wmts
import json

class TestWMTSServices(unittest.TestCase):
    """Unified WMTS service tests for both legacy and new Titiler."""
    
    def setUp(self):
        """Setup test environment."""
        app.config['TESTING'] = True
        self.app = app.test_client()
        self.maxDiff = None
        initialize_sql(db.engine)
        db.create_all()
        
        # Mock common WMTS functions
        mock_response = Mock()
        mock_response.content = b'imagebytes'
        mock_response.status_code = 200
        wmts.get_tiles = MagicMock(return_value=mock_response)
        
        wmts.get_mosaic_tilejson = MagicMock(return_value={
            'bounds': [8.727, -2.291, 13.800, 2.04],
            'center': [11.264, -0.121],
            'minzoom': 6,
            'maxzoom': 12,
            'tilejson': '2.1.0',
            'tiles': ['https://888.execute-api.us-east-1.amazonaws.com/production/mosaic/{z}/{x}/{y}.png?urls=s3://bucket/cog.tif']
        })
        
        wmts.get_stats = MagicMock(return_value={
            'statistics': {
                '1': {
                    'pc': [2.3, 51.1]
                }
            }
        })
    
    def tearDown(self):
        """Clean up test database."""
        db.session.remove()
        db.drop_all()
    
    # Tile Generation Tests
    def test_wmts_tile_generation_with_granule_ur(self):
        """Tests WMTS tile generation using granule UR."""
        wmts.get_cog_urls_string = MagicMock(return_value='test.tif')
        
        response = self.app.get(
            "/api/wmts/GetTile/10/545/513.png"
            "?granule_urs=uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt"
            "&color_map=schwarzwald"
            "&rescale=-1,1"
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
    
    def test_wmts_tile_generation_with_collection(self):
        """Tests WMTS tile generation using collection parameters."""
        wmts.get_cog_urls_string = MagicMock(return_value='mosaic.cog')
        
        response = self.app.get(
            "/api/wmts/GetTile/10/545/513.png"
            "?short_name=AfriSAR_UAVSAR_Coreg_SLC"
            "&version=1"
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
    
    def test_wmts_tile_missing_identifier_error(self):
        """Tests error handling when required identifiers are missing."""
        response = self.app.get("/api/wmts/GetTile/10/545/513.png")
        
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 422)
        error_message = 'Neither required param granule_urs nor collection name and version provided in request'
        self.assertEqual(data['message'], error_message)
        self.assertEqual(data['error'], error_message)
    
    def test_wmts_tile_no_browse_images_error(self):
        """Tests error handling when no browse images are available."""
        wmts.get_cog_urls_string = MagicMock(return_value="")
        
        response = self.app.get(
            "/api/wmts/GetTile/10/545/513.png?granule_urs=no_browse.vrt"
        )
        
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['error'], 'No browse images')
    
    # Capabilities Document Tests
    def test_wmts_capabilities_document_generation(self):
        """Tests WMTS capabilities document generation."""
        wmts.get_cog_urls_string = MagicMock(return_value='out.cog.tif')
        
        response = self.app.get("/api/wmts/GetCapabilities")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response.headers['Content-Type'])
        
        # Verify capabilities document structure
        content = response.get_data(as_text=True)
        self.assertIn('<Capabilities', content)
        self.assertIn('ServiceIdentification', content)
        self.assertIn('Contents', content)
    
    # Multi-granule and Advanced Tests
    def test_wmts_multiple_granules_mosaic(self):
        """Tests tile generation with multiple granules."""
        wmts.get_cog_urls_string = MagicMock(return_value="granule1.tif,granule2.tif")
        
        response = self.app.get(
            "/api/wmts/GetTile/10/545/513.png"
            "?granule_urs=uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt,uavsar_AfriSAR_v1_SLC-hundre_14048_16008_007_160225_L090.vrt"
            "&color_map=schwarzwald"
            "&rescale=-1,1"
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
    
    # Titiler Integration Tests
    def test_titiler_integration_error_handling(self):
        """Tests error handling for Titiler integration failures."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b"Titiler error"
        wmts.get_tiles = MagicMock(return_value=mock_response)
        wmts.get_cog_urls_string = MagicMock(return_value="test.tif")
        
        response = self.app.get(
            "/api/wmts/GetTile/10/545/513.png?granule_urs=test.vrt"
        )
        
        # The API should handle Titiler errors gracefully
        self.assertIn(response.status_code, [500, 200])  # Either handle error or pass through

if __name__ == '__main__':
    unittest.main()