from api.models.member_algo_registration import MemberAlgorithmRegistration
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class MemberAlgorithmRegistrationSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MemberAlgorithmRegistration
        include_fk = True
        load_instance = True