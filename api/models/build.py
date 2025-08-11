
from api.models import Base
from api.maap_database import db
import datetime


class Build(Base):
    """
    Model for tracking build requests and their status.
    Follows the same pattern as the Deployment model.
    """
    
    __tablename__ = 'build'
    
    build_id = db.Column(db.String(), primary_key=True)
    created = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now(datetime.timezone.utc))
    status = db.Column(db.String(), nullable=False, default='accepted')
    pipeline_id = db.Column(db.Integer, nullable=True)
    requester = db.Column(db.Integer, db.ForeignKey('member.id'), nullable=False)
    updated = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.now(datetime.timezone.utc))
    pipeline_url = db.Column(db.String(), nullable=True)
    repository_url = db.Column(db.String(), nullable=True)
    branch_ref = db.Column(db.String(), nullable=True, default='main')
