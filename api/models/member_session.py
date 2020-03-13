from api.models import Base
from api.maap_database import db
# from datetime import datetime
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberSession(Base):
    __tablename__ = 'member_session'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    session_key = db.Column(db.String())
    creation_date = db.Column(db.DateTime())
    member = db.relationship('Member', backref=db.backref('sessions'))

    def __repr__(self):
        return "<MemberSession(session_key={self.session_key!r})>".format(self=self)


class MemberSessionSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberSession
        include_fk = True
        load_instance = True

