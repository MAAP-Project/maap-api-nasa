from api.models import Base
from api.maap_database import db


class MemberAlgorithmRegistration(Base):
    __tablename__ = 'member_algorithm_registration'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    username = db.Column(db.String(), db.ForeignKey('member.username'), nullable=False)
    email_id = db.Column(db.String(), db.ForeignKey('member.email'), nullable=False)
    algorithm_key = db.Column(db.String())
    creation_date = db.Column(db.DateTime())
    commit_hash = db.Column(db.String())
    ade_webhook = db.Column(db.String())
    member = db.relationship('Member', foreign_keys=[member_id])
    user = db.relationship('Member', foreign_keys=[username])
    email = db.relationship('Member', foreign_keys=[email_id])

    def __repr__(self):
        return "<MemberAlgorithmRegistration(registration_key={self.registration_key!r})>".format(self=self)