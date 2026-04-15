import json
import pytest
from unittest.mock import patch, MagicMock
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.personal_access_token import PersonalAccessToken


@pytest.fixture(scope="module")
def test_app():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    return app


@pytest.fixture(scope="function")
def client(test_app):
    with test_app.test_client() as client:
        with test_app.app_context():
            initialize_sql(db.engine)
            db.create_all()
            # Clean up any leftover tokens from previous test runs
            db.session.query(PersonalAccessToken).delete()
            db.session.commit()
            yield client
            db.session.query(PersonalAccessToken).delete()
            db.session.commit()
            db.session.remove()


ADMIN_HEADERS = {
    "X-MAAP-API-Key": "test-admin-key",
    "X-MAAP-User-Identifier": "user@esa.int",
    "X-MAAP-User-Origin": "https://esa-oidc.example.org",
    "Content-Type": "application/json",
}


class TestAdminCreateToken:
    """Tests for POST /api/gateway/members/tokens (admin endpoint)."""

    @patch("api.endpoints.gateway.settings")
    def test_create_token_success(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "my-esa-token"}),
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert "token" in data
        assert "token_id" in data
        assert data["token_name"] == "my-esa-token"
        assert data["expires_at"] is not None

    @patch("api.endpoints.gateway.settings")
    def test_create_token_invalid_api_key(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "correct-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-key"

        headers = {**ADMIN_HEADERS, "X-MAAP-API-Key": "wrong-key"}
        resp = client.post(
            "/api/gateway/members/tokens",
            headers=headers,
            data=json.dumps({"token_name": "test"}),
        )
        assert resp.status_code == 403

    @patch("api.endpoints.gateway.settings")
    def test_create_token_missing_user_identifier(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"

        headers = {k: v for k, v in ADMIN_HEADERS.items() if k != "X-MAAP-User-Identifier"}
        resp = client.post(
            "/api/gateway/members/tokens",
            headers=headers,
            data=json.dumps({"token_name": "test"}),
        )
        assert resp.status_code == 403

    @patch("api.endpoints.gateway.settings")
    def test_create_token_with_custom_expiry(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "short-lived", "expires_in": 3600}),
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["expires_at"] is not None


class TestAdminListTokens:
    """Tests for GET /api/gateway/members/tokens (admin endpoint)."""

    @patch("api.endpoints.gateway.settings")
    def test_list_tokens_empty(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.get(
            "/api/gateway/members/tokens",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data == []

    @patch("api.endpoints.gateway.settings")
    def test_list_tokens_after_create(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        # Create a token
        client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "list-test"}),
        )

        # List tokens
        resp = client.get(
            "/api/gateway/members/tokens",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["token_name"] == "list-test"
        assert "token" not in data[0]  # token value should not be in list response


class TestAdminRevokeToken:
    """Tests for DELETE /api/gateway/members/tokens/<token_id> (admin endpoint)."""

    @patch("api.endpoints.gateway.settings")
    def test_revoke_token_success(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        # Create a token
        create_resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "to-revoke"}),
        )
        token_id = json.loads(create_resp.data)["token_id"]

        # Revoke it
        resp = client.delete(
            f"/api/gateway/members/tokens/{token_id}",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )
        assert resp.status_code == 204

    @patch("api.endpoints.gateway.settings")
    def test_revoke_nonexistent_token(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.delete(
            "/api/gateway/members/tokens/nonexistent-id",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )
        assert resp.status_code == 404

    @patch("api.endpoints.gateway.settings")
    def test_revoke_already_revoked_token(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        # Create and revoke
        create_resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "double-revoke"}),
        )
        token_id = json.loads(create_resp.data)["token_id"]

        client.delete(
            f"/api/gateway/members/tokens/{token_id}",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )

        # Try to revoke again
        resp = client.delete(
            f"/api/gateway/members/tokens/{token_id}",
            headers={k: v for k, v in ADMIN_HEADERS.items() if k != "Content-Type"},
        )
        assert resp.status_code == 404


class TestESAClient:
    """Tests for the ESA integration client."""

    @patch("api.utils.esa_client.requests")
    def test_create_token(self, mock_requests):
        from api.utils.esa_client import ESATokenClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "esa-token-value",
            "token_id": "esa-token-id",
            "token_name": "test",
            "expires_at": "2026-04-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_response

        client = ESATokenClient(
            base_url="https://esa-gateway.example.org",
            admin_api_key="nasa-admin-key",
            nasa_oidc_origin="https://auth.maap-project.org/cas/oidc",
        )

        result = client.create_token("user@nasa.gov", token_name="test", expires_in=3600)

        assert result["token"] == "esa-token-value"
        assert result["token_id"] == "esa-token-id"

        call_args = mock_requests.post.call_args
        assert call_args[1]["headers"]["X-MAAP-API-Key"] == "nasa-admin-key"
        assert call_args[1]["headers"]["X-MAAP-User-Identifier"] == "user@nasa.gov"

    @patch("api.utils.esa_client.requests")
    def test_list_tokens(self, mock_requests):
        from api.utils.esa_client import ESATokenClient

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"token_id": "t1", "token_name": "tok1", "expires_at": None}
        ]
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response

        client = ESATokenClient(
            base_url="https://esa-gateway.example.org",
            admin_api_key="nasa-admin-key",
            nasa_oidc_origin="https://auth.maap-project.org/cas/oidc",
        )

        result = client.list_tokens("user@nasa.gov")
        assert len(result) == 1
        assert result[0]["token_id"] == "t1"

    @patch("api.utils.esa_client.requests")
    def test_revoke_token(self, mock_requests):
        from api.utils.esa_client import ESATokenClient

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_requests.delete.return_value = mock_response

        client = ESATokenClient(
            base_url="https://esa-gateway.example.org",
            admin_api_key="nasa-admin-key",
            nasa_oidc_origin="https://auth.maap-project.org/cas/oidc",
        )

        client.revoke_token("user@nasa.gov", "token-id-123")

        call_args = mock_requests.delete.call_args
        assert "token-id-123" in call_args[0][0]
