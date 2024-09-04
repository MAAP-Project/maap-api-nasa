import logging
import sqlalchemy
from flask_restx import Resource
from flask import request
from flask_api import status
from collections import namedtuple
from sqlalchemy.exc import SQLAlchemyError
from api.models.job_queue import JobQueue
from api.models.organization import Organization as Organization_db
from api.models.organization_job_queue import OrganizationJobQueue
from api.models.organization_membership import OrganizationMembership as OrganizationMembership_db
from api.models.member import Member
from api.models.role import Role
from api.restplus import api
from api.auth.security import login_required, get_authorized_user
from api.maap_database import db
from api.schemas.organization_job_queue_schema import OrganizationJobQueueSchema
from api.schemas.organization_membership_schema import OrganizationMembershipSchema
from api.schemas.organization_schema import OrganizationSchema
from datetime import datetime
import json

from api.utils import organization
from api.utils.http_util import err_response

log = logging.getLogger(__name__)
ns = api.namespace('organizations', description='Operations related to the MAAP organizations')

@ns.route('')
class Organizations(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):
        """
        Lists the hierarchy of organizations using MAAP
        :return:
        """
        orgs = organization.get_organizations()
        return orgs

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """
        Create new organization
        :return:
        """

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        name = req_data.get("name", "")
        if not isinstance(name, str) or not name:
            return err_response("Valid org name is required.")

        root_org = db.session \
            .query(Organization_db) \
            .filter_by(parent_org_id=None) \
            .first()

        parent_org_id = req_data.get("parent_org_id", root_org.id)
        if parent_org_id is None:
            parent_org_id = root_org.id

        default_job_limit_count = req_data.get("default_job_limit_count", None)
        default_job_limit_hours = req_data.get("default_job_limit_hours", None)
        members = req_data.get("members", [])

        new_org = organization.create_organization(name, parent_org_id, default_job_limit_count, default_job_limit_hours, members)

        return new_org


@ns.route('/<int:org_id>')
class Organization(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, org_id):
        """
        Retrieve organization
        """
        org = organization.get_organization(org_id)

        if org is None:
            return err_response(msg="No organization found with id " + org_id, code=status.HTTP_404_NOT_FOUND)

        org_schema = OrganizationSchema()
        result = json.loads(org_schema.dumps(org))

        return result

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def put(self, org_id):

        """
        Update organization. Only supplied fields are updated.
        """

        if not org_id:
            return err_response("Org id is required.")

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        org = db.session.query(Organization_db).filter_by(id=org_id).first()

        if org is None:
            return err_response(msg="No org found with id " + org_id)

        org.name = req_data.get("name", org.name)
        org.parent_org_id = req_data.get("parent_org_id", org.parent_org_id)
        org.default_job_limit_count = req_data.get("default_job_limit_count", org.default_job_limit_count)
        org.default_job_limit_hours = req_data.get("default_job_limit_hours", org.default_job_limit_hours)
        members = req_data.get("members", [])

        updated_org = organization.update_organization(org, members)
        return updated_org



    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, org_id):
        """
        Delete organization
        """

        org = organization.get_organization(org_id)

        if org is None:
            return err_response(msg="Organization does not exist")

        org_name = org.name
        organization.delete_organization(org.id)

        return {"code": status.HTTP_200_OK, "message": "Successfully deleted {}.".format(org_name)}


@ns.route('/<int:org_id>/membership')
class OrganizationMemberships(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, org_id):
        """
        Retrieve organization members
        """
        try:
            org_members = db.session.query(
                OrganizationMembership_db, Member, Organization_db,
            ).filter(
                OrganizationMembership_db.member_id == Member.id,
            ).filter(
                OrganizationMembership_db.org_id == Organization_db.id,
            ).filter(
                OrganizationMembership_db.org_id == org_id,
            ).order_by(Member.username).all()

            result = [{
                'org_id': om.organization.id
            } for om in org_members]

            return result
        except SQLAlchemyError as ex:
            raise ex


@ns.route('/<int:org_id>/membership/<string:username>')
class OrganizationMembership(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self, org_id, username):
        """
        Add organization member
        :return:
        """
        try:
            req_data = request.get_json()
            if not isinstance(req_data, dict):
                return err_response("Valid JSON body object required.")

            member = get_authorized_user()
            membership = db.session.query(OrganizationMembership_db).filter_by(member_id=member.id,
                                                                               org_id=org_id).first()

            if member.role_id != Role.ROLE_ADMIN and not membership.org_maintainer:
                return err_response("Must be an org maintainer to add members.", status.HTTP_403_FORBIDDEN)

            org_member = db.session.query(Member).filter_by(username=username).first()

            if org_member is None:
                return err_response("Valid username is required.")

            membership_dup = db.session.query(OrganizationMembership_db).filter_by(member_id=org_member.id,
                                                                                   org_id=org_id).first()

            if membership_dup is not None:
                return err_response("Member {} already exists in org {}".format(username, org_id))

            job_limit_count = req_data.get("job_limit_count", None)
            job_limit_hours = req_data.get("job_limit_hours", None)
            org_maintainer = req_data.get("org_maintainer", False)

            new_org_membership = OrganizationMembership_db(org_id=org_id, member_id=org_member.id,
                                                           job_limit_count=job_limit_count,
                                                           job_limit_hours=job_limit_hours,
                                                           org_maintainer=org_maintainer,
                                                           creation_date=datetime.utcnow())

            db.session.add(new_org_membership)
            db.session.commit()

            org_schema = OrganizationMembershipSchema()
            return json.loads(org_schema.dumps(new_org_membership))

        except SQLAlchemyError as ex:
            raise ex

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, org_id, username):
        """
        Delete organization member
        """
        try:
            member = get_authorized_user()
            membership = db.session.query(OrganizationMembership_db).filter_by(member_id=member.id,
                                                                               org_id=org_id).first()

            if membership is None:
                return err_response("Org id {} for user {} was not found.".format(org_id, member.username))

            if not membership.org_maintainer and member.role_id != Role.ROLE_ADMIN:
                return err_response("Must be an org maintainer to remove members.", status.HTTP_403_FORBIDDEN)

            member_to_delete = db.session.query(Member).filter_by(username=username).first()

            if member_to_delete is None:
                return err_response("Member {} was not found.".format(username))

            membership_to_delete = db.session.query(OrganizationMembership_db).filter_by(member_id=member_to_delete.id,
                                                                                         org_id=org_id).first()

            if membership_to_delete is None:
                return err_response("Org id {} for user {} was not found.".format(org_id, member_to_delete.username))

            db.session.query(OrganizationMembership_db).filter_by(member_id=member_to_delete.id, org_id=org_id).delete()
            db.session.commit()

            return {"code": status.HTTP_200_OK,
                    "message": "Successfully removed {} from org {}.".format(member_to_delete.username, org_id)}

        except SQLAlchemyError as ex:
            raise ex


@ns.route('/<int:org_id>/job_queues')
class OrganizationJobQueues(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, org_id):
        """
        Retrieve organization members
        """
        try:
            org_queues = db.session.query(
                OrganizationJobQueue, JobQueue, Organization_db,
            ).filter(
                OrganizationJobQueue.job_queue_id == JobQueue.id,
            ).filter(
                OrganizationJobQueue.org_id == Organization_db.id,
            ).filter(
                OrganizationJobQueue.org_id == org_id,
            ).order_by(JobQueue.queue_name).all()

            result = [{
                'org_id': om.organization.id
            } for om in org_queues]

            return result
        except SQLAlchemyError as ex:
            raise ex


@ns.route('/<int:org_id>/job_queues/<string:queue_name>')
class OrganizationJobQueueCls(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self, org_id, queue_name):
        """
        Add organization member
        :return:
        """
        try:
            req_data = request.get_json()
            if not isinstance(req_data, dict):
                return err_response("Valid JSON body object required.")

            member = get_authorized_user()
            membership = db.session.query(OrganizationMembership_db).filter_by(member_id=member.id,
                                                                               org_id=org_id).first()

            if member.role_id != Role.ROLE_ADMIN and not membership.org_maintainer:
                return err_response("Must be an org maintainer to add queues.", status.HTTP_403_FORBIDDEN)

            org_queue = db.session.query(JobQueue).filter_by(queue_name=queue_name).first()

            if org_queue is None:
                return err_response("Valid job queue is required.")

            org_queue_dup = db.session.query(OrganizationJobQueue).filter_by(job_queue_id=org_queue.id,
                                                                             org_id=org_id).first()

            if org_queue_dup is not None:
                return err_response("Job queue {} already exists in org {}".format(queue_name, org_id))

            new_org_queue = OrganizationJobQueue(org_id=org_id, job_queue_id=org_queue.id,
                                                 creation_date=datetime.utcnow())

            db.session.add(new_org_queue)
            db.session.commit()

            org_schema = OrganizationJobQueueSchema()
            return json.loads(org_schema.dumps(new_org_queue))

        except SQLAlchemyError as ex:
            raise ex

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, org_id, queue_name):
        """
        Delete organization member
        """
        try:
            member = get_authorized_user()
            membership = db.session.query(OrganizationMembership_db).filter_by(member_id=member.id,
                                                                               org_id=org_id).first()

            if membership is None:
                return err_response("Org id {} for user {} was not found.".format(org_id, member.username))

            if not membership.org_maintainer and member.role_id != Role.ROLE_ADMIN:
                return err_response("Must be an org maintainer to remove members.", status.HTTP_403_FORBIDDEN)

            queue_to_delete = db.session.query(JobQueue).filter_by(queue_name=queue_name).first()

            if queue_to_delete is None:
                return err_response("Job queue {} was not found.".format(queue_name))

            org_queue_to_delete = db.session.query(OrganizationJobQueue).filter_by(job_queue_id=queue_to_delete.id,
                                                                                   org_id=org_id).first()

            if org_queue_to_delete is None:
                return err_response("Org id {} for job queue {} was not found.".format(org_id, queue_name))

            db.session.query(OrganizationJobQueue).filter_by(job_queue_id=queue_to_delete.id, org_id=org_id).delete()
            db.session.commit()

            return {"code": status.HTTP_200_OK,
                    "message": "Successfully removed {} from org {}.".format(queue_name, org_id)}

        except SQLAlchemyError as ex:
            raise ex
