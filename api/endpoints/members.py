import logging
from flask_restplus import Resource, reqparse
from flask import request, jsonify, make_response
from api.restplus import api
import api.settings as settings
from api.cas.cas_auth import get_authorized_user, login_required, dps_authorized, get_dps_user
from api.maap_database import db
from api.models.member import Member, MemberSchema
from datetime import datetime
import json
import boto3
from urllib import parse


log = logging.getLogger(__name__)
ns = api.namespace('members', description='Operations for MAAP members')
s3_client = boto3.client('s3', region_name=settings.AWS_REGION)


@ns.route('/self')
class Self(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()

        if 'proxy-ticket' in request.headers:
            member_schema = MemberSchema()
            return json.loads(member_schema.dumps(member))

        if 'Authorization' in request.headers:
            return member


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


@ns.route('/self/presignedUrlS3/<string:bucket>/<path:key>')
class PresignedUrlS3(Resource):

    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)
    expiration_param.add_argument('ws', type=str, required=False, default="")

    @login_required
    @api.expect(expiration_param)
    def get(self, bucket, key):

        expiration = request.args['exp']
        che_ws_namespace = request.args['ws'] if 'ws' in request.args else ''
        s3_path = self.mount_key_to_bucket(key, che_ws_namespace) if che_ws_namespace else key

        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket,
                'Key': parse.unquote(s3_path)
            },
            ExpiresIn=expiration

        )

        response = jsonify(url=url)
        response.headers.add('Access-Control-Allow-Origin', '*')

        return response

    def mount_key_to_bucket(self, key, ws):

        if key.startswith(settings.WORKSPACE_MOUNT_PRIVATE):
            return key.replace(settings.WORKSPACE_MOUNT_PRIVATE, ws)
        elif key.startswith(settings.WORKSPACE_MOUNT_PUBLIC):
            return key.replace(settings.WORKSPACE_MOUNT_PUBLIC, f'{settings.AWS_SHARED_WORKSPACE_BUCKET_PATH}/{ws}')
        elif key.startswith(settings.WORKSPACE_MOUNT_SHARED):
            return key.replace(settings.WORKSPACE_MOUNT_SHARED, settings.AWS_SHARED_WORKSPACE_BUCKET_PATH)
        else:
            return key


@ns.route('/dps/userImpersonationToken')
class DPS(Resource):

    @dps_authorized
    def get(self):
        dps_user = get_dps_user()
        response = jsonify(user_token=dps_user.urs_token, app_token=settings.MAAP_EDL_CREDS)

        return response










