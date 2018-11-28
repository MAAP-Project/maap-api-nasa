import logging
from flask import request
from flask_restplus import Resource
from api.restplus import api
import api.utils.hysds_util as hysds

log = logging.getLogger(__name__)

ns = api.namespace('job', description='Operations to ')


@ns.route('/submit')
class Submit(Resource):

    def post(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        req_data = request.get_json()
        job_type = req_data["job_type"]
        response_body = dict()

        try:
            response_body = hysds.mozart_submit_job(job_type=job_type)
        except Exception as ex:
            response_body["code"] = 500
            response_body["message"] = "Failed to submit job of type {}".format(job_type)
            response_body["error"] = ex.message

        return response_body


@ns.route('/status')
class Status(Resource):

    def get(self):
        """This will return run status of a job given a job id
        :return:
        """
        response_body = dict()
        req_data = request.get_json()
        job_id = req_data["job_id"]

        try:
            response_body = hysds.mozart_job_status(job_id=job_id)
        except Exception as ex:
            response_body["code"] = 500
            response_body["message"] = "Failed to get job status of job with id: {}".format(job_id)
            response_body["error"] = ex.message

        return response_body
