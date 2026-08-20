import logging

from sqlalchemy import text

from api import constants
from api.maap_database import db
from api.models.member import Member
from api.models.member_log import MemberLog
from api.models.member_log_change import MemberLogChange
from api.models.organization import Organization
from api.models.organization_membership import OrganizationMembership
from api.models.role import Role

log = logging.getLogger(__name__)


def seed_member_log_changes():
    """Ensure the member_log_change reference rows exist. Idempotent: safe to
    call on every boot (no migration tooling — schema is create_all())."""
    for change_type in (MemberLogChange.CHANGE_STATUS,
                        MemberLogChange.CHANGE_ROLE,
                        MemberLogChange.CHANGE_ORG,
                        MemberLogChange.CHANGE_SLACK,
                        MemberLogChange.CHANGE_MAILING):
        exists = db.session.query(MemberLogChange).filter_by(change_type=change_type).first()
        if exists is None:
            db.session.add(MemberLogChange(change_type=change_type))
    db.session.commit()


def add_missing_member_columns():
    """Add nullable member columns introduced after the table already existed.
    create_all() only creates missing *tables*, not columns, and there is no
    migration tooling — so add them idempotently at startup (Postgres
    ADD COLUMN IF NOT EXISTS)."""
    for column in ("invited_to_slack", "added_to_mailing_list"):
        db.session.execute(text(
            f"ALTER TABLE member ADD COLUMN IF NOT EXISTS {column} BOOLEAN"))
    db.session.commit()


def migrate_legacy_status():
    """One-time (idempotent) backfill: pre-expansion members stored 'suspended';
    the expanded status model has no 'suspended', so map those to 'inactive'.
    No-ops once no rows remain."""
    updated = db.session.query(Member) \
        .filter(Member.status == constants.STATUS_SUSPENDED) \
        .update({Member.status: constants.STATUS_INACTIVE}, synchronize_session=False)
    if updated:
        db.session.commit()
        log.info("Migrated %d legacy 'suspended' member(s) to 'inactive'", updated)


def run_startup_tasks():
    """Column adds + reference-data seed + legacy-status backfill, called after
    create_all. Each step is independent so one failure doesn't block the rest."""
    for step in (add_missing_member_columns, seed_member_log_changes, migrate_legacy_status):
        try:
            step()
        except Exception as e:
            db.session.rollback()
            log.error("member_log startup step %s failed: %s", step.__name__, e)


def role_name(role_id):
    """Human-readable role name for a role id (for audit old/new values)."""
    if role_id is None:
        return None
    role = db.session.query(Role).filter_by(id=role_id).first()
    return role.role_name if role is not None else str(role_id)


def org_names_csv(member_id):
    """Comma-separated, sorted list of the org names a member belongs to
    (for audit old/new values)."""
    rows = db.session \
        .query(Organization.name) \
        .join(OrganizationMembership, Organization.id == OrganizationMembership.org_id) \
        .filter(OrganizationMembership.member_id == member_id) \
        .all()
    return ", ".join(sorted(name for (name,) in rows))


def record_member_change(member_id, admin_id, change_type, old_value, new_value, comment):
    """Append a member_log audit row for one changed dimension. Adds to the
    session without committing — the caller commits once for the whole action.
    Returns the MemberLog, or None if the change_type reference row is missing."""
    change = db.session.query(MemberLogChange).filter_by(change_type=change_type).first()
    if change is None:
        log.error("member_log_change row missing for %r; skipping audit entry", change_type)
        return None
    entry = MemberLog(
        member_id=member_id,
        admin_id=admin_id,
        member_log_change_id=change.id,
        comment=comment,
        old_value=old_value,
        new_value=new_value,
    )
    db.session.add(entry)
    return entry
