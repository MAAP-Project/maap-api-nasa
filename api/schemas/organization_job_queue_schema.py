from api.models.organization_job_queue import OrganizationJobQueue
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema


class OrganizationJobQueueSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = OrganizationJobQueue
        include_fk = True
        load_instance = True
