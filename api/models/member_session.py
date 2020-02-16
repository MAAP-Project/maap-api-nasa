from api.maap_database import db
from datetime import datetime


class MemberSession(db.Model):
    __tablename__ = 'member_session'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    session_key = db.Column(db.String())
    creation_date = db.Column(db.DateTime())

    member = db.relationship('Member', backref=db.backref('member', lazy=True))

    def __init__(self, member_id, session_key):
        self.member_id = member_id
        self.session_key = session_key
        self.creation_date = datetime.utcnow()

    def __repr__(self):
        return '<MemberSession %r>' % self.session_key
