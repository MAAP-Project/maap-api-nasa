import logging
from flask_restplus import Resource
from flask import request
from api.restplus import api
from api.cas.cas_auth import get_authorized_user, login_required
from api.maap_database import db
from api.models.member import Member, MemberSchema
from datetime import datetime
import json


log = logging.getLogger(__name__)

ns = api.namespace('members', description='Operations for MAAP members')


@ns.route('/self')
class Self(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()
        member_schema = MemberSchema()

        return json.loads(member_schema.dumps(member))


@ns.route('/selfTest')
class Self(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()
        member_schema = MemberSchema()

        return json.loads(member_schema.dumps(member))


@ns.route('/self/sshKey')
class PublicSshKeyUpload(Resource):

    @login_required
    def post(self):
        if 'file' not in request.files:
            log.error('Upload attempt with no file')
            raise Exception('No file uploaded')

        member = get_authorized_user()

        f = request.files['file']

        file_lines = f.read().decode("utf-8")

        db.session.query(Member).filter(Member.id == member.id). \
            update({Member.public_ssh_key: file_lines,
                    Member.public_ssh_key_name: f.filename,
                    Member.public_ssh_key_modified_date: datetime.utcnow()})

        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))

    @login_required
    def delete(self):
        member = get_authorized_user()

        db.session.query(Member).filter(Member.id == member.id). \
            update({Member.public_ssh_key: '',
                    Member.public_ssh_key_name: '',
                    Member.public_ssh_key_modified_date: datetime.utcnow()})

        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


# @ns.route('/self/project')
# class ProjectData(Resource):
#
#     @login_required
#     def get(self):
#         member = get_authorized_user()
#         project = MemberCmrCollection.query.filter_by(member_id=member.id)
#
#         return project
#
#     @login_required
#     def post(self):
#         member = get_authorized_user()
#         # project = MemberCmrCollection.query.filter_by(member_id=member.id)
#         test = Member()
#         sample = test.deserialize(request.get_json())
#         db.session.add(sample)
#         db.session.commit()
#
#         #return project





