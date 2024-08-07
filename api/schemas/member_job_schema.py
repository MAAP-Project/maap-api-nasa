from api.models.member_job import MemberJob
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberJobSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberJob
        include_fk = True
        load_instance = True
