import logging
from datetime import datetime

from flask import current_app

from api import constants, settings
from api.maap_database import db
from api.models.member import Member
from api.models.pre_approved import PreApproved
from api.models.role import Role
from api.utils.email_util import (
    send_user_status_change_email,
    send_welcome_to_maap_active_user_email,
    send_welcome_to_maap_suspended_user_email,
)

log = logging.getLogger(__name__)


def determine_initial_status(email):
    """Initial status for a newly registered member: pre-approved emails
    activate immediately; everyone else starts suspended pending admin review.
    Mirrors the CAS-era registration flow (wildcard '*' prefix supported)."""
    if not email:
        return constants.STATUS_SUSPENDED

    pre_approved_email = db.session.query(PreApproved).filter(
        (PreApproved.email.like("*%") & PreApproved.email.like("%" + email[1:])) |
        (~PreApproved.email.like("*%") & PreApproved.email.like(email))
    ).first()

    return constants.STATUS_SUSPENDED if pre_approved_email is None else constants.STATUS_ACTIVE


def notify_new_member(member, base_url):
    """New-registration notifications: alert the admins, welcome the user.
    Notification failures must not break registration/authentication.

    No-op unless settings.MEMBER_EMAIL_NOTIFICATIONS_ENABLED — user
    communication is handled by the Hub environment for now."""
    if not settings.MEMBER_EMAIL_NOTIFICATIONS_ENABLED:
        return
    try:
        is_active = member.status == constants.STATUS_ACTIVE
        send_user_status_change_email(member, True, is_active, base_url)
        if member.email:
            if is_active:
                send_welcome_to_maap_active_user_email(member, base_url)
            else:
                send_welcome_to_maap_suspended_user_email(member, base_url)
    except Exception as e:
        current_app.logger.error(
            f"Failed to send new-member notification emails for {member.username}: {e}")


def create_member_from_identity(username, email=None, first_name=None, last_name=None,
                                organization=None, base_url=None, notify=False):
    """Create a member record for an authenticated identity that has no MAAP
    member row yet — the Keycloak-era replacement for the auto-create that the
    CAS SSO login flow used to provide. Role is GUEST; status comes from the
    pre-approved list (active) or defaults to suspended pending admin review.

    Creation is silent by default: new-user email notifications are the Hub
    environment's responsibility (its post-auth flow is the control center for
    registration emails), and the CAS auto-create was likewise silent. Pass
    notify=True with a base_url to send the same new-registration emails as
    POST /members.

    Returns the Member, the existing member when one already exists
    (concurrent first-touch race), or None on failure."""
    member = Member(first_name=first_name,
                    last_name=last_name,
                    username=username,
                    email=email,
                    organization=organization,
                    role_id=Role.ROLE_GUEST,
                    status=determine_initial_status(email),
                    creation_date=datetime.utcnow())
    try:
        db.session.add(member)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # A concurrent first-touch request may have created the member already.
        existing = db.session.query(Member).filter_by(username=username).first()
        if existing is not None:
            return existing
        current_app.logger.error(f"Failed to auto-create member {username}: {e}")
        return None

    if notify and base_url:
        notify_new_member(member, base_url)

    return member
