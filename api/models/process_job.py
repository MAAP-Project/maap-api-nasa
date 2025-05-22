from api.models import Base
from api.maap_database import db


class ProcessJob(Base):
    __tablename__ = 'process_job'

    # This is what is passed back from HySDS, will always be unique 
    id = db.Column(db.String(), primary_key=True)
    user = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    submitted_time = db.Column(db.DateTime())
    completed_time = db.Column(db.DateTime())
    status = db.Column(db.String())
    results = db.Column(db.String())
    traceback = db.Column(db.String())
    # Process id of the process this job was submitted for 
    process_id = db.Column(db.Integer, db.ForeignKey('process.process_id'), nullable=False)