from api.models.member_secret import MemberSecret
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberSecretSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberSecret
        include_fk = True
        load_instance = True
