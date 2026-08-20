from api.models import Base
from api.maap_database import db


class MemberLogChange(Base):
    """Reference/lookup table of member-change categories audited in
    member_log. Seeded idempotently at startup (see
    api/utils/member_log_util.py)."""
    __tablename__ = 'member_log_change'

    CHANGE_STATUS = 'Status'
    CHANGE_ROLE = 'Role'
    CHANGE_ORG = 'Org'
    CHANGE_SLACK = 'Slack Invite'
    CHANGE_MAILING = 'Mailing List'

    id = db.Column(db.Integer, primary_key=True)
    change_type = db.Column(db.String(), unique=True, nullable=False)

    def __repr__(self):
        return "<MemberLogChange(change_type={self.change_type!r})>".format(self=self)
