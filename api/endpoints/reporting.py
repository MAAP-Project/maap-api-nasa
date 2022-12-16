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
from datetime import timedelta
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
    parser = api.parser()
    parser.add_argument('start', required=False, type=str,
                        help="Report start date")
    parser.add_argument('end', required=False, type=str,
                        help="Report end date")

    @login_required
    def get(self):

        start = request.form.get('start', request.args.get('start', datetime.now() + timedelta(days=-8)))
        end = request.form.get('end', request.args.get('end', datetime.now() + timedelta(days=1)))

        if not isinstance(start, str):
            start = start.strftime('%Y-%m-%d')

        if not isinstance(end, str):
            end = end.strftime('%Y-%m-%d')

        athena_client = pythena.Athena("maap_logging")

        usage = athena_client.execute(f"""
            select 
                date_format(u.logged, '%Y-%m-%d') as log_dt, 
                COUNT(DISTINCT workspace) as workspace_cont, 
                COUNT(DISTINCT err.logged) as error_cont, 
                count(*) as log_ct
            from ade_usage u left join ade_errors err 
                on date_format(u.logged, '%Y-%m-%d') = date_format(err.logged, '%Y-%m-%d')
            where u.logged between timestamp '{start}' and timestamp '{end}'
            group by date_format(u.logged, '%Y-%m-%d')
            order by date_format(u.logged, '%Y-%m-%d')""")[0]

        tuples = list(usage.itertuples(index=False, name=None))
        report = [{"date": d, "workspaces": w, "errors": e} for d, w, e, c in tuples]
        return report


@ns.route('/ade-metrics')
class AdeUsage(Resource):
    parser = api.parser()
    parser.add_argument('start', required=False, type=str,
                        help="Report start date")
    parser.add_argument('end', required=False, type=str,
                        help="Report end date")

    @login_required
    def get(self):

        start = request.form.get('start', request.args.get('start', datetime.now() + timedelta(hours=-8)))
        end = request.form.get('end', request.args.get('end', datetime.now() + timedelta(hours=1)))

        if not isinstance(start, str):
            start = start.strftime('%Y-%m-%d %H:%M:%S')

        if not isinstance(end, str):
            end = end.strftime('%Y-%m-%d %H:%M:%S')

        athena_client = pythena.Athena("maap_logging")

        usage = athena_client.execute(f"""
            select 
                date_format(u.logged, '%Y-%m-%d-%h') as log_dt,
                AVG(cpu) as cpu, 
                AVG(memory) as memory, 
                COUNT(DISTINCT err.logged) as error_cont, 
                count(*) as log_ct
            from ade_usage u left join ade_errors err 
                on date_format(u.logged, '%Y-%m-%d-%h') = date_format(err.logged, '%Y-%m-%d-%h')
            where u.logged between timestamp '{start}' and timestamp '{end}'
            group by date_format(u.logged, '%Y-%m-%d-%h')
            order by date_format(u.logged, '%Y-%m-%d-%h')""")[0]

        tuples = list(usage.itertuples(index=False, name=None))
        report = [{"date": d, "cpu": w, "memory": e, "errors": c} for d, w, e, c, h in tuples]
        return report






