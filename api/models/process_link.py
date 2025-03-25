from api.models import Base
from api.maap_database import db

class ProcessLink(Base):
    __tablename__ = 'process_link'

    id = db.Column(db.Integer, primary_key=True)
    parent_process_id = db.Column(db.String(), db.ForeignKey('process.id'))
    href = db.Column(db.String(), nullable=True)
    rel = db.Column(db.String(), nullable=True)
    type = db.Column(db.String(), nullable=True)
    hreflang = db.Column(db.String(), nullable=True)
    title = db.Column(db.String(), nullable=True)