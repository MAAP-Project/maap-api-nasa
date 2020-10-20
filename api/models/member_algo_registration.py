from api.models import Base
from api.maap_database import db
# from datetime import datetime
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberAlgorithmRegistration(Base):
    __tablename__ = 'member_algorithm_registration'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    username = db.Column(db.String(), db.ForeignKey('member.username'), nullable=False)
    email = db.Column(db.String(), db.ForeignKey('member.email'), nullable=False)
    algorithm_key = db.Column(db.String())
    creation_date = db.Column(db.DateTime())
    commit_hash = db.Column(db.String())
    ade_webhook = db.Column(db.String())
    member = db.relationship('Member', backref=db.backref('algorithms'))

    def __repr__(self):
        return "<MemberAlgorithmRegistration(algorithm_key={self.algorithm_key!r})>".format(self=self) # what does this mean?


class MemberAlgorithmRegistrationSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberAlgorithmRegistration
        include_fk = True
        load_instance = True