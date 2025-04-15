from api.models import Base
from api.maap_database import db

class Process(Base):
    __tablename__ = 'process'

    process_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(), nullable=False)
    version = db.Column(db.String(), nullable=False)
    status = db.Column(db.String(), nullable=False)
    process_workflow_link = db.Column(db.String(), nullable=False)
    user = db.Column(db.String(), nullable=False)