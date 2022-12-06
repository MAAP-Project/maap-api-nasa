import logging
from flask_restx import Resource, reqparse
from flask import request, jsonify, Response
from api.restplus import api
import api.settings as settings
from api.cas.cas_auth import get_authorized_user, login_required, dps_authorized, get_dps_user
from api.maap_database import db
from api.utils import github_util
from api.models.member import Member as Member_db, MemberSchema
from datetime import datetime
import json
import boto3
import requests
from urllib import parse
import pythena


log = logging.getLogger(__name__)
ns = api.namespace('reports', description='MAAP metrics and reports')
s3_client = boto3.client('s3', region_name=settings.AWS_REGION)


def err_response(msg, code=400):
    return {
        'code': code,
        'message': msg
    }, code


@ns.route('/ade-usage')
class AdeUsage(Resource):

    @login_required
    def get(self):
        athena_client = pythena.Athena("mydatabase")

        # Returns results as a pandas dataframe
        df = athena_client.execute("select * from mytable")

        print(df.sample(n=2))  # Prints 2 rows from your dataframe

        member_schema = MemberSchema()
        result = [json.loads(member_schema.dumps(m)) for m in members]
        return result






