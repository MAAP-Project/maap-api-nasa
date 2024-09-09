from api.models import Base
from api.maap_database import db


class OrganizationMembership(Base):
    __tablename__ = 'organization_membership'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    org_maintainer = db.Column(db.Boolean())
    # The maximum number of jobs that this org member can run per the defined hour(s).
    # Used in conjunction with job_limit_hours.
    # A value of null or zero equates to unlimited jobs.
    job_limit_count = db.Column(db.Integer)

    # The number of hours during which this org member can run their allotment of jobs.
    # Used in conjunction with job_limit_count.
    # A value of null or zero equates to unlimited hours.
    job_limit_hours = db.Column(db.Integer)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<OrganizationMembership(id={self.id!r})>".format(self=self)