from api.models import Base
from api.maap_database import db
# from datetime import datetime
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberAlgorithm(Base):
    __tablename__ = 'member_algorithm'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    algorithm_key = db.Column(db.String())
    is_public = db.Column(db.Boolean())
    creation_date = db.Column(db.DateTime())
    member = db.relationship('Member', backref=db.backref('algorithms'))

    def __repr__(self):
        return "<MemberAlgorithm(algorithm_key={self.algorithm_key!r})>".format(self=self)


class MemberAlgorithmSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberAlgorithm
        include_fk = True
        load_instance = True