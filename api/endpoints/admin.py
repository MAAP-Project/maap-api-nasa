import logging
from flask_restx import Resource
from flask import request
from flask_api import status
import api.utils.hysds_util as hysds
from api.models.job_queue import JobQueue
from api.models.organization import Organization
from api.models.organization_job_queue import OrganizationJobQueue
from api.models.role import Role
from api.restplus import api
from api.auth.security import login_required
from api.maap_database import db
from api.models.pre_approved import PreApproved
from api.schemas.job_queue_schema import JobQueueSchema
from api.schemas.pre_approved_schema import PreApprovedSchema
from datetime import datetime
import json

from api.utils.http_util import err_response

log = logging.getLogger(__name__)
ns = api.namespace('admin', description='Operations related to the MAAP admin')

@ns.route('/job-queues')
class JobQueuesCls(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def get(self):
        """
        Lists the job queues and associated organizations
        :return:
        """

        result = []

        queues = db.session.query(
            JobQueue.id,
            JobQueue.queue_name,
            JobQueue.queue_description,
            JobQueue.guest_tier,
            PreApproved.creation_date
        ).order_by(PreApproved.email).all()

        orgs_query = db.session.query(
            Organization, OrganizationJobQueue,
        ).filter(
            Organization.id == OrganizationJobQueue.org_id
        ).order_by(Organization.name).all()

        hysds_queues = hysds.get_mozart_queues()

        for q in queues:
            queue = {
                'id': q.id,
                'queue_name': q.queue_name,
                'queue_description': q.queue_description,
                'guest_tier': q.guest_tier,
                'status': 'Online' if q.queue_name in hysds_queues else 'Offline',
                'orgs': [],
                'creation_date': q.creation_date.strftime('%m/%d/%Y'),
            }

            for o in orgs_query:
                if o.OrganizationJobQueue.job_queue_id == q.id:
                    queue['orgs'].append({
                        'id': o.Organization.id,
                        'org_name': o.Organization.name,
                        'default_job_limit_count': o.Organization.default_job_limit_count,
                        'default_job_limit_hours': o.Organization.default_job_limit_hours
                    })

            result.append(queue)

        unassigned_queues = (hq for hq in hysds_queues if hq not in map(self._queue_name, queues))
        for uq in unassigned_queues:
            result.append({
                'id': 0,
                'queue_name': uq,
                'queue_description': '',
                'guest_tier': False,
                'status': 'Unassigned',
                'orgs': [],
                'creation_date': None,
            })

        return result

    def _queue_name(self, q):
        return q.queue_name

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def post(self):

        """
        Create new job queue.
        """

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        queue_name = req_data.get("queue_name", "")
        if not isinstance(queue_name, str) or not queue_name:
            return err_response("Valid queue name is required.")

        queue_description = req_data.get("queue_description", "")
        if not isinstance(queue_description, str) or not queue_description:
            return err_response("Valid queue description is required.")

        guest_tier = req_data.get("guest_tier", False)

        new_queue = JobQueue(queue_name=queue_name, queue_description=queue_description, guest_tier=guest_tier, creation_date=datetime.utcnow())

        db.session.add(new_queue)
        db.session.commit()

        queue_orgs = []
        orgs = req_data.get("orgs", [])
        for queue_org in orgs:
            queue_orgs.append(OrganizationJobQueue(org_id=queue_org['org_id'], job_queue_id=new_queue.id, creation_date=datetime.utcnow()))

        if len(queue_orgs) > 0:
            db.session.add_all(queue_orgs)
            db.session.commit()

        org_schema = JobQueueSchema()
        return json.loads(org_schema.dumps(new_queue))


@ns.route('/job-queues/<int:queue_id>')
class JobQueueCls(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def put(self, queue_id):

        """
        Update job queue. Only supplied fields are updated.
        """

        if not queue_id:
            return err_response("Job queue id is required.")

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        queue = db.session.query(JobQueue).filter_by(id=queue_id).first()

        if queue is None:
            return err_response(msg="No job queue found with id " + queue_id)

        queue.queue_name = req_data.get("queue_name", queue.queue_name)
        queue.queue_description = req_data.get("queue_description", queue.queue_description)
        queue.guest_tier = req_data.get("guest_tier", queue.guest_tier)
        db.session.commit()

        # Update org assignments
        db.session.execute(
            db.delete(OrganizationJobQueue).filter_by(job_queue_id=queue_id)
        )
        db.session.commit()

        queue_orgs = []
        orgs = req_data.get("orgs", [])
        for queue_org in orgs:
            queue_orgs.append(OrganizationJobQueue(org_id=queue_org['org_id'], job_queue_id=queue_id, creation_date=datetime.utcnow()))

        if len(queue_orgs) > 0:
            db.session.add_all(queue_orgs)
            db.session.commit()

        queue_schema = JobQueueSchema()
        return json.loads(queue_schema.dumps(queue))

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def delete(self, queue_id):
        """
        Delete job queue
        """

        queue = db.session.query(JobQueue).filter_by(id=queue_id).first()
        queue_name = queue.queue_name

        if queue is None:
            return err_response(msg="Job queue does not exist")

        # Clear orgs
        db.session.execute(
            db.delete(OrganizationJobQueue).filter_by(job_queue_id=queue_id)
        )
        db.session.commit()

        db.session.query(OrganizationJobQueue).filter_by(id=queue_id).delete()
        db.session.commit()

        return {"code": status.HTTP_200_OK, "message": "Successfully deleted {}.".format(queue_name)}


@ns.route('/pre-approved')
class PreApprovedEmails(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def get(self):
        pre_approved = db.session.query(
            PreApproved.email,
            PreApproved.creation_date
        ).order_by(PreApproved.email).all()

        pre_approved_schema = PreApprovedSchema()
        result = [json.loads(pre_approved_schema.dumps(p)) for p in pre_approved]
        return result

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def post(self):

        """
        Create new pre-approved email. Wildcards are supported for starting email characters.

        Format of JSON to post:
        {
            "email": ""
        }

        Sample 1. Any email ending in "@maap-project.org" is pre-approved
        {
            "email": "*@maap-project.org"
        }

        Sample 2. Any email matching "jane.doe@maap-project.org" is pre-approved
        {
            "email": "jane.doe@maap-project.org"
        }
        """

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        email = req_data.get("email", "")
        if not isinstance(email, str) or not email:
            return err_response("Valid email is required.")

        pre_approved_email = db.session.query(PreApproved).filter_by(email=email).first()

        if pre_approved_email is not None:
            return err_response(msg="Email already exists")

        new_email = PreApproved(email=email, creation_date=datetime.utcnow())

        db.session.add(new_email)
        db.session.commit()

        pre_approved_schema = PreApprovedSchema()
        return json.loads(pre_approved_schema.dumps(new_email))


@ns.route('/pre-approved/<string:email>')
class PreApprovedEmails(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required(role=Role.ROLE_ADMIN)
    def delete(self, email):
        """
        Delete pre-approved email
        """

        pre_approved_email = db.session.query(PreApproved).filter_by(email=email).first()

        if pre_approved_email is None:
            return err_response(msg="Email does not exist")

        db.session.query(PreApproved).filter_by(email=email).delete()
        db.session.commit()

        return {"code": status.HTTP_200_OK, "message": "Successfully deleted {}.".format(email)}
