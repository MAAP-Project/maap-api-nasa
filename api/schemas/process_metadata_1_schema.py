from api.models.process_metadata_1 import ProcessMetadata1
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessMetadata1Schema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessMetadata1
        include_fk = True
        load_instance = True