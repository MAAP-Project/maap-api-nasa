from json.decoder import JSONDecodeError
import unittest
import json
from unittest.mock import Mock, MagicMock
import api.endpoints.ogcapi_features as ogcapi_features
from api.maapapp import app
from api import settings
from flask import Response
import os
import pytest

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

collection = {
  'short_name': 'AfriSAR_UAVSAR_Coreg_SLC',
  'version': '1'
}

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True

class MockResponse:
    def __init__(self, status_code, headers, text):
        self.headers = headers
        self.status_code = status_code
        self.text = text


class OgcapiFeaturesTestCase(unittest.TestCase):
    # Helper functions
    def get_path(self, path):
      return f"api/ogcapi-features{zxy}"

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
        settings.OGCAPI_FEATURES_ENDPOINT = "http://example.com/oaf"
        # if MOCK_RESPONSES:
            # mock_response = Mock()
            # mock_response.content = 'imagebytes'
            # mock_response.status_code = 200
            # ogcapi_features.get_tiles = MagicMock(return_value = mock_response)

    def test_rewrite_urls(self):
        ogcapi_features.rewrite_urls(None, "")
        ogcapi_features.rewrite_urls({"links": [ { "not_href": "" } ]}, "")

        rewritten = ogcapi_features.rewrite_urls({"links": [ { "href": "http://example.com/oaf/foo" } ]}, "x")
        assert rewritten["links"][0]["href"] == "x/foo"

        rewritten = ogcapi_features.rewrite_urls_in_list(
            [
                {"links": [ { "href": "http://example.com/oaf/foo" } ]},
                {"links": [ { "href": "http://example.com/oaf/foo" } ]}
            ], 
            "x"
            )
        assert rewritten[0]["links"][0]["href"] == "x/foo"
        assert rewritten[1]["links"][0]["href"] == "x/foo"

    def test_respond(self):
        res = ogcapi_features.respond(MockResponse(200, {"content-type": "application/json"}, '{ "id": "1" }'), "")
        assert res.status_code == 200
        assert res.content_type == "application/json"
        assert res.response == [b'{"id": "1"}']

        body = {
            "links": [ 
                { "href": "http://example.com/oaf/foo" }, 
                { "href": "http://example.com/oaf/bar" } 
            ],
            "items": [ { "links": [ { "href": "http://example.com/oaf/baz" } ] } ],
            "collections": [ { "links": [ { "href": "http://example.com/oaf/corge" } ] } ]
        }

        res = ogcapi_features.respond(MockResponse(200, {"content-type": "application/json"}, json.dumps(body)), "x")
        res_body = json.loads(res.response[0])
        assert res_body["links"][0]["href"] == "x/foo"
        assert res_body["links"][1]["href"] == "x/bar"
        assert res_body["items"][0]["links"][0]["href"] == "x/baz"
        assert res_body["collections"][0]["links"][0]["href"] == "x/corge"
        assert res.status_code == 200
        assert res.content_type == "application/json"

        res = ogcapi_features.respond(MockResponse(200, {"content-type": "text/plain"}, 'xxx'), "")
        assert res.status_code == 200
        assert res.content_type == "text/plain"
        assert res.response == [b'xxx']

        try:
            res = ogcapi_features.respond(MockResponse(200, {"content-type": "application/json"}, "xxx"), "")
            pytest.fail("should have failed b/c advertised as json but was not")
        except JSONDecodeError as e:
            pass

        res = ogcapi_features.respond(MockResponse(500, {"content-type": "application/json"}, "xxx"), "")
        assert res.status_code == 500
        assert res.content_type == "application/json"
        assert res.response == [b"xxx"]