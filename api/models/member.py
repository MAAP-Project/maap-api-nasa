from api.maap_database import db
from datetime import datetime
import json


class Member(db.Model):
    __tablename__ = 'member'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True)
    email = db.Column(db.String(), unique=True)
    first_name = db.Column(db.String())
    last_name = db.Column(db.String())
    organization = db.Column(db.String())
    public_ssh_key = db.Column(db.String())
    creation_date = db.Column(db.DateTime())

    def __init__(self, first_name, last_name, username, email, organization):
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.email = email
        self.organization = organization
        self.creation_date = datetime.utcnow()

    def __repr__(self):
        return '<Member %r>' % self.username

    @property
    def serialize(self):
        json_data = json.dumps(self, default=lambda o: o.__dict__)
        return json_data

    @property
    def deserialize(self, json_data):
        decoded_obj = Member(**json.loads(json_data))
        return decoded_obj

