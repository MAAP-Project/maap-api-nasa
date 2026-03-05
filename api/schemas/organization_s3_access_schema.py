from api.models.organization_s3_access import OrganizationS3Access
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class OrganizationS3AccessSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = OrganizationS3Access
        include_fk = True
        load_instance = True
