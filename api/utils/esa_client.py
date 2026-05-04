import logging

import requests

import api.settings as settings

log = logging.getLogger(__name__)


class ESATokenClient:
    """Client for managing ESA MAAP tokens on behalf of NASA users.

    Calls ESA's admin gateway API to create, list, and revoke personal
    access tokens that allow NASA users to access ESA MAAP resources.
    """

    def __init__(
        self,
        base_url=None,
        admin_api_key=None,
        nasa_oidc_origin=None,
    ):
        self.base_url = (base_url or settings.ESA_GATEWAY_BASE_URL).rstrip("/")
        self.api_key = admin_api_key or settings.NASA_ADMIN_API_KEY
        self.origin = nasa_oidc_origin or settings.NASA_CAS_OIDC_ORIGIN
        self.tokens_url = f"{self.base_url}/esa-maap/api/v1.0/members/tokens"

    def _headers(self, user_identifier):
        return {
            "X-MAAP-API-Key": self.api_key,
            "X-MAAP-User-Identifier": user_identifier,
            "X-MAAP-User-Origin": self.origin,
            "Content-Type": "application/json",
        }

    def create_token(self, user_identifier, token_name=None, expires_in=None):
        """Create an ESA MAAP token for a NASA user.

        Args:
            user_identifier: The NASA user's email address.
            token_name: Human-readable name for the token.
            expires_in: Token expiry in seconds (optional).

        Returns:
            dict with token, token_id, token_name, expires_at on success.

        Raises:
            requests.HTTPError on failure.
        """
        body = {}
        if token_name:
            body["token_name"] = token_name
        if expires_in is not None:
            body["expires_in"] = expires_in

        resp = requests.post(
            self.tokens_url,
            json=body,
            headers=self._headers(user_identifier),
            timeout=settings.REQUESTS_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()

    def list_tokens(self, user_identifier, page=None, size=None):
        """List ESA MAAP tokens for a NASA user.

        Args:
            user_identifier: The NASA user's email address.
            page: Page number (optional).
            size: Page size (optional).

        Returns:
            list of token metadata dicts.

        Raises:
            requests.HTTPError on failure.
        """
        params = {}
        if page is not None:
            params["page"] = page
        if size is not None:
            params["size"] = size

        resp = requests.get(
            self.tokens_url,
            params=params,
            headers=self._headers(user_identifier),
            timeout=settings.REQUESTS_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()

    def revoke_token(self, user_identifier, token_id):
        """Revoke an ESA MAAP token for a NASA user.

        Args:
            user_identifier: The NASA user's email address.
            token_id: The ID of the token to revoke.

        Raises:
            requests.HTTPError on failure.
        """
        url = f"{self.tokens_url}/{token_id}"
        resp = requests.delete(
            url,
            headers=self._headers(user_identifier),
            timeout=settings.REQUESTS_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
