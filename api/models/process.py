from api.models import Base
from api.maap_database import db

class Process(Base):
    __tablename__ = 'process'

    process_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(), nullable=False)
    version = db.Column(db.String(), nullable=False)
    cwl_link = db.Column(db.String(), nullable=False)
    user = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    # Status is either deployed or undeployed 
    status = db.Column(db.String(), nullable=False)
    title = db.Column(db.String(), nullable=True)
    description = db.Column(db.String(), nullable=True)
    # comma separated list of keywords from CWL 
    keywords = db.Column(db.String(), nullable=True)
    # UTC time the process was last modified
    last_modified_time = db.Column(db.DateTime(), nullable=True)
    # Process name as it is stored in like HySDS
    process_name_hysds = db.Column(db.String(), nullable=True)
    github_url = db.Column(db.String(), nullable=True)
    git_commit_hash = db.Column(db.String(), nullable=True)
    ram_min = db.Column(db.Integer, nullable=True)
    cores_min = db.Column(db.Integer, nullable=True)
    base_command = db.Column(db.String(), nullable=True)