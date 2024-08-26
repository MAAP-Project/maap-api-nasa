from api.models.job_queue import JobQueue
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobQueue
        include_relationships = True
        load_instance = True


