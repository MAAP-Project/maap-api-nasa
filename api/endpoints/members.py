import logging
from flask_restplus import Resource, reqparse
from flask import request, jsonify, Response
from api.restplus import api
import api.settings as settings
from api.cas.cas_auth import get_authorized_user, login_required
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


@ns.route('/self/presignedUrlS3/<string:bucket>/<string:key>')
class PresignedUrlS3(Resource):

    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)

    #@login_required
    @api.expect(expiration_param)
    def get(self, bucket, key):

        expiration = request.args['exp']

        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket,
                'Key': parse.unquote(key)
            },
            ExpiresIn=expiration

        )

        response = Response(
            jsonify(url=url),
            200,
            {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            })

        return response









