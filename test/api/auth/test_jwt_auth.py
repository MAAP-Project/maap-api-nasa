"""Tests for Keycloak-JWT authentication: member auto-create on first touch
(the CAS-era registration replacement) and role enforcement on the JWT paths
of login_required (proxy-ticket/cpticket `jwt:` and Authorization Bearer)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from api import constants
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.pre_approved import PreApproved
from api.models.role import Role
from api.auth.cas_auth import start_member_session_jwt


NEW_USER_CLAIMS = {
    "preferred_username": "newuser",
    "email": "new.user@example.org",
    "given_name": "New",
    "family_name": "User",
    "organization": "NASA",
}

COMPUTE_USER_CLAIMS = {
    "preferred_username": "computeuser",
    "email": "compute.user@example.org",
    "given_name": "Compute",
    "family_name": "User",
    "roles": ["CPU:S"],
}


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
    db.session.query(MemberSession).delete()
    db.session.query(PreApproved).delete()
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


# ---------------------------------------------------------------------------
# Auto-create on first authenticated touch (start_member_session_jwt)
# ---------------------------------------------------------------------------

@patch("api.auth.cas_auth.refresh_urs_token")
@patch("api.utils.member_util.notify_new_member")
class TestJwtMemberAutoCreate:

    def test_new_user_auto_created_as_suspended_guest(self, mock_notify, _refresh, client):
        member = start_member_session_jwt(NEW_USER_CLAIMS, "jwt:token-new-1")

        assert member is not None
        assert member.username == "newuser"
        assert member.role_id == Role.ROLE_GUEST
        assert member.status == constants.STATUS_SUSPENDED
        assert member.email == "new.user@example.org"
        assert member.organization == "NASA"
        # Auto-create is SILENT: new-user notifications are the Hub
        # environment's responsibility — no API emails (guards against
        # double notifications).
        mock_notify.assert_not_called()

    def test_pre_approved_email_auto_created_active(self, mock_notify, _refresh, client):
        db.session.add(PreApproved(email="new.user@example.org",
                                   creation_date=datetime.utcnow()))
        db.session.commit()

        member = start_member_session_jwt(NEW_USER_CLAIMS, "jwt:token-new-2")

        assert member.status == constants.STATUS_ACTIVE
        assert member.role_id == Role.ROLE_GUEST
        mock_notify.assert_not_called()

    def test_compute_role_auto_created_active_member(self, mock_notify, _refresh, client):
        member = start_member_session_jwt(COMPUTE_USER_CLAIMS, "jwt:token-compute")

        # Existing compute-role behavior preserved: MEMBER + active, no
        # registration notifications.
        assert member.role_id == Role.ROLE_MEMBER
        assert member.status == constants.STATUS_ACTIVE
        mock_notify.assert_not_called()

    def test_existing_member_not_duplicated(self, mock_notify, _refresh, client):
        _create_member("newuser", Role.ROLE_MEMBER)

        member = start_member_session_jwt(NEW_USER_CLAIMS, "jwt:token-existing")

        assert member.role_id == Role.ROLE_MEMBER
        assert db.session.query(Member).filter_by(username="newuser").count() == 1
        mock_notify.assert_not_called()

    def test_second_touch_no_duplicate(self, mock_notify, _refresh, client):
        first = start_member_session_jwt(NEW_USER_CLAIMS, "jwt:token-touch-1")
        second = start_member_session_jwt(NEW_USER_CLAIMS, "jwt:token-touch-2")

        assert first.id == second.id
        assert db.session.query(Member).filter_by(username="newuser").count() == 1
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# Role enforcement on the JWT branches of login_required
# ---------------------------------------------------------------------------

# DB-only ADMIN-gated endpoint (job-queues would call out to Mozart/HySDS).
ADMIN_ENDPOINT = "/api/admin/pre-approved"
SELF_ENDPOINT = "/api/members/self"


def _claims_for(username):
    return {"preferred_username": username,
            "email": f"{username}@example.org",
            "given_name": "Test",
            "family_name": "User"}


@patch("api.auth.cas_auth.refresh_urs_token")
@patch("api.utils.member_util.notify_new_member")
@patch("api.auth.security.verify_jwt_token")
class TestJwtRoleEnforcement:

    def test_admin_endpoint_rejects_auto_created_guest_cpticket(
            self, mock_verify, _notify, _refresh, client):
        mock_verify.return_value = _claims_for("brandnew")

        resp = client.get(ADMIN_ENDPOINT, headers={"cpticket": "jwt:some-token"})

        assert resp.status_code == 401
        # The rejected caller was still registered (the CAS-era funnel).
        member = db.session.query(Member).filter_by(username="brandnew").first()
        assert member is not None
        assert member.status == constants.STATUS_SUSPENDED

    def test_admin_endpoint_rejects_guest_member_proxy_ticket(
            self, mock_verify, _notify, _refresh, client):
        _create_member("guestuser", Role.ROLE_GUEST)
        mock_verify.return_value = _claims_for("guestuser")

        resp = client.get(ADMIN_ENDPOINT, headers={"proxy-ticket": "jwt:some-token"})
        assert resp.status_code == 401

    def test_admin_endpoint_allows_admin_member_cpticket(
            self, mock_verify, _notify, _refresh, client):
        _create_member("adminuser", Role.ROLE_ADMIN)
        mock_verify.return_value = _claims_for("adminuser")

        resp = client.get(ADMIN_ENDPOINT, headers={"cpticket": "jwt:some-token"})
        assert resp.status_code == 200

    def test_admin_endpoint_rejects_guest_member_bearer(
            self, mock_verify, _notify, _refresh, client):
        _create_member("guestuser", Role.ROLE_GUEST)
        mock_verify.return_value = _claims_for("guestuser")

        resp = client.get(ADMIN_ENDPOINT, headers={"Authorization": "Bearer some-token"})
        assert resp.status_code == 401

    def test_admin_endpoint_allows_admin_member_bearer(
            self, mock_verify, _notify, _refresh, client):
        _create_member("adminuser", Role.ROLE_ADMIN)
        mock_verify.return_value = _claims_for("adminuser")

        resp = client.get(ADMIN_ENDPOINT, headers={"Authorization": "Bearer some-token"})
        assert resp.status_code == 200

    def test_guest_endpoint_serves_new_user_with_pending_status(
            self, mock_verify, _notify, _refresh, client):
        mock_verify.return_value = _claims_for("pendinguser")

        resp = client.get(SELF_ENDPOINT, headers={"proxy-ticket": "jwt:some-token"})

        # First touch auto-creates the member and members/self renders the
        # pending (suspended) record instead of crashing.
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["username"] == "pendinguser"
        assert body["status"] == constants.STATUS_SUSPENDED

    def test_admin_status_change_endpoint_requires_admin(
            self, mock_verify, _notify, _refresh, client):
        _create_member("guestuser", Role.ROLE_GUEST)
        target = _create_member("targetuser", Role.ROLE_GUEST,
                                status=constants.STATUS_SUSPENDED)
        mock_verify.return_value = _claims_for("guestuser")

        resp = client.post(f"/api/members/{target.username}/status",
                           headers={"cpticket": "jwt:some-token"},
                           json={"status": constants.STATUS_ACTIVE})
        assert resp.status_code == 401
