from api.models.organization import Organization
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class OrganizationSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Organization
        include_fk = True
        load_instance = True
