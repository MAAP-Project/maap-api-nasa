from api.models import Base
from api.maap_database import db


class MemberSecret(Base):
    __tablename__ = 'member_secret'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    secret_name = db.Column(db.String())
    secret_value = db.Column(db.String())
    creation_date = db.Column(db.DateTime())
    member = db.relationship('Member', backref=db.backref('secrets'))

    def __repr__(self):
        return "<MemberSecret(id={self.id!r})>".format(self=self)