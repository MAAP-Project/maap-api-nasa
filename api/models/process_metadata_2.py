from api.models import Base
from api.maap_database import db

class ProcessMetadata2(Base):
    __tablename__ = 'process_metadata_2'

    id = db.Column(db.Integer, primary_key=True)
    parent_process_id = db.Column(db.String(), db.ForeignKey('process.id'))
    role = db.Column(db.String(), nullable=True)
    title = db.Column(db.String(), nullable=True)
    lang = db.Column(db.String(), nullable=True)
    # graceal This is of type object which I am not sure how to represent 
    value = db.Column(db.String(), nullable=True) 