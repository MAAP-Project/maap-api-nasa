from api.models.deployment import Deployment
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class DeploymentSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Deployment
        include_fk = True
        load_instance = True