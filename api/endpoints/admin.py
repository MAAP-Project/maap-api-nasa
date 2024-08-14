import logging
from flask_restx import Resource
from flask import request
from flask_api import status
from api.restplus import api
from api.auth.security import login_required
from api.maap_database import db
from api.models.pre_approved import PreApproved
from api.schemas.pre_approved_schema import PreApprovedSchema
from datetime import datetime
import json

log = logging.getLogger(__name__)

ns = api.namespace('admin', description='Operations related to the MAAP admin')


@ns.route('/pre-approved')
class PreApprovedEmails(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self):
        pre_approved = db.session.query(
            PreApproved.email,
            PreApproved.creation_date
        ).order_by(PreApproved.email).all()

        pre_approved_schema = PreApprovedSchema()
        result = [json.loads(pre_approved_schema.dumps(p)) for p in pre_approved]
        return result

    @api.doc(security='ApiKeyAuth')
    @login_required
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
    @login_required
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


