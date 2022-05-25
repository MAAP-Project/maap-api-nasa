import logging
from flask_restplus import Resource, reqparse
from flask import request, jsonify, Response
from api.restplus import api
import api.settings as settings
from api.cas.cas_auth import get_authorized_user, login_required, dps_authorized, get_dps_user
from api.maap_database import db
from api.models.member import Member as Member_db, MemberSchema
from datetime import datetime
import json
import boto3
import requests
from urllib import parse


log = logging.getLogger(__name__)
ns = api.namespace('members', description='Operations for MAAP members')
s3_client = boto3.client('s3', region_name=settings.AWS_REGION)

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"

def err_response(msg, code=400):
    return {
        'code': code,
        'message': msg
    }, code


@ns.route('/')
class Member(Resource):

    @login_required
    def get(self):
        members = db.session.query(Member_db).all()
        member_schema = MemberSchema()
        result = [json.loads(member_schema.dumps(m)) for m in members]
        return result


@ns.route('/<string:key>')
class Member(Resource):

    @login_required
    def get(self, key):

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is None:
            return err_response(msg="No member found with key " + key, code=404)

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))

    @login_required
    def post(self, key):

        """
        Create new member

        Format of JSON to post:
        {
            "first_name": "",
            "last_name": "",
            "email": "",
            "organization": "",
            "public_ssh_key": "",
            "public_ssh_key_name": "",
            "urs_token": "",
            "gitlab_id": "",
            "gitlab_username": "",
            "gitlab_token": ""
        }

        Sample JSON:
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@email.org",
            "organization": "NASA",
            "public_ssh_key": "----",
            "public_ssh_key_name": "----"
        }
        """

        if not key:
            return err_response("Username key is required.")

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        first_name = req_data.get("first_name", "")
        if not isinstance(first_name, str) or not first_name:
            return err_response("first_name is required.")

        last_name = req_data.get("last_name", "")
        if not isinstance(last_name, str) or not last_name:
            return err_response("last_name is required.")

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is not None:
            return err_response(msg="Member already exists with username " + key)

        email = req_data.get("email", "")
        if not isinstance(email, str) or not email:
            return err_response("Valid email is required.")

        member = db.session.query(Member_db).filter_by(email=email).first()

        if member is not None:
            return err_response(msg="Member already exists with email " + email)

        guest = Member_db(first_name=first_name,
                          last_name=last_name,
                          username=key,
                          email=email,
                          organization=req_data.get("organization", None),
                          public_ssh_key=req_data.get("public_ssh_key", None),
                          public_ssh_key_modified_date=datetime.utcnow(),
                          public_ssh_key_name=req_data.get("public_ssh_key_name", None),
                          urs_token=req_data.get("urs_token", None),
                          gitlab_id=req_data.get("gitlab_id", None),
                          gitlab_username=req_data.get("gitlab_username", None),
                          gitlab_token=req_data.get("gitlab_token", None),
                          status=STATUS_SUSPENDED)

        db.session.add(guest)
        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(guest))

    @login_required
    def put(self, key):

        """
        Update member. Only supplied fields are updated.

        Format of JSON to put:
        {
            "first_name": "",
            "last_name": "",
            "email": "",
            "organization": "",
            "public_ssh_key": "",
            "public_ssh_key_name": "",
            "urs_token": "",
            "gitlab_id": "",
            "gitlab_username": "",
            "gitlab_token": ""
        }

        Sample JSON:
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@email.org",
            "organization": "NASA",
            "public_ssh_key": "----",
            "public_ssh_key_name": "----"
        }
        """

        if not key:
            return err_response("Username key is required.")

        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is None:
            return err_response(msg="No member found with username " + key)

        email = req_data.get("email", member.email)
        if email != member.email:
            email_check = db.session.query(Member_db).filter_by(email=email).first()

            if email_check is not None:
                return err_response(msg="Member already exists with email " + email)

        member.first_name = req_data.get("first_name", member.first_name)
        member.last_name = req_data.get("last_name", member.last_name)
        member.email = email
        member.organization = req_data.get("organization", member.organization)
        if req_data.get("public_ssh_key", member.public_ssh_key) != member.public_ssh_key:
            member.public_ssh_key_modified_date = datetime.utcnow()
        member.public_ssh_key = req_data.get("public_ssh_key", member.public_ssh_key)
        member.public_ssh_key_name = req_data.get("public_ssh_key_name", member.public_ssh_key_name)
        member.gitlab_id = req_data.get("gitlab_id", member.gitlab_id)
        member.gitlab_username = req_data.get("gitlab_username", member.gitlab_username)
        member.gitlab_token = req_data.get("gitlab_token", member.gitlab_token)
        member.urs_token = req_data.get("urs_token", member.urs_token)
        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


@ns.route('/<string:key>/status')
class MemberStatus(Resource):

    @login_required
    def post(self, key):

        """
        Update member status

        Format of JSON to post:
        {
            "status": ""
        }

        Sample JSON:
        {
            "status": "suspended"
        }
        """
        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        status = req_data.get("status", "")
        if not isinstance(status, str) or not status:
            return err_response("Valid status string required.")

        if status != STATUS_ACTIVE and status != STATUS_SUSPENDED:
            return err_response("Status must be either " + STATUS_ACTIVE + " or " + STATUS_SUSPENDED)

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is None:
            return err_response(msg="No member found with key " + key, code=404)

        old_status = member.status if member.status is not None else STATUS_SUSPENDED
        activated = old_status == STATUS_SUSPENDED and status == STATUS_ACTIVE
        deactivated = old_status == STATUS_ACTIVE and status == STATUS_SUSPENDED

        if activated or deactivated:
            member.status = status
            db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


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
class SelfTest(Resource):

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

        db.session.query(Member_db).filter(Member_db.id == member.id). \
            update({Member_db.public_ssh_key: file_lines,
                    Member_db.public_ssh_key_name: f.filename,
                    Member_db.public_ssh_key_modified_date: datetime.utcnow()})

        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))

    @login_required
    def delete(self):
        member = get_authorized_user()

        db.session.query(Member_db).filter(Member_db.id == member.id). \
            update({Member_db.public_ssh_key: '',
                    Member_db.public_ssh_key_name: '',
                    Member_db.public_ssh_key_modified_date: datetime.utcnow()})

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


@ns.route('/self/awsAccess/requesterPaysBucket')
class AwsAccessRequesterPaysBucket(Resource):

    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)

    @login_required
    @api.expect(expiration_param)
    def get(self):

        member = get_authorized_user()

        expiration = request.args['exp']
        sts_client = boto3.client('sts')
        assumed_role_object = sts_client.assume_role(
            DurationSeconds=int(expiration),
            RoleArn=settings.AWS_REQUESTER_PAYS_BUCKET_ARN,
            RoleSessionName="MAAP-session-" + member.username
        )
        credentials = assumed_role_object['Credentials']

        response = jsonify(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )

        response.headers.add('Access-Control-Allow-Origin', '*')

        return response


@ns.route('/self/awsAccess/edcCredentials/<string:endpoint_uri>')
class AwsAccessEdcCredentials(Resource):
    """
    Earthdata Cloud Temporary s3 Credentials

        Obtain temporary s3 credentials to access Earthdata Cloud resources

        Example:
        https://api.maap-project.org/api/self/edcCredentials/https%3A%2F%2Fdata.lpdaac.earthdatacloud.nasa.gov%2Fs3credentials
    """
    @login_required
    def get(self, endpoint_uri):

        s = requests.Session()
        maap_user = get_authorized_user()

        if maap_user is None:
            return Response('Unauthorized', status=401)
        else:
            urs_token = db.session.query(Member_db).filter_by(id=maap_user.id).first().urs_token
            s.headers.update({'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
                              'Connection': 'close'})

            endpoint = parse.unquote(endpoint_uri)
            login_resp = s.get(
                endpoint, allow_redirects=False
            )
            login_resp.raise_for_status()

            edl_response = s.get(url=login_resp.headers['location'])
            json_response = json.loads(edl_response.content)

            response = jsonify(
                accessKeyId=json_response['accessKeyId'],
                secretAccessKey=json_response['secretAccessKey'],
                sessionToken=json_response['sessionToken'],
                expiration=json_response['expiration']
            )

            response.headers.add('Access-Control-Allow-Origin', '*')

            return response






