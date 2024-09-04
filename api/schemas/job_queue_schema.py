from api.models.job_queue import JobQueue
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class JobQueueSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobQueue
        include_relationships = True
        load_instance = True


