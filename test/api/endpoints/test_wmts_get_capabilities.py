import unittest
import os
from api.maapapp import app
from api import settings
from api.endpoints.wmts_collections import default_collections
import json
from unittest.mock import Mock, MagicMock
import api.endpoints.wmts as wmts

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True

class GetCapabilitiesCase(unittest.TestCase):
    def get_capabilities_path(self, params=''):
      path = 'api/wmts/GetCapabilities'
      if params:
        path = f'{path}?{params}'
      return path

    def setUp(self):
        app.config['TESTING'] = True
        self.maxDiff = None # For seeing the whole redirect message
        self.app = app.test_client()
        if MOCK_RESPONSES:
            wmts.get_mosaic_tilejson = MagicMock(return_value = {
                                                     'bounds': [8.727, -2.291, 13.800, 2.04],
                                                     'center': [11.264, -0.121],
                                                     'minzoom': 6,
                                                     'maxzoom': 12,
                                                     'tilejson': '2.1.0',
                                                     'tiles': ['https://888.execute-api.us-east-1.amazonaws.com/production/mosaic/{z}/{x}/{y}.png?urls=s3://bucket/cog.tif']
                                                 })
            wmts.get_stats = MagicMock(return_value = {
                                         'statistics': {
                                           '1': {
                                             'pc': [2.3, 51.1]
                                           }
                                         }
                                       })
            wmts.get_cog_urls_string = MagicMock(return_value = 'out.cog.tif')

    def test_get_capabilities_default(self):
        response = self.app.get(self.get_capabilities_path())
        data = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        [self.assertTrue(collection_name in data) for collection_name in default_collections.keys()]

    def test_get_capabilites_params(self):
        response = self.app.get(self.get_capabilities_path("attribute[]=float,Flight Number,57438"))
        data = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
