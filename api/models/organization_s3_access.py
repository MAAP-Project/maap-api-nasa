from api.models import Base
from api.maap_database import db


class OrganizationS3Access(Base):
    __tablename__ = 'organization_s3_access'

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    bucket_name = db.Column(db.String(), nullable=False)
    bucket_prefix = db.Column(db.String(), nullable=True)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<OrganizationS3Access(id={self.id!r})>".format(self=self)
