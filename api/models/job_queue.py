from api.models import Base
from api.maap_database import db

class JobQueue(Base):
    __tablename__ = 'job_queue'

    id = db.Column(db.Integer, primary_key=True)
    queue_name = db.Column(db.String())
    queue_description = db.Column(db.String())
    # Whether the queue is available to public 'Guest' users
    guest_tier = db.Column(db.Boolean())
    # Whether the queue is used as a default when no queues are specified
    is_default = db.Column(db.Boolean())
    # The maximum time, in minutes, that jobs are allowed to run using this queue
    time_limit_minutes = db.Column(db.Integer)
    creation_date = db.Column(db.DateTime())

    def __repr__(self):
        return "<JobQueue(queue_name={self.queue_name!r})>".format(self=self)


