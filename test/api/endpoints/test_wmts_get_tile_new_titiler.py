import unittest
import json
from unittest.mock import Mock, MagicMock
import api.endpoints.wmts as wmts
from api.maapapp import app
from api import settings
from flask import Response
import os
import requests as rq
import pdb

g1 = {
    'granule_ur': 'uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt',
    'cog_url': 's3://cumulus-map-internal/file-staging/circleci/AfriSAR_UAVSAR_Coreg_SLC___1/uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt.cog.tif',
    'color_map': 'schwarzwald',
    'rescale': '-1,1',
    'zxy': '10/545/513'
}

g2 = {
    'granule_ur': 'uavsar_AfriSAR_v1_SLC-hundre_14048_16008_007_160225_L090.vrt',
    'cog_url': 's3://cumulus-map-internal/file-staging/circleci/AfriSAR_UAVSAR_Coreg_SLC___1/uavsar_AfriSAR_v1_SLC-hundre_14048_16008_007_160225_L090.vrt.cog.tif'
}

g3 = {    
    'granule_ur': 'SC:AFLVIS2.001:138349020',
    'cog_url': 's3://cumulus-map-internal/file-staging/nasa-map/AFLVIS2___001/LVIS2_Gabon2016_0308_R1808_048492_cog.tif',
    'rescale':'11,57',
    'zxy': '11/1077/1020',
    'indexes':'1,2'
}
g4 = {
    'granule_ur': 'SC:AFLVIS2.001:138348905',
    'cog_url': 's3://cumulus-map-internal/file-staging/nasa-map/AFLVIS2___001/LVIS2_Gabon2016_0308_R1808_049095_cog.tif',
    'rescale':'11,57',
    'zxy': '11/1077/1020',
    'indexes':'1,2'
}

collection = {
  'short_name': 'AfriSAR_UAVSAR_Coreg_SLC',
  'version': '1'
}

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True

class GetTileCase(unittest.TestCase):
    # Helper functions
    def get_tile_path(self, zxy='1/1/1.png'):
      return f"api/wmts/GetTile/{zxy}.png"

    def assert_image_response(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        self.assertTrue(int(response.headers['Content-Length']) > 0)

    # Setup
    def setUp(self):
        app.config['TESTING'] = True
        self.maxDiff = None # For seeing the whole redirect message
        self.app = app.test_client()
        if MOCK_RESPONSES:
            mock_response = Mock()
            mock_response.content = 'imagebytes'
            mock_response.status_code = 200
            wmts.get_tiles = MagicMock(return_value = mock_response)

    
    # Tests
    def test_get_tile_no_identifier(self):
        response = self.app.get(self.get_tile_path())
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 422)
        error_message = 'Neither required param granule_urs nor collection name and version provided in request'
        self.assertEqual(data['message'], error_message)
        self.assertEqual(data['error'], error_message)

    def test_get_tile_no_browse(self):
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string = MagicMock(return_value = '')
        test_granule_ur = 'test.vrt'
        response = self.app.get(f"{self.get_tile_path()}?granule_urs={test_granule_ur}")
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 500)
        error_message = 'Failed to fetch tiles for {"granule_urs": "test.vrt"}'
        self.assertEqual(data['message'], error_message)
        self.assertEqual(data['error'], 'No browse images')
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string.reset_mock()

    def test_get_tile_returns_image(self):
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string = MagicMock(return_value = 'test.tif')
        tile_path = f"{self.get_tile_path(g1['zxy'])}?granule_urs={g1['granule_ur']}&color_map={g1['color_map']}&rescale={g1['rescale']}"
        print(tile_path)
        url = settings.API_HOST_URL + str(tile_path)
        response = rq.get(url)
        return self.assert_image_response(response)
    
    def test_get_tile_returns_image3(self):
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string = MagicMock(return_value = 'test.tif')
        tile_path = f"{self.get_tile_path(g3['zxy'])}?granule_urs={g3['granule_ur']}&bidx={g3['indexes']}&rescale={g3['rescale']}"
        print(tile_path)
        url = settings.API_HOST_URL + str(tile_path)
        response = rq.get(url)
        return self.assert_image_response(response)

    def test_get_tile_returns_image4(self):
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string = MagicMock(return_value = 'test.tif')
        tile_path = f"{self.get_tile_path(g4['zxy'])}?granule_urs={g4['granule_ur']}&bidx={g4['indexes']}&rescale={g4['rescale']}"
        print(tile_path)
        url = settings.API_HOST_URL + str(tile_path)
        response = rq.get(url)
        return self.assert_image_response(response)
        
    def test_get_tile_collection_returns_image(self):
        if MOCK_RESPONSES:
            wmts.get_cog_urls_string = MagicMock(return_value = 'mosaic.cog')
        tile_path = f"{self.get_tile_path(g1['zxy'])}?short_name={collection['short_name']}&version={collection['version']}&color_map={g1['color_map']}&rescale={g1['rescale']}"
        print(tile_path)
        url = settings.API_HOST_URL + str(tile_path)
        response = rq.get(url)
        print(response)
        return self.assert_image_response(response)
    
