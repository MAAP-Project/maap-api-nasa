from api.models import Base
from api.maap_database import db
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberJob(Base):
    __tablename__ = 'member_job'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    job_id = db.Column(db.String())
    submitted_date = db.Column(db.DateTime())
    member = db.relationship('Member', backref=db.backref('jobs'))

    def __repr__(self):
        return "<MemberJob(id={self.id!r})>".format(self=self)


class MemberJobSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberJob
        include_fk = True
        load_instance = True