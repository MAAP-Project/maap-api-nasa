from api.models.member_session import MemberSession
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberSessionSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberSession
        include_fk = True
        load_instance = True

