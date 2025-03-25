from api.models.process_keywords import Process
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessesSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Process
        include_fk = True
        load_instance = True
