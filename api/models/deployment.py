from api.models import Base
from api.maap_database import db

class Deployment(Base):
    __tablename__ = 'deployment'

    job_id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.String(), nullable=True)
    status = db.Column(db.String(), nullable=False)
    execution_venue = db.Column(db.String(), nullable=True)
    pipeline_id = db.Column(db.Integer, nullable=True)
    cwl_link = db.Column(db.String(), nullable=True)
    id = db.Column(db.String(), nullable=False)
    version = db.Column(db.String(), nullable=False)
    deployer = db.Column(db.String(), db.ForeignKey('member.username'), nullable=False)
    author = db.Column(db.String(), nullable=True)
    process_id= db.Column(db.String(), nullable=True)
    title = db.Column(db.String(), nullable=True)
    description = db.Column(db.String(), nullable=True)
    # comma separated list of keywords from CWL 
    keywords = db.Column(db.String(), nullable=True)
    github_url = db.Column(db.String(), nullable=True)
    git_commit_hash = db.Column(db.String(), nullable=True)
    ram_min = db.Column(db.Integer, nullable=True)
    cores_min = db.Column(db.Integer, nullable=True)
    base_command = db.Column(db.String(), nullable=True)