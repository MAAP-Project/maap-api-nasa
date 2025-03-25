from api.models import Base
from api.maap_database import db

class Process(Base):
    __tablename__ = 'process'

    id = db.Column(db.String(), primary_key=True)
    title = db.Column(db.String(), nullable=True)
    description = db.Column(db.String(), nullable=True)
    version = db.Column(db.String())
    # Dont include keywords because that is its own thing with one to many relationship 
    # Dont include jobControlOptions because that it its own thing with one to many relationship

    member_id = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    algorithm_key = db.Column(db.String())
    is_public = db.Column(db.Boolean())
    creation_date = db.Column(db.DateTime())
    member = db.relationship('Member', backref=db.backref('algorithms'))