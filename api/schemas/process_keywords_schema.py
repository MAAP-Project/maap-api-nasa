from api.models.process_keywords import ProcessKeywords
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class ProcessKeywordsSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ProcessKeywords
        include_fk = True
        load_instance = True