from api.models import Base
from api.maap_database import db


class ProcessJob(Base):
    __tablename__ = 'process_job'

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    # This is what is passed back from HySDS
    job_id = db.Column(db.String())
    submitted_time = db.Column(db.DateTime())
    completed_time = db.Column(db.DateTime())
    status = db.Column(db.String())
    # Process id of the process this job was submitted for 
    process_id = db.Column(db.Integer, db.ForeignKey('process.process_id'), nullable=False)
    # member = db.relationship('Member', backref=db.backref('jobs'))