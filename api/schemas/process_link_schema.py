from api.models.process_link import ProcessLink
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessLinkSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessLink
        include_fk = True
        load_instance = True