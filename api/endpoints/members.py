import logging
from cachetools import TLRUCache, cached
from flask_restx import Resource, reqparse
from flask import request, jsonify, Response
from api.restplus import api
import api.settings as settings
from api.cas.cas_auth import get_authorized_user, login_required
from api.maap_database import db
from api.utils import github_util
from api.models.member import Member as Member_db
from api.schemas.member_schema import MemberSchema
from api.utils.email_util import send_user_status_update_active_user_email, \
    send_user_status_update_suspended_user_email, send_user_status_change_email, \
    send_welcome_to_maap_active_user_email, send_welcome_to_maap_suspended_user_email
from api.models.pre_approved import PreApproved
from api.schemas.pre_approved_schema import PreApprovedSchema
from datetime import datetime, timedelta, timezone
import json
import boto3
import requests
from urllib import parse
from api.utils.url_util import proxied_url


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


@ns.route('')
class Member(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self):
        members = db.session.query(
            Member_db.id,
            Member_db.username,
            Member_db.first_name,
            Member_db.last_name,
            Member_db.email,
            Member_db.status,
            Member_db.creation_date
        ).order_by(Member_db.username).all()

        member_schema = MemberSchema()
        result = [json.loads(member_schema.dumps(m)) for m in members]
        return result


@ns.route('/<string:key>')
class Member(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self, key):

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is None:
            return err_response(msg="No member found with key " + key, code=404)

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))

    @api.doc(security='ApiKeyAuth')
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
            "public_ssh_key_name": ""
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

        pre_approved_email = db.session.query(PreApproved).filter(
            (PreApproved.email.like("*%") & PreApproved.email.like("%" + email[1:])) |
            (~PreApproved.email.like("*%") & PreApproved.email.like(email))
        ).first()

        status = STATUS_SUSPENDED if pre_approved_email is None else STATUS_ACTIVE

        guest = Member_db(first_name=first_name,
                          last_name=last_name,
                          username=key,
                          email=email,
                          organization=req_data.get("organization", None),
                          public_ssh_key=req_data.get("public_ssh_key", None),
                          public_ssh_key_modified_date=datetime.utcnow(),
                          public_ssh_key_name=req_data.get("public_ssh_key_name", None),
                          status=status,
                          creation_date=datetime.utcnow())

        db.session.add(guest)
        db.session.commit()

        # Send Email Notifications based on member status
        if status == STATUS_ACTIVE:
            send_user_status_change_email(guest, True, True, proxied_url(request))
            send_welcome_to_maap_active_user_email(guest, proxied_url(request))
        else:
            send_user_status_change_email(guest, True, False, proxied_url(request))
            send_welcome_to_maap_suspended_user_email(guest, proxied_url(request))

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(guest))

    @api.doc(security='ApiKeyAuth')
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
            "public_ssh_key_name": ""
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
        db.session.commit()

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


@ns.route('/<string:key>/status')
class MemberStatus(Resource):

    @api.doc(security='ApiKeyAuth')
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
            gitlab_account = github_util.sync_gitlab_account(
                activated,
                member.username,
                member.email,
                member.first_name,
                member.last_name)

            if gitlab_account is not None:
                # A gitlab account was created, so update the member profile.
                member.gitlab_id = gitlab_account["gitlab_id"]
                member.gitlab_token = gitlab_account["gitlab_token"]
                member.gitlab_username = member.username
                db.session.commit()

        # Send "Account Activated" email notification to Member & Admins
        if activated:
            send_user_status_update_active_user_email(member, proxied_url(request))
            send_user_status_change_email(member, False, True, proxied_url(request))

        # Send "Account Deactivated" email notification to Member & Admins
        if deactivated:
            send_user_status_update_suspended_user_email(member, proxied_url(request))
            send_user_status_change_email(member, False, False, proxied_url(request))

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


@ns.route('/self')
class Self(Resource):

    @api.doc(security='ApiKeyAuth')
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

    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self):
        member = get_authorized_user()
        member_schema = MemberSchema()

        return json.loads(member_schema.dumps(member))


@ns.route('/self/sshKey')
class PublicSshKeyUpload(Resource):

    @api.doc(security='ApiKeyAuth')
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

    @api.doc(security='ApiKeyAuth')
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

    @api.doc(security='ApiKeyAuth')
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


@ns.route('/self/awsAccess/requesterPaysBucket')
class AwsAccessRequesterPaysBucket(Resource):

    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)

    @api.doc(security='ApiKeyAuth')
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
    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self, endpoint_uri):
        maap_user = get_authorized_user()

        if not maap_user:
            return Response('Unauthorized', status=401)

        creds = get_edc_credentials(endpoint_uri, maap_user)

        response = jsonify(
            accessKeyId=creds['accessKeyId'],
            secretAccessKey=creds['secretAccessKey'],
            sessionToken=creds['sessionToken'],
            expiration=creds['expiration']
        )

        response.headers.add('Access-Control-Allow-Origin', '*')

        return response


def creds_expiration_utc(_key, creds, now_utc: datetime) -> datetime:
    """Return the UTC time that is halfway between now and the expiration time
    of a credentials object.

    Assume ``creds`` is an object containing the key ``'expiration'`` associated
    to a ``str`` value representing the expiration date/time of the credentials
    in the format ``'%Y-%m-%d %H:%M:%S%z'``.

    If there is no such key, or the associated value cannot be successfully
    parsed into a ``datetime`` value using the format above, return ``now_utc``.
    Otherwise, return a datetime value halfway between ``now_utc`` and the
    parsed expiration value (converted to UTC).

    Note that if the parsed value is prior to ``now_utc``, the returned value
    will also be prior to ``now_utc``, halfway between both values.
    """

    try:
        expiration = creds['expiration']
        expiration_dt = datetime.strptime(expiration, "%Y-%m-%d %H:%M:%S%z")
        expiration_dt_utc = expiration_dt.astimezone(timezone.utc)
    except (KeyError, ValueError):
        expiration_dt_utc = now_utc

    # Expire creds in half the actual expiration time
    return expiration_dt_utc - (expiration_dt_utc - now_utc) / 2


def now_utc() -> datetime:
    """Return the current datetime value in UTC."""
    return datetime.now(timezone.utc)


@cached(TLRUCache(ttu=creds_expiration_utc, timer=now_utc, maxsize=None))
def get_edc_credentials(endpoint_uri, user):
    """Get EDC credentials for a user from an endpoint.

    Credentials are cached for the given endpoint and user for half the time the
    credentials are valid to avoid unnecessary generation of new credentials and
    to minimize load on the endpoint, while also ensuring reasonable "freshness".
    """
    urs_token = db.session.query(Member_db).filter_by(id=user.id).first().urs_token

    with requests.Session() as s:
        s.headers.update(
            {
                'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
                'Connection': 'close'
            }
        )

        endpoint = parse.unquote(endpoint_uri)
        login_resp = s.get(endpoint, allow_redirects=False)
        login_resp.raise_for_status()

        edl_response = s.get(url=login_resp.headers['location'])

        return json.loads(edl_response.content)


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

        return {"code": 200, "message": "Successfully deleted {}.".format(email)}
