import logging
from flask import request
from flask_restplus import Resource
from api.restplus import api
import api.utils.job_id_store as db
import api.utils.hysds_util as hysds

log = logging.getLogger(__name__)

ns = api.namespace('job', description='Operations to interface with HySDS Mozart')


@ns.route('/submit')
class Submit(Resource):

    def post(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        req_data = request.get_json()
        job_type = req_data["job_type"]
        params = req_data["params"]
        response_body = dict()

        try:
            response = hysds.mozart_submit_job(job_type=job_type, params=params)
            response_body["message"] = "Successfully submitted job of type {}".format(job_type)
            response_body["job_id"] = response.get("result")
            response_body["code"] = 200
            response_body["success"] = True
        except Exception as ex:
            response_body["code"] = 500
            response_body["message"] = "Failed to submit job of type {}".format(job_type)
            response_body["error"] = ex.message
            response_body["success"] = False

        return response_body


@ns.route('/status')
class Status(Resource):
    def get(self):
        """This will return run status of a job given a job id
        :return:
        """
        response_body = dict()
        job_id = request.args.get("job_id")

        try:
            mozart_job_id = db.get_mozart_id(job_id)
            response = hysds.mozart_job_status(job_id=mozart_job_id)
            response_body["message"] = "Successfully got status of job with id {}".format(job_id)
            response_body["job_status"] = response.get("status")
            response_body["code"] = 200
            response_body["success"] = True
        except Exception as ex:
            response_body["code"] = 500
            response_body["message"] = "Failed to get job status of job with id: {}".format(job_id)
            response_body["error"] = ex.message
            response_body["success"] = False

        return response_body
