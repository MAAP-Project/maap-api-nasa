import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
import api.utils.job_id_store as db
import api.utils.hysds_util as hysds
import api.utils.ogc_translate as ogc
import json
import traceback
import uuid

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

        try:
            response = hysds.mozart_submit_job(job_type=job_type, params=params)
            logging.info("Mozart Response: {}".format(json.dumps(response)))
            job_id = response.get("result")
            if job_id is not None:
                logging.info("Submitted Job with HySDS ID: {}".format(job_id))
                local_id = str(uuid.uuid4())
                db.add_record(local_id, job_id)
                return Response(ogc.execute_response(job_id=local_id, output=output), mimetype='text/xml')
            else:
                raise Exception(response.get("message"))
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to submit job of type {}. Exception Message: {}".format(job_type, ex)),
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
                                              ex_message="Failed to get server capabilities. {}. {}"
                                              .format(ex.message, tb)),
                            mimetype='text/xml')


@ns.route('/job/<string:job_id>')
class Result(Resource):
    def get(self, job_id):
        """
        This will return the result of the job that successfully completed
        :return:
        """
        try:
            #request_xml = request.data
            #job_id = ogc.parse_result_request(request_xml)
            prod_list = list()
            logging.info("Finding result of job with id {}".format(job_id))
            mozart_job_id = db.get_mozart_id(job_id)
            logging.info("Retrieved Mozart job id: {}".format(mozart_job_id))
            response = hysds.get_mozart_job_info(mozart_job_id)
            job_info = response.get("job").get("job_info").get("metrics").get("products_staged")
            if job_info is not None:
                for product in job_info:
                    prod = dict()
                    prod["urls"] = product.get("urls")
                    clickable_url = "https://s3.console.aws.amazon.com/s3/buckets/"
                    for url in prod["urls"]:
                        if url.startswith("s3://"):
                            clickable_url += url.split(":80/")[1] + "/?region=us-east-1&tab=overview"
                    prod["urls"].append(clickable_url)
                    prod["id"] = product.get("id")
                    prod_list.append(prod)
            return Response(ogc.result_response(job_id=job_id, job_result=prod_list), mimetype='text/xml')
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetResult", origin_process="GetResult",
                                              ex_message="Failed to get job result of job with id: {}. " \
                                                         "{}. If you don't see expected results," \
                                                         " please contact administrator " \
                                                         "of DPS".format(job_id, ex)), mimetype='text/xml')


@ns.route('/job/<string:job_id>/status')
class Status(Resource):

    def get(self, job_id):
        """This will return run status of a job given a job id
        :return:
        """
        # request_xml = request.data
        # job_id = ogc.parse_status_request(request_xml)
        try:
            logging.info("Finding status of job with id {}".format(job_id))
            mozart_job_id = db.get_mozart_id(job_id)
            logging.info("Retrieved Mozart job id: {}".format(mozart_job_id))
            response = hysds.mozart_job_status(job_id=mozart_job_id)
            job_status = response.get("status")
            logging.info("Found Job Status: {}".format(job_status))
            response_body = ogc.status_response(job_id=job_id, job_status=job_status)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetStatus", origin_process="GetStatus",
                                              ex_message="Failed to get job status of job with id: {}. " \
                                              "Please check back a little later for " \
                                              "job execution status. If still not found," \
                                              " please contact administrator " \
                                              "of DPS".format(job_id)), mimetype='text/xml')





