from api.models.process_job_control_options import ProcessJobControlOptions
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessJobControlOptionsSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessJobControlOptions
        include_fk = True
        load_instance = True