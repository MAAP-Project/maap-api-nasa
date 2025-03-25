from api.models import Base
from api.maap_database import db

class ProcessKeywords(Base):
    __tablename__ = 'process_keywords'

    id = db.Column(db.Integer, primary_key=True)
    parent_process_id = db.Column(db.String(), db.ForeignKey('process.id'))
    keyword = db.Column(db.String())