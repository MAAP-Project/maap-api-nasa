from api.models import Base
from api.maap_database import db
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class PreApproved(Base):
    __tablename__ = 'preapproved'

    email = db.Column(db.String(), primary_key=True)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<PreApproved(email={self.email!r})>".format(self=self)


class PreApprovedSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = PreApproved
        include_relationships = True
        load_instance = True


