from api.models import Base
from api.maap_database import db

class Process(Base):
    __tablename__ = 'process'

    id = db.Column(db.String(), primary_key=True)
    title = db.Column(db.String(), nullable=True)
    description = db.Column(db.String(), nullable=True)
    version = db.Column(db.String())
    # This should later be a separate thing and use a one to one relational database 
    links = db.Column(db.String())
    # keywords = db.Column(db.String())
    # Dont include keywords because that is its own thing with one to many relationship, can also use HySDS tags potentially
    # Dont include jobControlOptions because that it its own thing with one to many relationship