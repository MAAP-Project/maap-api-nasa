from api.models.member import Member
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Member
        include_relationships = True
        load_instance = True


