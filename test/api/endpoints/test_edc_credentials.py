"""Error mapping for the Earthdata Cloud temporary-credentials helper."""
import unittest
from unittest.mock import patch
from urllib import parse

import responses
from werkzeug.exceptions import Unauthorized, Forbidden, ServiceUnavailable

from api.endpoints.members import get_edc_credentials

ENDPOINT = 'https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials'
ENDPOINT_URI = parse.quote(ENDPOINT, safe='')
# Bypass the TLRU cache so each test exercises the helper body.
fetch = get_edc_credentials.__wrapped__


@patch('api.endpoints.members.get_urs_token', return_value='edl-token')
class TestGetEdcCredentials(unittest.TestCase):

    @responses.activate
    def test_success_returns_credentials(self, _):
        creds = {'accessKeyId': 'a', 'secretAccessKey': 'b', 'sessionToken': 'c',
                 'expiration': '2026-11-03 00:00:00+00:00'}
        responses.add(responses.GET, ENDPOINT, json=creds, status=200)

        assert fetch(ENDPOINT_URI, 1) == creds
        assert responses.calls[0].request.headers['Authorization'] == 'Bearer edl-token'

    @responses.activate
    def test_no_stored_token_is_unauthorized(self, mock_token):
        mock_token.return_value = None

        with self.assertRaises(Unauthorized) as ctx:
            fetch(ENDPOINT_URI, 1)
        assert 'Sign in to the MAAP ADE' in ctx.exception.description
        assert len(responses.calls) == 0

    @responses.activate
    def test_redirect_to_edl_login_is_unauthorized(self, _):
        """The DAAC redirects to EDL instead of returning 401 for a rejected token."""
        responses.add(responses.GET, ENDPOINT, status=307, body='Temporary Redirect.',
                      headers={'Location': 'https://urs.earthdata.nasa.gov/oauth/authorize'})

        with self.assertRaises(Unauthorized) as ctx:
            fetch(ENDPOINT_URI, 1)
        assert 'rejected the stored token' in ctx.exception.description

    @responses.activate
    def test_daac_forbidden_passes_edl_reason_through(self, _):
        responses.add(responses.GET, ENDPOINT, status=403,
                      json={'error': 'eula', 'error_description': 'Please accept the LP DAAC EULA.'})

        with self.assertRaises(Forbidden) as ctx:
            fetch(ENDPOINT_URI, 1)
        assert 'Please accept the LP DAAC EULA.' in ctx.exception.description

    @responses.activate
    def test_daac_unauthorized_passes_edl_reason_through(self, _):
        responses.add(responses.GET, ENDPOINT, status=401, body='token expired')

        with self.assertRaises(Unauthorized) as ctx:
            fetch(ENDPOINT_URI, 1)
        assert 'token expired' in ctx.exception.description

    @responses.activate
    def test_other_errors_remain_service_unavailable(self, _):
        responses.add(responses.GET, ENDPOINT, status=400, body='bad request')
        with self.assertRaises(ServiceUnavailable):
            fetch(ENDPOINT_URI, 1)

        responses.add(responses.GET, ENDPOINT, status=200, body='<html>not json</html>')
        with self.assertRaises(ServiceUnavailable):
            fetch(ENDPOINT_URI, 2)


if __name__ == '__main__':
    unittest.main()
