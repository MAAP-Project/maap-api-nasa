from api.models import Base
from api.maap_database import db
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class Member(Base):
    __tablename__ = 'member'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True)
    email = db.Column(db.String(), unique=True)
    first_name = db.Column(db.String())
    last_name = db.Column(db.String())
    organization = db.Column(db.String())
    public_ssh_key = db.Column(db.String())
    public_ssh_key_name = db.Column(db.String())
    public_ssh_key_modified_date = db.Column(db.DateTime())
    urs_token = db.Column(db.String())
    status = db.Column(db.String())
    gitlab_id = db.Column(db.String())
    gitlab_username = db.Column(db.String())
    gitlab_token = db.Column(db.String())
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<Member(username={self.username!r})>".format(self=self)


class MemberSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Member
        include_relationships = True
        load_instance = True


