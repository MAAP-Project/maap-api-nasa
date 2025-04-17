from api.models import Base
from api.maap_database import db

class Process(Base):
    __tablename__ = 'process'

    process_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(), nullable=False)
    version = db.Column(db.String(), nullable=False)
    cwl_link = db.Column(db.String(), nullable=False)
    user = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)