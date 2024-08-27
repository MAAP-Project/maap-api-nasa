from api.models import Base
from api.maap_database import db


class Role(Base):
    __tablename__ = 'role'

    ROLE_GUEST = 1
    ROLE_MEMBER = 2
    ROLE_ADMIN = 3

    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String())

    def __repr__(self):
        return "<Role(id={self.id!r})>".format(self=self)


