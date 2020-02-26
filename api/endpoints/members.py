import logging
from flask_restplus import Resource
from flask import request
from api.restplus import api
from api.cas.cas_auth import get_authorized_user, login_required
from api.maap_database import db
from api.models.member_cmr_collection import MemberCmrCollection
from api.models.member import Member


log = logging.getLogger(__name__)

ns = api.namespace('members', description='Operations for MAAP members')


@ns.route('/self')
class Self(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()

        return member


@ns.route('/self/project')
class ProjectData(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()
        project = MemberCmrCollection.query.filter_by(member_id=member.id)

        return project

    @login_required
    def post(self):
        member = get_authorized_user()
        # project = MemberCmrCollection.query.filter_by(member_id=member.id)
        test = Member()
        sample = test.deserialize(request.get_json())
        db.session.add(sample)
        db.session.commit()

        #return project





