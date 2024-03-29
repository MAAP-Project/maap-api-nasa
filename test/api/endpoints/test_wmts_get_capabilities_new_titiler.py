import unittest
import os
from api.maapapp import app
from api import settings
from api.endpoints.wmts_collections import default_collections
import json
from unittest.mock import Mock, MagicMock
import api.endpoints.wmts as wmts
import requests as rq

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True

class GetCapabilitiesCase(unittest.TestCase):
    def get_capabilities_path(self, params=''):
      path = 'api/wmts/GetCapabilities'
      if params:
        path = f'{path}?{params}'
      return path

    def assert_response(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/xml')
        self.assertTrue(int(response.headers['Content-Length']) > 0)

    def test_get_capabilities_default(self):
        url = settings.API_HOST_URL + str(self.get_capabilities_path())
        response = rq.get(url)
        return self.assert_response(response)
    