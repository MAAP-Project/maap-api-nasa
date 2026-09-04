"""Tests for personal access token (PAT) authentication.

A PAT sent in the proxy-ticket/cpticket header (which is how maap-py sends
MAAP_PGT) must authenticate without contacting the CAS server: the PAT lookup
runs before the CAS proxy-ticket validation, so an unreachable CAS server must
not turn every PAT request into a 503."""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api import constants
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.personal_access_token import PersonalAccessToken
from api.models.role import Role
from api.auth.cas_auth import validate_proxy
from api.utils.security_utils import ExternalServiceError


ADMIN_ENDPOINT = "/api/admin/pre-approved"
SELF_ENDPOINT = "/api/members/self"
RAW_TOKEN = "pTIObTNROz04kg1WJsDCKa5GB1mD-shJZH_fMZiMmvo"


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


def _create_member(username, role_id, status=constants.STATUS_ACTIVE):
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


def _create_pat(member, raw_token=RAW_TOKEN, expires_at=None):
    pat = PersonalAccessToken(
        user_identifier=member.email,
        user_origin="https://auth.maap-project.org/cas/oidc",
        token_name="test",
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    )
    db.session.add(pat)
    db.session.commit()
    return pat


def _cas_down(*_args, **_kwargs):
    raise ExternalServiceError(
        "CAS server connection failed or timed out: <urlopen error [Errno 111] Connection refused>")


# ---------------------------------------------------------------------------
# PAT authentication must not depend on CAS
# ---------------------------------------------------------------------------

@patch("api.auth.cas_auth.validate_cas_request", side_effect=_cas_down)
class TestPatAuthWithCasUnreachable:

    def test_pat_in_proxy_ticket_header_authenticates(self, _cas, client):
        member = _create_member("patuser", Role.ROLE_MEMBER)
        _create_pat(member)

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        assert resp.status_code == 200
        assert resp.get_json()["username"] == "patuser"
        _cas.assert_not_called()

    def test_pat_in_cpticket_header_authenticates(self, _cas, client):
        member = _create_member("patuser", Role.ROLE_MEMBER)
        _create_pat(member)

        resp = client.get(SELF_ENDPOINT, headers={"cpticket": RAW_TOKEN})

        assert resp.status_code == 200
        assert resp.get_json()["username"] == "patuser"
        _cas.assert_not_called()

    def test_admin_endpoint_allows_admin_pat(self, _cas, client):
        member = _create_member("adminuser", Role.ROLE_ADMIN)
        _create_pat(member)

        resp = client.get(ADMIN_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        assert resp.status_code == 200
        _cas.assert_not_called()

    def test_admin_endpoint_rejects_guest_pat(self, _cas, client):
        member = _create_member("guestuser", Role.ROLE_GUEST)
        _create_pat(member)

        resp = client.get(ADMIN_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        assert resp.status_code == 401
        _cas.assert_not_called()

    def test_expired_pat_rejected_without_contacting_cas(self, _cas, client):
        member = _create_member("patuser", Role.ROLE_MEMBER)
        _create_pat(member, expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        # An opaque, non-CAS token that is not a live PAT is a plain 401;
        # there is nothing for the CAS server to validate.
        assert resp.status_code == 401
        _cas.assert_not_called()

    def test_revoked_pat_rejected(self, _cas, client):
        member = _create_member("patuser", Role.ROLE_MEMBER)
        pat = _create_pat(member)
        pat.revoked_at = datetime.now(timezone.utc)
        db.session.commit()

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        assert resp.status_code == 401

    def test_pat_for_inactive_member_rejected(self, _cas, client):
        member = _create_member("patuser", Role.ROLE_MEMBER, status=constants.STATUS_INACTIVE)
        _create_pat(member)

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": RAW_TOKEN})

        assert resp.status_code == 401

    def test_unknown_opaque_token_is_401_not_503(self, _cas, client):
        _create_member("patuser", Role.ROLE_MEMBER)

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": "not-a-real-token"})

        assert resp.status_code == 401
        _cas.assert_not_called()


# ---------------------------------------------------------------------------
# validate_proxy only contacts CAS for something that looks like a CAS ticket
# ---------------------------------------------------------------------------

class TestValidateProxyCasContact:

    @patch("api.auth.cas_auth.validate_cas_request", side_effect=_cas_down)
    def test_undecryptable_ticket_does_not_contact_cas(self, _cas, client):
        with app.test_request_context("/api/members/self"):
            assert validate_proxy(RAW_TOKEN) is None
        _cas.assert_not_called()

    @patch("api.auth.cas_auth.validate_cas_request", side_effect=_cas_down)
    def test_real_pgt_still_contacts_cas(self, _cas, client):
        with app.test_request_context("/api/members/self"):
            with pytest.raises(ExternalServiceError):
                validate_proxy("PGT-1-unknown-ticket")
        _cas.assert_called_once()
