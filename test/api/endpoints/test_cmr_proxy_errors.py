"""
CMR search proxy: error translation and transient-failure retries.

Background: maap-py pages through large searches (thousands of sequential
requests) and parses whatever the API returns as XML after stripping the JSON
string quoting. A single non-JSON/non-XML body from CMR (e.g. an HTML 503 page
from a load balancer) used to surface as a bare 500 from json.loads, which
maap-py then reported as an opaque XML ParseError. These tests pin the new
contract: upstream status codes pass through, errors are returned in a shape
the caller can parse, and 502/503/504 are retried.
"""
import json
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import requests
import responses

from api.maapapp import app
from api.endpoints import cmr as cmr_module

CMR_GRANULES = 'https://cmr.maap-project.org/search/granules'
XML_ACCEPT = {'Accept': 'application/echo10+xml'}
ECHO10_PAGE = ('<?xml version="1.0" encoding="UTF-8"?><results><hits>1</hits>'
               '<result><Granule><GranuleUR>G1</GranuleUR></Granule></result></results>')
HTML_503 = ('<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n'
            '<body><center><h1>503 Service Temporarily Unavailable</h1></center></body></html>')


def maap_py_parse(api_body_text):
    """Replicates maap-py 4.2.0 CMR._prepare_cmr_response + ET.XML exactly."""
    cmr_output = api_body_text[1:-2].replace("\\", "")
    if cmr_output.startswith('CMR Error <'):
        cmr_output = cmr_output.replace('CMR Error <', '<')
    return ET.XML(cmr_output)


class TestCmrProxyErrorTranslation(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    # --- happy paths must be byte-for-byte what maap-py already expects ---

    @responses.activate
    def test_xml_page_passes_through_unchanged(self):
        responses.add(responses.GET, CMR_GRANULES, body=ECHO10_PAGE, status=200,
                      content_type='application/echo10+xml')
        r = self.client.get('/api/cmr/granules?collection_concept_id=C1', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 200)
        page = maap_py_parse(r.get_data(as_text=True))
        self.assertEqual([c.tag for c in page], ['hits', 'result'])

    @responses.activate
    def test_json_page_passes_through_unchanged(self):
        responses.add(responses.GET, CMR_GRANULES, json={'feed': {'entry': []}}, status=200)
        r = self.client.get('/api/cmr/granules?collection_concept_id=C1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {'feed': {'entry': []}})

    # --- the failure from the 2026-10-07 gedi-subsetter job ---

    @responses.activate
    def test_html_error_page_is_not_a_500_and_is_parseable_by_maap_py(self):
        responses.add(responses.GET, CMR_GRANULES, body=HTML_503, status=503,
                      content_type='text/html')
        r = self.client.get('/api/cmr/granules?collection_concept_id=C1', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 503, 'upstream status must pass through')
        body = r.get_data(as_text=True)
        self.assertTrue(body.startswith('"CMR Error <?xml'), body[:60])
        doc = maap_py_parse(body)
        # maap-py raises a readable ValueError('Bad search response ...') when it
        # sees an <error> child; previously it hit an opaque XML ParseError.
        self.assertEqual(doc.tag, 'errors')
        self.assertEqual(doc[0].tag, 'error')
        self.assertIn('503', doc[0].text)

    @responses.activate
    def test_200_with_non_json_body_becomes_502_not_500(self):
        # Exactly the json.loads crash path from the prod traceback.
        responses.add(responses.GET, CMR_GRANULES, body='<html>oops</html>', status=200,
                      content_type='text/html')
        r = self.client.get('/api/cmr/granules?collection_concept_id=C1')
        self.assertEqual(r.status_code, 502)
        self.assertIn('non-JSON', r.get_json()['errors'][0])

    @responses.activate
    def test_cmr_json_error_passes_status_and_message_to_json_clients(self):
        responses.add(responses.GET, CMR_GRANULES, status=400,
                      json={'errors': ['Parameter [foo] was not recognized.']})
        r = self.client.get('/api/cmr/granules?foo=bar')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json(), {'errors': ['Parameter [foo] was not recognized.']})

    @responses.activate
    def test_cmr_json_error_is_translated_for_xml_clients(self):
        responses.add(responses.GET, CMR_GRANULES, status=400,
                      json={'errors': ['Parameter [foo] was not recognized.']})
        r = self.client.get('/api/cmr/granules?foo=bar', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 400)
        doc = maap_py_parse(r.get_data(as_text=True))
        self.assertEqual(doc[0].text, 'Parameter [foo] was not recognized.')

    @responses.activate
    def test_connection_failure_after_retries_is_a_504(self):
        responses.add(responses.GET, CMR_GRANULES,
                      body=requests.exceptions.ConnectionError('boom'))
        r = self.client.get('/api/cmr/granules?collection_concept_id=C1', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 504)
        doc = maap_py_parse(r.get_data(as_text=True))
        self.assertIn('ConnectionError', doc[0].text)

    @responses.activate
    def test_collections_endpoint_uses_same_translation(self):
        responses.add(responses.GET, 'https://cmr.maap-project.org/search/collections',
                      body=HTML_503, status=503, content_type='text/html')
        r = self.client.get('/api/cmr/collections?keyword=x')
        self.assertEqual(r.status_code, 503)
        self.assertIn('503', r.get_json()['errors'][0])

    def test_xml_special_characters_are_escaped_in_error_body(self):
        with app.test_request_context(headers=XML_ACCEPT):
            body, code, _ = cmr_module.cmr_error_response(502, 'bad <thing> & "stuff"')
        self.assertEqual(code, 502)
        doc = maap_py_parse(json.dumps(body) + '\n')
        self.assertEqual(doc[0].text, 'bad <thing> & "stuff"')


class _FlakyCmr(BaseHTTPRequestHandler):
    """Fails with 503 for the first N requests, then serves an echo10 page."""
    failures_remaining = 2
    requests_seen = 0

    def do_GET(self):
        _FlakyCmr.requests_seen += 1
        if _FlakyCmr.failures_remaining > 0:
            _FlakyCmr.failures_remaining -= 1
            self.send_response(503)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_503.encode())
            return
        body = ECHO10_PAGE.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/echo10+xml')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


class TestCmrProxyRetries(unittest.TestCase):
    """Exercises the real urllib3 Retry wiring on the session adapter, which
    the `responses` library bypasses (it replaces HTTPAdapter.send)."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), _FlakyCmr)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:{}'.format(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        _FlakyCmr.failures_remaining = 2
        _FlakyCmr.requests_seen = 0

    def test_retry_policy_matches_settings(self):
        adapter = cmr_module._cmr_session.get_adapter('https://cmr.maap-project.org')
        retry = adapter.max_retries
        self.assertEqual(retry.total, cmr_module.settings.CMR_RETRIES)
        self.assertEqual(set(retry.status_forcelist), {502, 503, 504})
        self.assertEqual(retry.allowed_methods, frozenset(['GET']))
        self.assertFalse(retry.raise_on_status)

    def test_transient_503s_are_retried_and_the_page_is_returned(self):
        with patch.object(cmr_module.settings, 'CMR_URL', self.url):
            r = self.client.get('/api/cmr/granules?collection_concept_id=C1', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_FlakyCmr.requests_seen, 3, 'two 503s then success')
        page = maap_py_parse(r.get_data(as_text=True))
        self.assertEqual(page[1].tag, 'result')

    def test_persistent_503_is_returned_after_retries_are_exhausted(self):
        _FlakyCmr.failures_remaining = 99
        with patch.object(cmr_module.settings, 'CMR_URL', self.url):
            r = self.client.get('/api/cmr/granules?collection_concept_id=C1', headers=XML_ACCEPT)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(_FlakyCmr.requests_seen, 1 + cmr_module.settings.CMR_RETRIES)
        doc = maap_py_parse(r.get_data(as_text=True))
        self.assertEqual(doc[0].tag, 'error')


if __name__ == '__main__':
    unittest.main()
