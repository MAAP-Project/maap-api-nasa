import unittest
import os
from api.maapapp import app
from api import settings
from api.endpoints.wmts_collections import default_collections
import json

class GetCapabilitiesCase(unittest.TestCase):
    def get_capabilities_path(self, params={}):
      return 'api/wmts/GetCapabilities'

    def setUp(self):
        app.config['TESTING'] = True
        self.maxDiff = None # For seeing the whole redirect message
        self.app = app.test_client()

    def test_get_capabilities_default(self):
        response = self.app.get(self.get_capabilities_path())
        data = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        [self.assertTrue(collection_name in data) for collection_name in default_collections.keys()]
