import logging
from cachetools import TLRUCache, cached
from flask_restx import Resource, reqparse
from flask import request, jsonify, Response, current_app as app
from flask_api import status
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, Unauthorized, ServiceUnavailable
from api.utils.organization import get_member_organizations
from api.models.role import Role
from api.restplus import api
import api.settings as settings
from api.auth.security import get_authorized_user, login_required, valid_dps_request, edl_federated_request, \
    MEMBER_STATUS_ACTIVE, MEMBER_STATUS_SUSPENDED
from api.maap_database import db
from api.utils import github_util
from api.models.member import Member as Member_db
from api.models.member_session import MemberSession as MemberSession_db
from api.models.member_secret import MemberSecret as MemberSecret_db
from api.schemas.member_schema import MemberSchema
from api.schemas.member_session_schema import MemberSessionSchema
from api.utils.security_utils import validate_ssh_key_file, sanitize_filename, InvalidFileTypeError, FileSizeTooLargeError, EmptyFileError
from api.utils.email_util import send_user_status_update_active_user_email, \
    send_user_status_update_suspended_user_email, send_user_status_change_email, \
    send_welcome_to_maap_active_user_email, send_welcome_to_maap_suspended_user_email
from api.endpoints import get_config_from_api
from api.models.pre_approved import PreApproved
from datetime import datetime, timezone
import json
import boto3
import requests
from urllib import parse

from api.utils.http_util import err_response, custom_response
from api.utils.url_util import proxied_url
from cryptography.fernet import Fernet

log = logging.getLogger(__name__)
ns = api.namespace('members', description='Operations for MAAP members')
s3_client = boto3.client('s3', region_name=settings.AWS_REGION)
sts_client = boto3.client('sts', region_name=settings.AWS_REGION)
fernet = Fernet(settings.FERNET_KEY)


@ns.route('')
class Member(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):

        member_query = db.session.query(
            Member_db, Role,
        ).filter(
            Member_db.role_id == Role.id
        ).order_by(Member_db.username).all()

        result = [{
            'id': m.Member.id,
            'username': m.Member.username,
            'first_name': m.Member.first_name,
            'last_name': m.Member.last_name,
            'email': m.Member.email,
            'role_id': m.Member.role_id,
            'role_name': m.Role.role_name,
            'status': m.Member.status,
            'creation_date': m.Member.creation_date.strftime('%m/%d/%Y'),
        } for m in member_query]

        return result


@ns.route('/<string:key>')
class Member(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, key):

        cols = [
            Member_db.id,
            Member_db.username,
            Member_db.first_name,
            Member_db.last_name,
            Member_db.email,
            Member_db.status,
            Member_db.public_ssh_key,
            Member_db.creation_date
        ]

        member = db.session \
            .query(Member_db) \
            .with_entities(*cols) \
            .filter_by(username=key) \
            .first()

        if member is None:
            return err_response(msg="No member found with key " + key, code=status.HTTP_404_NOT_FOUND)

        member_id = member.id
        member_schema = MemberSchema()
        result = json.loads(member_schema.dumps(member))

        # If the request originates from the logged-in user or DPS worker,
        # include additional profile information belonging to the user
        if valid_dps_request() or member.username == key:
            pgt_ticket = db.session \
                .query(MemberSession_db) \
                .with_entities(MemberSession_db.session_key) \
                .filter_by(member_id=member_id) \
                .order_by(MemberSession_db.id.desc()) \
                .first()

            cols = [
                Member_db.public_ssh_key_name,
                Member_db.public_ssh_key_modified_date
            ]

            member = db.session \
                .query(Member_db) \
                .with_entities(*cols) \
                .filter_by(username=member.username) \
                .first()

            member_session_schema = MemberSessionSchema()
            pgt_result = json.loads(member_session_schema.dumps(pgt_ticket))
            member_ssh_info_result = json.loads(member_schema.dumps(member))
            result = json.loads(json.dumps(dict(result.items() | pgt_result.items() | member_ssh_info_result.items())))

        result['organizations'] = get_member_organizations(member_id)

        return result

    @api.doc(security='ApiKeyAuth')
    @login_required()
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

        member_status = MEMBER_STATUS_SUSPENDED if pre_approved_email is None else MEMBER_STATUS_ACTIVE

        guest = Member_db(first_name=first_name,
                          last_name=last_name,
                          username=key,
                          email=email,
                          organization=req_data.get("organization", None),
                          public_ssh_key=req_data.get("public_ssh_key", None),
                          public_ssh_key_modified_date=datetime.utcnow(),
                          public_ssh_key_name=req_data.get("public_ssh_key_name", None),
                          status=member_status,
                          creation_date=datetime.utcnow())

        try:
            db.session.add(guest)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to create member: {e}")
            raise

        # Send Email Notifications based on member status
        if member_status == MEMBER_STATUS_ACTIVE:
            send_user_status_change_email(guest, True, True, proxied_url(request))
            send_welcome_to_maap_active_user_email(guest, proxied_url(request))
        else:
            send_user_status_change_email(guest, True, False, proxied_url(request))
            send_welcome_to_maap_suspended_user_email(guest, proxied_url(request))

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(guest))

    @api.doc(security='ApiKeyAuth')
    @login_required()
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
        member.role_id = req_data.get("role_id", member.role_id)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to update member {member.id}: {e}")
            raise

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


@ns.route('/<string:key>/status')
class MemberStatus(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
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

        member_status = req_data.get("status", "")
        if not isinstance(member_status, str) or not member_status:
            return err_response("Valid status string required.")

        if member_status != MEMBER_STATUS_ACTIVE and member_status != MEMBER_STATUS_SUSPENDED:
            return err_response("Status must be either " + MEMBER_STATUS_ACTIVE + " or " + MEMBER_STATUS_SUSPENDED)

        member = db.session.query(Member_db).filter_by(username=key).first()

        if member is None:
            return err_response(msg="No member found with key " + key, code=404)

        old_status = member.status if member.status is not None else MEMBER_STATUS_SUSPENDED
        activated = old_status == MEMBER_STATUS_SUSPENDED and member_status == MEMBER_STATUS_ACTIVE
        deactivated = old_status == MEMBER_STATUS_ACTIVE and member_status == MEMBER_STATUS_SUSPENDED

        if activated or deactivated:
            member.status = member_status
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Failed to update member status {member.id}: {e}")
                raise
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
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Failed to update member gitlab info {member.id}: {e}")
                    raise

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
    @login_required()
    def get(self):
        authorized_user = get_authorized_user()

        cols = [
            Member_db.id,
            Member_db.username,
            Member_db.first_name,
            Member_db.last_name,
            Member_db.email,
            Member_db.status,
            Member_db.public_ssh_key,
            Member_db.public_ssh_key_name,
            Member_db.public_ssh_key_modified_date,
            Member_db.creation_date
        ]

        member = db.session \
            .query(Member_db) \
            .with_entities(*cols) \
            .filter_by(username=authorized_user.username) \
            .first()

        pgt_ticket = db.session \
            .query(MemberSession_db) \
            .with_entities(MemberSession_db.session_key) \
            .filter_by(member_id=member.id) \
            .order_by(MemberSession_db.id.desc()) \
            .first()

        member_session_schema = MemberSessionSchema()
        member_schema = MemberSchema()
        pgt_result = json.loads(member_session_schema.dumps(pgt_ticket))
        member_result = json.loads(member_schema.dumps(member))
        result = json.loads(json.dumps(dict(member_result.items() | pgt_result.items())))

        if 'proxy-ticket' in request.headers:
            result['organizations'] = get_member_organizations(member.id)
            return result

        if 'Authorization' in request.headers:
            return member


@ns.route('/self/sshKey')
class PublicSshKeyUpload(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        if 'file' not in request.files:
            log.error('Upload attempt with no file')
            # Use a more specific error from werkzeug.exceptions or our custom ones
            raise BadRequest('No file uploaded.')

        member = get_authorized_user()
        f = request.files['file']

        # Sanitize filename first
        safe_filename = sanitize_filename(f.filename)

        try:
            # Validate the file (type, size, content)
            validate_ssh_key_file(f, settings.MAX_SSH_KEY_SIZE_BYTES, settings.ALLOWED_SSH_KEY_EXTENSIONS)
            # f.seek(0) # validate_ssh_key_file should reset seek(0) if it reads

            file_content = f.read().decode("utf-8") # Read after validation

            db.session.query(Member_db).filter(Member_db.id == member.id). \
                update({Member_db.public_ssh_key: file_content,
                        Member_db.public_ssh_key_name: safe_filename, # Use sanitized filename
                        Member_db.public_ssh_key_modified_date: datetime.utcnow()})
            db.session.commit()

            # Re-fetch member to get updated data for the response
            updated_member = db.session.query(Member_db).filter_by(id=member.id).first()
            member_schema = MemberSchema()
            return json.loads(member_schema.dumps(updated_member))

        except (InvalidFileTypeError, FileSizeTooLargeError, EmptyFileError) as e:
            log.error(f"SSH key upload validation failed for member {member.id}: {e.description}")
            # These exceptions are already werkzeug HTTPExceptions, so they will be handled by Flask/RestX
            raise e
        except UnicodeDecodeError:
            log.error(f"SSH key for member {member.id} is not valid UTF-8 text.")
            raise BadRequest("File content is not valid UTF-8 text.")
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"Database error updating SSH key for member {member.id}: {e}")
            # For database errors, we might want a more generic server error
            # Or a specific error if api.restplus handles SQLAlchemyError specifically
            raise ServiceUnavailable("Could not save SSH key due to a database error.")
        except Exception as e:
            db.session.rollback() # Ensure rollback for any other unexpected error
            log.error(f"Unexpected error updating SSH key for member {member.id}: {e}")
            # Fallback for truly unexpected errors
            raise ServiceUnavailable("An unexpected error occurred while saving the SSH key.")


    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self):
        member = get_authorized_user()

        try:
            db.session.query(Member_db).filter(Member_db.id == member.id). \
                update({Member_db.public_ssh_key: '',
                        Member_db.public_ssh_key_name: '',
                        Member_db.public_ssh_key_modified_date: datetime.utcnow()})
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to delete SSH key for member {member.id}: {e}")
            raise

        member_schema = MemberSchema()
        return json.loads(member_schema.dumps(member))


@ns.route('/self/secrets')
class Secrets(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):

        try:
            secrets = \
                (
                    db.session.query(
                        MemberSecret_db.secret_name,
                        MemberSecret_db.secret_value)
                    .filter_by(member_id=get_authorized_user().id)
                    .order_by(MemberSecret_db.secret_name)
                    .all())

            result = [{
                'secret_name': s.secret_name
            } for s in secrets]

            return result
        except SQLAlchemyError as ex:
            return err_response(ex, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):

        try:
            req_data = request.get_json()
            if not isinstance(req_data, dict):
                return err_response("Valid JSON body object required.")

            secret_name = req_data.get("secret_name", "")
            if not isinstance(secret_name, str) or not secret_name:
                return err_response("secret_name is required.")

            secret_value = req_data.get("secret_value", "")
            if not isinstance(secret_value, str) or not secret_value:
                return err_response("secret_value is required.")

            member = get_authorized_user()
            secret = db.session.query(MemberSecret_db).filter_by(member_id=member.id, secret_name=secret_name).first()

            if secret is not None:
                return err_response(msg="Secret already exists with name {}. Please delete and re-create the secret to update it's value. ".format(secret_name))

            encrypted_secret = fernet.encrypt(secret_value.encode()).decode("utf-8")

            new_secret = MemberSecret_db(member_id=member.id,
                                         secret_name=secret_name,
                                         secret_value=encrypted_secret,
                                         creation_date=datetime.utcnow())

            db.session.add(new_secret)
            db.session.commit()

            return {
                'secret_name': secret_name
            }, status.HTTP_200_OK

        except SQLAlchemyError as ex:
            return err_response(ex, status.HTTP_500_INTERNAL_SERVER_ERROR)


@ns.route('/self/secrets/<string:name>')
class Secrets(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, name):

        try:
            secret = \
                (
                    db.session.query(
                        MemberSecret_db.secret_name,
                        MemberSecret_db.secret_value)
                    .filter_by(member_id=get_authorized_user().id, secret_name=name)
                    .first())

            if secret is None:
                return err_response(msg="No secret exists with name {}".format(name), code=status.HTTP_404_NOT_FOUND)

            result = {
                'secret_name': secret.secret_name,
                'secret_value': fernet.decrypt(secret.secret_value).decode("utf-8")
            }

            return result, status.HTTP_200_OK

        except SQLAlchemyError as ex:
            return err_response(ex, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, name):

        try:
            member = get_authorized_user()
            secret = db.session.query(MemberSecret_db).filter_by(member_id=member.id, secret_name=name).first()

            if secret is None:
                return err_response(msg="No secret exists with name " + name)

            db.session.delete(secret)
            db.session.commit()

            return custom_response("Successfully deleted secret {}".format(name))
        except SQLAlchemyError as ex:
            return err_response(ex, status.HTTP_500_INTERNAL_SERVER_ERROR)


@ns.route('/self/presignedUrlS3/<string:bucket>/<path:key>')
class PresignedUrlS3(Resource):
    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)
    expiration_param.add_argument('ws', type=str, required=False, default="")

    @api.doc(security='ApiKeyAuth')
    @login_required()
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
        elif key.startswith(settings.WORKSPACE_MOUNT_TRIAGE):
            return key.replace(settings.WORKSPACE_MOUNT_TRIAGE, settings.AWS_TRIAGE_WORKSPACE_BUCKET_PATH)
        else:
            return key


@ns.route('/self/awsAccess/requesterPaysBucket')
class AwsAccessRequesterPaysBucket(Resource):
    expiration_param = reqparse.RequestParser()
    expiration_param.add_argument('exp', type=int, required=False, default=60 * 60 * 12)

    @api.doc(security='ApiKeyAuth')
    @login_required()
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
    @login_required()
    def get(self, endpoint_uri):
        s = requests.Session()
        maap_user = get_authorized_user()

        if maap_user is None:
            return Response('Unauthorized', status=status.HTTP_401_UNAUTHORIZED)
        else:
            json_response = get_edc_credentials(endpoint_uri=endpoint_uri, user_id=maap_user.id)

            response = jsonify(
                accessKeyId=json_response['accessKeyId'],
                secretAccessKey=json_response['secretAccessKey'],
                sessionToken=json_response['sessionToken'],
                expiration=json_response['expiration']
            )

            response.headers.add('Access-Control-Allow-Origin', '*')

            return response


@ns.route('/self/awsAccess/workspaceBucket')
class AwsAccessUserBucketCredentials(Resource):
    """
    User Bucket Temporary s3 Credentials

        Obtain temporary s3 credentials to access a user's s3 bucket

        Example:
        https://api.maap-project.org/api/self/awsAccess/workspaceBucket
    """

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):
        maap_user = get_authorized_user()

        if not maap_user:
            return Response('Unauthorized', status=401)

        # Guaranteed to at least always return default 
        config = get_config_from_api(self.request.host)
        workspace_bucket = config["workspace_bucket"]

        # Allow bucket access to just the user's workspace directory
        policy = f'''{{"Version": "2012-10-17",
            "Statement": [
                {{
                    "Sid": "GrantAccessToUserFolder",
                    "Effect": "Allow",
                    "Action": [
                        "s3:ListBucket",
                        "s3:DeleteObject",
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:RestoreObject",
                        "s3:ListMultipartUploadParts",
                        "s3:AbortMultipartUpload"
                    ],
                    "Resource": [
                        "arn:aws:s3:::{workspace_bucket}/{maap_user.username}/*"
                    ]
                }},
                {{
                    "Sid": "GrantListAccess",
                    "Effect": "Allow",
                    "Action": [
                        "s3:ListBucket"
                    ],
                    "Resource": "arn:aws:s3:::{workspace_bucket}",
                    "Condition": {{
                        "StringLike": {{
                            "s3:prefix": [
                                "{maap_user.username}/*"
                            ]
                        }}
                    }}
                }}
            ]
        }}'''

        # Call the assume_role method of the STSConnection object
        assumed_role_object = sts_client.assume_role(
            RoleArn=settings.WORKSPACE_BUCKET_ARN,
            RoleSessionName=f'workspace-session-{maap_user.username}',
            Policy=policy,
            DurationSeconds=(60 * 60)
        )

        response = jsonify(
            aws_bucket_name=workspace_bucket,
            aws_bucket_prefix=maap_user.username,
            aws_access_key_id=assumed_role_object['Credentials']['AccessKeyId'],
            aws_secret_access_key=assumed_role_object['Credentials']['SecretAccessKey'],
            aws_session_token=assumed_role_object['Credentials']['SessionToken'],
            aws_session_expiration=assumed_role_object['Credentials']['Expiration'].strftime("%Y-%m-%d %H:%M:%S%z")
        )

        response.headers.add('Access-Control-Allow-Origin', '*')

        return response


def creds_expiration_utc(_key, creds, now_utc_cred: float) -> float:
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
        expiration_dt_utc = expiration_dt.astimezone(timezone.utc).timestamp() * 1000
    except (KeyError, ValueError):
        expiration_dt_utc = now_utc_cred

    # Expire creds in half the actual expiration time
    return expiration_dt_utc - (expiration_dt_utc - now_utc_cred) / 2


def now_utc() -> float:
    """Return the current datetime value in UTC."""
    return datetime.now(timezone.utc).timestamp() * 1000


@cached(TLRUCache(ttu=creds_expiration_utc, timer=now_utc, maxsize=128))
def get_edc_credentials(endpoint_uri, user_id):
    """Get EDC credentials for a user from an endpoint.

    Credentials are cached for the given endpoint and user for half the time the
    credentials are valid to avoid unnecessary generation of new credentials and
    to minimize load on the endpoint, while also ensuring reasonable "freshness".
    """
    urs_token = db.session.query(Member_db).filter_by(id=user_id).first().urs_token

    s = requests.Session()

    s.headers.update(
        {
            'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
            'Connection': 'close'
        }
    )

    endpoint = parse.unquote(endpoint_uri)
    login_resp = s.get(endpoint, allow_redirects=False)

    if login_resp.status_code == status.HTTP_307_TEMPORARY_REDIRECT:
        edl_response = s.get(url=login_resp.headers['location'])
    else:
        edl_response = edl_federated_request(url=endpoint)

    return edl_response.json()