from api.models import Base
from api.maap_database import db

class Deployment(Base):
    __tablename__ = 'deployment'

    job_id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.String(), nullable=True)
    status = db.Column(db.String(), nullable=False)
    execution_venue = db.Column(db.String(), nullable=True)
    pipeline_id = db.Column(db.Integer, nullable=True)
    cwl_link = db.Column(db.String(), nullable=False)
    id = db.Column(db.String(), nullable=False)
    version = db.Column(db.String(), nullable=False)
    user = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    process_id= db.Column(db.String(), nullable=True)
    title = db.Column(db.String(), nullable=True)
    description = db.Column(db.String(), nullable=True)
    # comma separated list of keywords from CWL 
    keywords = db.Column(db.String(), nullable=True)