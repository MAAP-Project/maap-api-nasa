from api.models.organization_membership import OrganizationMembership
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class OrganizationMembershipSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = OrganizationMembership
        include_fk = True
        load_instance = True
