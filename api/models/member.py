from api.models import Base
from api.maap_database import db
from api.models.role import Role

class Member(Base):
    __tablename__ = 'member'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True)
    email = db.Column(db.String(), unique=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False, default=Role.ROLE_GUEST)
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
        return self.role_id == Role.ROLE_GUEST

    def is_member(self):
        return self.role_id == Role.ROLE_MEMBER

    def is_admin(self):
        return self.role_id == Role.ROLE_ADMIN

    def __repr__(self):
        return "<Member(username={self.username!r})>".format(self=self)


