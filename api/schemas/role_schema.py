from api.models.role import Role
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class RoleSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Role
        include_relationships = True
        load_instance = True


