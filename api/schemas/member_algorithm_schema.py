from api.models.member_algorithm import MemberAlgorithm
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberAlgorithmSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberAlgorithm
        include_fk = True
        load_instance = True