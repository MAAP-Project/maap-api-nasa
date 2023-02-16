from api.models.pre_approved import PreApproved
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class PreApprovedSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = PreApproved
        include_relationships = True
        load_instance = True


