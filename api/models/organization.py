from api.models import Base
from api.maap_database import db

class Organization(Base):
    __tablename__ = 'organization'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String())
    parent_org_id = db.Column(db.Integer, db.ForeignKey('organization.id'))

    # The maximum number of jobs that org members can run per the defined hour(s).
    # Used in conjunction with default_job_limit_hours.
    # A value of null or zero equates to unlimited jobs.
    default_job_limit_count = db.Column(db.Integer)

    # The number of hours during which an org member can run their allotment of jobs.
    # Used in conjunction with default_job_limit_count.
    # A value of null or zero equates to unlimited hours.
    default_job_limit_hours = db.Column(db.Integer)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<Organization(name={self.name!r})>".format(self=self)


