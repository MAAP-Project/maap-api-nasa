from api.models import Base
from api.maap_database import db


class PreApproved(Base):
    __tablename__ = 'preapproved'

    email = db.Column(db.String(), primary_key=True)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<PreApproved(email={self.email!r})>".format(self=self)


