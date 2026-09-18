"""Tests for the system-issued DPS job token returned as ``session_key`` by
``GET /members/<username>`` when the request carries the dps-token header."""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api import constants
from api import settings
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.personal_access_token import PersonalAccessToken
from api.models.role import Role
from api.auth.security import validate_personal_access_token
from api.utils.dps_token_util import get_or_create_dps_token, DPS_TOKEN_NAME
from api.utils.security_utils import ExternalServiceError


DPS_MACHINE_TOKEN = "test-dps-machine-token"
SELF_ENDPOINT = "/api/members/self"


@pytest.fixture(scope="module")
def test_app():
    app.config['TESTING'] = True
    return app


@pytest.fixture(scope="function")
def client(test_app):
    with test_app.test_client() as client:
        with test_app.app_context():
            initialize_sql(db.engine)
            db.create_all()
            _clean()
            _ensure_roles()
            with patch.object(settings, "DPS_MACHINE_TOKEN", DPS_MACHINE_TOKEN):
                yield client
            _clean()
            db.session.remove()


def _clean():
    db.session.query(PersonalAccessToken).delete()
    db.session.query(MemberSession).delete()
    db.session.query(Member).delete()
    db.session.commit()


def _ensure_roles():
    for role_id, name in [(Role.ROLE_GUEST, "guest"),
                          (Role.ROLE_MEMBER, "member"),
                          (Role.ROLE_ADMIN, "admin")]:
        if db.session.query(Role).filter_by(id=role_id).first() is None:
            db.session.add(Role(id=role_id, role_name=name))
    db.session.commit()


def _create_member(username, role_id=Role.ROLE_MEMBER, status=constants.STATUS_ACTIVE):
    member = Member(username=username,
                    email=f"{username}@example.org",
                    first_name="Test",
                    last_name="User",
                    role_id=role_id,
                    status=status,
                    creation_date=datetime.utcnow())
    db.session.add(member)
    db.session.commit()
    return member


def _system_tokens(email):
    return db.session.query(PersonalAccessToken) \
        .filter_by(user_identifier=email) \
        .filter(PersonalAccessToken.token_encrypted.isnot(None)) \
        .order_by(PersonalAccessToken.id).all()


def _dps_get(client, username):
    return client.get(f"/api/members/{username}", headers={"dps-token": DPS_MACHINE_TOKEN})


def _cas_down(*_args, **_kwargs):
    raise ExternalServiceError("CAS server connection failed")


class TestDpsTokenEndpoint:

    def test_dps_request_returns_token_that_authenticates_as_user(self, client):
        email = _create_member("jobuser").email

        resp = _dps_get(client, "jobuser")
        assert resp.status_code == 200
        token = resp.get_json()["session_key"]
        assert token

        # The DPS job then presents it as MAAP_PGT (proxy-ticket header) —
        # which must work with CAS unreachable.
        with patch("api.auth.cas_auth.validate_cas_request", side_effect=_cas_down):
            job_resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": token})
        assert job_resp.status_code == 200
        assert job_resp.get_json()["username"] == "jobuser"

        tokens = _system_tokens(email)
        assert len(tokens) == 1
        assert tokens[0].token_name == DPS_TOKEN_NAME
        assert tokens[0].token_hash == hashlib.sha256(token.encode()).hexdigest()

    def test_repeated_dps_requests_reuse_the_same_token(self, client):
        email = _create_member("jobuser").email

        first = _dps_get(client, "jobuser").get_json()["session_key"]
        second = _dps_get(client, "jobuser").get_json()["session_key"]
        third = _dps_get(client, "jobuser").get_json()["session_key"]

        assert first == second == third
        assert len(_system_tokens(email)) == 1

    def test_self_request_still_returns_latest_session_key(self, client):
        """The non-DPS branch (user reading their own record) is unchanged."""
        member = _create_member("selfuser")
        email = member.email
        db.session.add(MemberSession(member_id=member.id, session_key="PGT-1-old",
                                     creation_date=datetime.utcnow()))
        db.session.add(MemberSession(member_id=member.id, session_key="PGT-2-latest",
                                     creation_date=datetime.utcnow()))
        db.session.commit()

        with patch("api.auth.security.validate_proxy") as mock_proxy:
            session = db.session.query(MemberSession).filter_by(session_key="PGT-2-latest").first()
            mock_proxy.return_value = session
            resp = client.get("/api/members/selfuser", headers={"proxy-ticket": "PGT-2-latest"})

        assert resp.status_code == 200
        assert resp.get_json()["session_key"] == "PGT-2-latest"
        assert _system_tokens(email) == []

    def test_dps_request_for_unknown_member_is_404(self, client):
        resp = _dps_get(client, "nobody")
        assert resp.status_code == 404


class TestDpsTokenRollover:

    def test_token_inside_renewal_window_is_replaced_but_kept(self, client):
        member = _create_member("jobuser")
        first = get_or_create_dps_token(member.email)

        # Age the token so that less than the renewal threshold remains.
        tok = _system_tokens(member.email)[0]
        tok.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.DPS_TOKEN_RENEWAL_THRESHOLD_SECONDS - 60)
        db.session.commit()

        second = get_or_create_dps_token(member.email)

        assert second != first
        tokens = _system_tokens(member.email)
        # Old token is left for running jobs; new token is the one handed out.
        assert len(tokens) == 2
        assert validate_personal_access_token(first) is not None
        assert validate_personal_access_token(second) is not None

        # A further request reuses the new token rather than minting again.
        assert get_or_create_dps_token(member.email) == second
        assert len(_system_tokens(member.email)) == 2

    def test_expired_and_revoked_system_tokens_are_pruned(self, client):
        member = _create_member("jobuser")
        get_or_create_dps_token(member.email)
        tok = _system_tokens(member.email)[0]
        tok.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

        get_or_create_dps_token(member.email)
        tok = _system_tokens(member.email)[-1]
        tok.revoked_at = datetime.now(timezone.utc)
        db.session.commit()

        fresh = get_or_create_dps_token(member.email)

        tokens = _system_tokens(member.email)
        assert len(tokens) == 1
        assert tokens[0].token_hash == hashlib.sha256(fresh.encode()).hexdigest()
        assert validate_personal_access_token(fresh) is not None

    def test_user_created_tokens_are_untouched(self, client):
        member = _create_member("jobuser")
        user_pat = PersonalAccessToken(
            user_identifier=member.email,
            user_origin=settings.NASA_CAS_OIDC_ORIGIN,
            token_name="my laptop",
            token_hash="hash-of-user-token",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # expired
        )
        db.session.add(user_pat)
        db.session.commit()

        get_or_create_dps_token(member.email)

        remaining = db.session.query(PersonalAccessToken) \
            .filter_by(user_identifier=member.email).all()
        names = sorted(t.token_name for t in remaining)
        assert names == sorted(["my laptop", DPS_TOKEN_NAME])

    def test_token_expiry_matches_setting(self, client):
        member = _create_member("jobuser")
        before = datetime.now(timezone.utc)
        get_or_create_dps_token(member.email)
        tok = _system_tokens(member.email)[0]
        expected = before + timedelta(seconds=settings.DPS_TOKEN_EXPIRY_SECONDS)
        assert abs((tok.expires_at - expected).total_seconds()) < 5
