from api.models import Base
from api.maap_database import db


class Member(Base):
    __tablename__ = 'member'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True)
    email = db.Column(db.String(), unique=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False, default=1)
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

    def get_display_name(self):
        return "{} {}".format(self.first_name, self.last_name)

    def is_guest(self):
        return self.role_id == 1

    def is_member(self):
        return self.role_id == 2

    def is_admin(self):
        return self.role_id == 3

    def __repr__(self):
        return "<Member(username={self.username!r})>".format(self=self)


