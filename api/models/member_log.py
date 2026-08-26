from datetime import datetime, timezone

from api.models import Base
from api.maap_database import db


class MemberLog(Base):
    """Audit trail of admin changes to a member's status, role, or org
    membership. One row per changed dimension per admin action.

    old_value / new_value are human-readable: the status string, the role name
    (from the role table), or a comma-separated list of org names.
    """
    __tablename__ = 'member_log'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    member_log_change_id = db.Column(
        db.Integer, db.ForeignKey('member_log_change.id'), nullable=False)
    comment = db.Column(db.String())
    old_value = db.Column(db.String())
    new_value = db.Column(db.String())
    updated = db.Column(db.DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return "<MemberLog(member_id={self.member_id!r}, change={self.member_log_change_id!r})>".format(self=self)
