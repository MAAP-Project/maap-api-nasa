from api.models.process_metadata_2 import ProcessMetadata2
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessMetadata2Schema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessMetadata2
        include_fk = True
        load_instance = True