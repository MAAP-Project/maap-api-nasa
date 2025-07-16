import logging
from flask_restx import Resource
from flask import request, current_app as app
from flask_api import status
from api.models.job_queue import JobQueue
from api.models.role import Role
from api.restplus import api
from api.auth.security import login_required
from api.maap_database import db
from api.models.pre_approved import PreApproved
from api.schemas.pre_approved_schema import PreApprovedSchema
from datetime import datetime
import json
from api.utils import job_queue
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
        all_queues = job_queue.get_all_queues()
        return all_queues


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
        is_default = req_data.get("is_default", False)
        time_limit_minutes = req_data.get("time_limit_minutes", 0)
        orgs = req_data.get("orgs", [])

        new_queue = job_queue.create_queue(queue_name, queue_description, guest_tier, is_default, time_limit_minutes, orgs)
        return new_queue


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
        queue.is_default = req_data.get("is_default", queue.is_default)
        queue.time_limit_minutes = req_data.get("time_limit_minutes", queue.time_limit_minutes)
        orgs = req_data.get("orgs", [])

        updated_queue = job_queue.update_queue(queue, orgs)
        return updated_queue


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

        job_queue.delete_queue(queue_id)

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

        try:
            db.session.add(new_email)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to add pre-approved email {email}: {e}")
            raise

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

        try:
            db.session.query(PreApproved).filter_by(email=email).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to delete pre-approved email {email}: {e}")
            raise

        return {"code": status.HTTP_200_OK, "message": "Successfully deleted {}.".format(email)}
