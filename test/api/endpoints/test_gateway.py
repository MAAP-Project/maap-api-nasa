import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.personal_access_token import PersonalAccessToken
from api.models.esa_token_meta import EsaTokenMeta
from api.models.role import Role


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
            db.session.query(EsaTokenMeta).delete()
            db.session.commit()
            yield client
            db.session.query(PersonalAccessToken).delete()
            db.session.query(EsaTokenMeta).delete()
            db.session.commit()
            db.session.remove()


ADMIN_HEADERS = {
    "X-MAAP-API-Key": "test-admin-key",
    "X-MAAP-User-Identifier": "user@esa.int",
    "X-MAAP-User-Origin": "https://esa-oidc.example.org",
    "Content-Type": "application/json",
}


def _ensure_test_member(email="user@esa.int"):
    """Create a test member in the DB if one doesn't already exist."""
    member = db.session.query(Member).filter_by(email=email).first()
    if member is None:
        # Ensure the guest role exists
        role = db.session.query(Role).filter_by(id=Role.ROLE_GUEST).first()
        if role is None:
            role = Role(id=Role.ROLE_GUEST, role_name="guest")
            db.session.add(role)
            db.session.commit()

        member = Member(
            username=email.split("@")[0],
            email=email,
            first_name="Test",
            last_name="User",
            status="active",
            role_id=Role.ROLE_GUEST,
            creation_date=datetime.now(timezone.utc),
        )
        db.session.add(member)
        db.session.commit()
    return member


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

    @patch("api.endpoints.gateway.settings")
    def test_create_token_with_expires_in_zero_never_expires(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "permanent", "expires_in": 0}),
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["expires_at"] is None

    @patch("api.endpoints.gateway.settings")
    def test_create_token_with_negative_expires_in_rejected(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "bad", "expires_in": -1}),
        )
        assert resp.status_code == 400

    @patch("api.endpoints.gateway.settings")
    def test_create_token_without_expires_in_uses_default(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        resp = client.post(
            "/api/gateway/members/tokens",
            headers=ADMIN_HEADERS,
            data=json.dumps({"token_name": "default-expiry"}),
        )
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["expires_at"] is not None


class TestAdminListTokens:
    """Tests for GET /api/gateway/members/tokens (admin endpoint)."""

    @patch("api.endpoints.gateway.settings")
    def test_list_tokens_nonexistent_user_returns_404(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        headers = {
            "X-MAAP-API-Key": "test-admin-key",
            "X-MAAP-User-Identifier": "nobody@example.com",
            "X-MAAP-User-Origin": "https://esa-oidc.example.org",
        }
        resp = client.get("/api/gateway/members/tokens", headers=headers)
        assert resp.status_code == 404

    @patch("api.endpoints.gateway.settings")
    def test_list_tokens_empty(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        _ensure_test_member("user@esa.int")

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

        _ensure_test_member("user@esa.int")

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


class TestAdminIdentifierResolution:
    """Partner platforms (ESA) send the JWT `sub` as the user identifier, which
    for EDL-brokered users is a bare username, not an email. The admin
    endpoints must resolve it to the member's canonical email so tokens are
    stored and looked up on the same key the PAT auth path uses
    (validate_personal_access_token joins on member.email)."""

    # Username differs from the email local-part to prove real resolution,
    # not an incidental "username == email prefix" match.
    USERNAME = "test.user"
    EMAIL = "test.user@esa.int"

    def _member(self):
        member = db.session.query(Member).filter_by(email=self.EMAIL).first()
        if member is None:
            role = db.session.query(Role).filter_by(id=Role.ROLE_GUEST).first()
            if role is None:
                db.session.add(Role(id=Role.ROLE_GUEST, role_name="guest"))
                db.session.commit()
            member = Member(
                username=self.USERNAME,
                email=self.EMAIL,
                first_name="Test",
                last_name="User",
                status="active",
                role_id=Role.ROLE_GUEST,
                creation_date=datetime.now(timezone.utc),
            )
            db.session.add(member)
            db.session.commit()
        return member

    def _headers(self, identifier):
        return {
            "X-MAAP-API-Key": "test-admin-key",
            "X-MAAP-User-Identifier": identifier,
            "X-MAAP-User-Origin": "http://eoiam-idp.eo.esa.int",
            "Content-Type": "application/json",
        }

    @patch("api.endpoints.gateway.settings")
    def test_create_by_username_stores_under_email(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"
        self._member()

        # ESA sends the username (the `sub` claim).
        resp = client.post(
            "/api/gateway/members/tokens",
            headers=self._headers(self.USERNAME),
            data=json.dumps({"token_name": "esa-managed"}),
        )
        assert resp.status_code == 201

        # The token must be persisted keyed on the member's email, or the PAT
        # auth path (email join) could never authenticate it.
        stored = (
            db.session.query(PersonalAccessToken)
            .filter_by(token_name="esa-managed")
            .first()
        )
        assert stored is not None
        assert stored.user_identifier == self.EMAIL

    @patch("api.endpoints.gateway.settings")
    def test_list_by_username_resolves_to_member(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"
        self._member()

        # A token stored the canonical way (under email).
        db.session.add(
            PersonalAccessToken(
                user_identifier=self.EMAIL,
                user_origin="http://eoiam-idp.eo.esa.int",
                token_name="pre-existing",
                token_hash="hash",
            )
        )
        db.session.commit()

        # Listing by username must resolve to the member (not 404) and return it.
        resp = client.get(
            "/api/gateway/members/tokens",
            headers={k: v for k, v in self._headers(self.USERNAME).items() if k != "Content-Type"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["token_name"] == "pre-existing"

    @patch("api.endpoints.gateway.settings")
    def test_email_identifier_still_works(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"
        self._member()

        # The pre-existing EOIAM behavior (identifier already an email) is
        # unchanged: resolves by email, stores under email.
        resp = client.post(
            "/api/gateway/members/tokens",
            headers=self._headers(self.EMAIL),
            data=json.dumps({"token_name": "email-managed"}),
        )
        assert resp.status_code == 201
        stored = (
            db.session.query(PersonalAccessToken)
            .filter_by(token_name="email-managed")
            .first()
        )
        assert stored is not None
        assert stored.user_identifier == self.EMAIL

    @patch("api.endpoints.gateway.settings")
    def test_list_unknown_identifier_still_404(self, mock_settings, client):
        mock_settings.NASA_ADMIN_API_KEY = "test-admin-key"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_CAS_OIDC_ORIGIN = "https://auth.maap-project.org/cas/oidc"

        # No member by that username or email → still a clean 404, not a match.
        resp = client.get(
            "/api/gateway/members/tokens",
            headers={k: v for k, v in self._headers("no.such.user").items() if k != "Content-Type"},
        )
        assert resp.status_code == 404


class TestESATokenCreatedAt:
    """ESA doesn't return a token creation date, so we record one locally
    (EsaTokenMeta) purely for UI consistency with NASA tokens."""

    NASA_ORIGIN = "https://auth.maap-project.org/cas/oidc"
    ESA_ORIGIN = "http://eoiam-idp.eo.esa.int"

    def _headers(self, origin):
        return {
            "cpticket": "jwt:fake-token",
            "Content-Type": "application/json",
            "X-MAAP-User-Origin": origin,
        }

    def _configure(self, mock_settings):
        mock_settings.NASA_CAS_OIDC_ORIGIN = self.NASA_ORIGIN
        mock_settings.ESA_OIDC_ORIGIN = self.ESA_ORIGIN
        mock_settings.ESA_GATEWAY_BASE_URL = "https://esa-gateway.example.org"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_ADMIN_API_KEY = "nasa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.endpoints.gateway._is_jwt_auth", return_value=True)
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_create_records_local_created_at(
        self, mock_settings, mock_verify, mock_jwt, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")
        # ESA's response omits created_at.
        mock_esa_cls.return_value.create_token.return_value = {
            "token": "esa-token-value",
            "token_id": "esa-abc",
            "token_name": "my-esa",
            "expires_at": None,
        }

        resp = client.post(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.ESA_ORIGIN),
            data=json.dumps({"token_name": "my-esa"}),
        )
        assert resp.status_code == 201

        # The create response is backfilled with our timestamp...
        data = json.loads(resp.data)
        assert data["created_at"] is not None

        # ...and a metadata row is persisted keyed by ESA's token_id.
        meta = db.session.query(EsaTokenMeta).filter_by(token_id="esa-abc").first()
        assert meta is not None
        assert meta.user_identifier == "user@nasa.gov"

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_list_backfills_created_at_from_metadata(
        self, mock_settings, mock_verify, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")

        recorded = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        db.session.add(
            EsaTokenMeta(token_id="esa-xyz", user_identifier="user@nasa.gov", created_at=recorded)
        )
        db.session.commit()

        # ESA lists the token but omits created_at.
        mock_esa_cls.return_value.list_tokens.return_value = [
            {"token_id": "esa-xyz", "token_name": "tok", "expires_at": None}
        ]

        resp = client.get(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.NASA_ORIGIN),
        )
        assert resp.status_code == 200
        esa_entry = next(t for t in json.loads(resp.data) if t["user_origin"] == self.ESA_ORIGIN)
        assert esa_entry["created_at"] == recorded.isoformat()

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_list_prefers_esa_created_at_when_present(
        self, mock_settings, mock_verify, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")

        # Local record exists, but if ESA ever sends its own created_at it wins.
        db.session.add(
            EsaTokenMeta(
                token_id="esa-xyz",
                user_identifier="user@nasa.gov",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        db.session.commit()
        mock_esa_cls.return_value.list_tokens.return_value = [
            {"token_id": "esa-xyz", "token_name": "tok", "expires_at": None,
             "created_at": "2026-07-22T09:00:00+00:00"}
        ]

        resp = client.get(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.NASA_ORIGIN),
        )
        esa_entry = next(t for t in json.loads(resp.data) if t["user_origin"] == self.ESA_ORIGIN)
        assert esa_entry["created_at"] == "2026-07-22T09:00:00+00:00"

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.endpoints.gateway._is_jwt_auth", return_value=True)
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_revoke_cleans_up_metadata(
        self, mock_settings, mock_verify, mock_jwt, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")
        db.session.add(
            EsaTokenMeta(token_id="esa-gone", user_identifier="user@nasa.gov")
        )
        db.session.commit()

        resp = client.delete(
            "/api/gateway/members/self/tokens/esa-gone",
            headers=self._headers(self.ESA_ORIGIN),
        )
        assert resp.status_code == 204
        assert db.session.query(EsaTokenMeta).filter_by(token_id="esa-gone").first() is None


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


class TestSelfServiceESADelegation:
    """Tests for self-service token endpoints routing ESA-targeted requests to
    ESA's gateway based on the X-MAAP-User-Origin header."""

    NASA_ORIGIN = "https://auth.maap-project.org/cas/oidc"
    ESA_ORIGIN = "http://eoiam-idp.eo.esa.int"

    def _headers(self, origin):
        return {
            "cpticket": "jwt:fake-token",
            "Content-Type": "application/json",
            "X-MAAP-User-Origin": origin,
        }

    def _configure(self, mock_settings):
        mock_settings.NASA_CAS_OIDC_ORIGIN = self.NASA_ORIGIN
        mock_settings.ESA_OIDC_ORIGIN = self.ESA_ORIGIN
        mock_settings.ESA_GATEWAY_BASE_URL = "https://esa-gateway.example.org"
        mock_settings.ESA_ADMIN_API_KEY = "esa-admin-key"
        mock_settings.NASA_ADMIN_API_KEY = "nasa-admin-key"
        mock_settings.TOKEN_DEFAULT_EXPIRY_SECONDS = 86400

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.endpoints.gateway._is_jwt_auth", return_value=True)
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_self_create_esa_delegates_to_esa_gateway(
        self, mock_settings, mock_verify, mock_jwt, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")
        mock_esa_cls.return_value.create_token.return_value = {
            "token": "esa-token-value",
            "token_id": "esa-token-id",
            "token_name": "my-esa",
            "expires_at": None,
        }

        resp = client.post(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.ESA_ORIGIN),
            data=json.dumps({"token_name": "my-esa", "expires_in": 3600}),
        )

        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["token"] == "esa-token-value"
        mock_esa_cls.return_value.create_token.assert_called_once_with(
            "user@nasa.gov", token_name="my-esa", expires_in=3600
        )

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.endpoints.gateway._is_jwt_auth", return_value=True)
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_self_create_nasa_stays_local(
        self, mock_settings, mock_verify, mock_jwt, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")

        resp = client.post(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.NASA_ORIGIN),
            data=json.dumps({"token_name": "my-nasa"}),
        )

        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["token_name"] == "my-nasa"
        assert "token" in data
        mock_esa_cls.return_value.create_token.assert_not_called()
        # Token was persisted locally with the NASA origin.
        stored = (
            db.session.query(PersonalAccessToken)
            .filter_by(user_identifier="user@nasa.gov")
            .first()
        )
        assert stored is not None
        assert stored.user_origin == self.NASA_ORIGIN

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_self_list_merges_nasa_and_esa(
        self, mock_settings, mock_verify, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")
        mock_esa_cls.return_value.list_tokens.return_value = [
            {"token_id": "esa-1", "token_name": "esa-tok", "expires_at": None}
        ]

        # Seed a local NASA token.
        db.session.add(
            PersonalAccessToken(
                user_identifier="user@nasa.gov",
                user_origin=self.NASA_ORIGIN,
                token_name="nasa-tok",
                token_hash="hash",
            )
        )
        db.session.commit()

        resp = client.get(
            "/api/gateway/members/self/tokens",
            headers=self._headers(self.NASA_ORIGIN),
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        origins = {t["user_origin"]: t for t in data}
        assert self.NASA_ORIGIN in origins
        assert self.ESA_ORIGIN in origins
        assert origins[self.ESA_ORIGIN]["token_id"] == "esa-1"

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_self_list_translates_page_to_esa_zero_based(
        self, mock_settings, mock_verify, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")
        mock_esa_cls.return_value.list_tokens.return_value = []

        # Our API is 1-based; ESA's gateway is 0-based. The first page (page=1)
        # must reach ESA as page=0, or the user's tokens are never returned.
        resp = client.get(
            "/api/gateway/members/self/tokens?page=1&size=50",
            headers=self._headers(self.NASA_ORIGIN),
        )

        assert resp.status_code == 200
        mock_esa_cls.return_value.list_tokens.assert_called_once_with(
            "user@nasa.gov", page=0, size=50
        )

    @patch("api.endpoints.gateway.ESATokenClient")
    @patch("api.endpoints.gateway.get_authorized_user")
    @patch("api.endpoints.gateway._is_jwt_auth", return_value=True)
    @patch("api.auth.security.verify_jwt_token", return_value={"sub": "x"})
    @patch("api.endpoints.gateway.settings")
    def test_self_revoke_esa_delegates(
        self, mock_settings, mock_verify, mock_jwt, mock_user, mock_esa_cls, client
    ):
        self._configure(mock_settings)
        mock_user.return_value = MagicMock(email="user@nasa.gov")

        resp = client.delete(
            "/api/gateway/members/self/tokens/esa-token-id",
            headers=self._headers(self.ESA_ORIGIN),
        )

        assert resp.status_code == 204
        mock_esa_cls.return_value.revoke_token.assert_called_once_with(
            "user@nasa.gov", "esa-token-id"
        )
