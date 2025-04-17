from api.models.process import Process
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Process
        include_fk = True
        load_instance = True
