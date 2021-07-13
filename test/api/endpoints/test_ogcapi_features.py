from json.decoder import JSONDecodeError
import unittest
import json
import api.endpoints.ogcapi_features as ogcapi_features
from api import settings
import pytest

class MockResponse:
    def __init__(self, status_code, headers, text):
        self.headers = headers
        self.status_code = status_code
        self.text = text


class OgcapiFeaturesTestCase(unittest.TestCase):

    # Setup
    def setUp(self):
        self.maxDiff = None # For seeing the whole redirect message
        settings.OGCAPI_FEATURES_ENDPOINT = "http://example.com/oaf"

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
