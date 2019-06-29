import unittest
import os
from api.maapapp import app
from api import settings
import json

# ROOT = os.path.dirname(os.path.abspath(__file__))
# collections_json = open(os.path.join(ROOT, '../../wmts_collections.json'), 'r').read()
# default_collections = json.loads(collections_json)

class MyAppCase(unittest.TestCase):
    def get_capabilities_path(self, params={}):
      return 'api/wmts/GetCapabilities'

    def setUp(self):
        app.config['TESTING'] = True
        self.maxDiff = None # For seeing the whole redirect message
        self.app = app.test_client()

    def test_get_capabilities_default(self):
        response = self.app.get(self.get_capabilities_path())
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 200)
