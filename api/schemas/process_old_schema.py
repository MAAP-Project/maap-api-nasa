from api.models.processOld import ProcessOld
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessesSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessOld
        include_fk = True
        load_instance = True