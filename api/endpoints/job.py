import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
import api.utils.job_id_store as db
import api.utils.hysds_util as hysds
import api.utils.ogc_translate as ogc
import traceback

log = logging.getLogger(__name__)

ns = api.namespace('dps', description='Operations to interface with HySDS Mozart')


@ns.route('/job')
class Submit(Resource):

    def post(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        Based on OGC Standard of wps:Execute
        :return:
        """
        request_xml = request.data
        job_type, params, output = ogc.parse_execute_request(request_xml)
        response_body = dict()

        try:
            response = hysds.mozart_submit_job(job_type=job_type, params=params)
            job_id = response.get("result")
            return Response(ogc.execute_response(job_id=job_id, output=output), mimetype='text/xml')
        except Exception as ex:
            response_body["code"] = 500
            response_body["message"] = "Failed to submit job of type {}".format(job_type)
            response_body["error"] = ex.message
            response_body["success"] = False
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to submit job of type {}".format(job_type)),
                            mimetype='text/xml')

    def get(self):
        """
        This will request information about the server's capabilities and processes offered
        :return:
        """

        try:
            response_body = ogc.get_capabilities()
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedGetCapabilities", origin_process="GetCapabilities",
                                     ex_message="Failed to get server capabilities. {}. {}".format(ex.message, tb)),
                            mimetype='text/xml')


@ns.route('/job/<string:job_id>')
class Status(Resource):

    def get(self, job_id):
        """This will return run status of a job given a job id
        :return:
        """
        # request_xml = request.data
        # job_id = ogc.parse_status_request(request_xml)
        try:
            print(job_id)
            mozart_job_id = db.get_mozart_id(job_id)
            response = hysds.mozart_job_status(job_id=mozart_job_id)
            job_status = response.get("status")
            response_body = ogc.status_response(job_id=job_id, job_status=job_status)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetStatus", origin_process="GetStatus",
                                              ex_message="Failed to get job status of job with id: {}. " \
                                              "Algorithm registration is in progress. " \
                                              "Please check back a little later for " \
                                              "job execution status. If still not found," \
                                              " please check CI for " \
                                              "a successful job".format(job_id)), mimetype='text/xml')

