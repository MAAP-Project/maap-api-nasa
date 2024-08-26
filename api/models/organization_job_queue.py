from api.models import Base
from api.maap_database import db


class OrganizationJobQueue(Base):
    __tablename__ = 'organization_job_queue'

    id = db.Column(db.Integer, primary_key=True)
    job_queue_id = db.Column(db.Integer, db.ForeignKey('job_queue.id'), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<OrganizationJobQueue(id={self.id!r})>".format(self=self)