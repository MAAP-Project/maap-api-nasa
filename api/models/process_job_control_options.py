from api.models import Base
from api.maap_database import db

class ProcessJobControlOptions(Base):
    __tablename__ = 'process_job_control_options'

    id = db.Column(db.Integer, primary_key=True)
    parent_process_id = db.Column(db.String(), db.ForeignKey('process.id'))
    job_control_option = db.Column(db.String())