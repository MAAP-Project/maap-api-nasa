from api.models.process_job import ProcessJob
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessJobSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessJob
        include_fk = True
        load_instance = True
