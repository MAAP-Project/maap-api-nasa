import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
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
        job_type, params, output, dedup = ogc.parse_execute_request(request_xml)

        try:
            if dedup is None:
                response = hysds.mozart_submit_job(job_type=job_type, params=params)
            else:
                response = hysds.mozart_submit_job(job_type=job_type, params=params, dedup= dedup)
            logging.info("Mozart Response: {}".format(json.dumps(response)))
            job_id = response.get("result")
            if job_id is not None:
                logging.info("Submitted Job with HySDS ID: {}".format(job_id))
                return Response(ogc.execute_response(job_id=job_id, output=output), mimetype='text/xml')
            else:
                raise Exception(response.get("message"))
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to submit job of type {}. Exception Message: {}".format(job_type, ex)),
                            mimetype='text/xml'), 500

    def get(self):
        """
        This will request information about the server's capabilities and processes offered
        :return:
        """

        try:
            job_list = hysds.get_algorithms()
            response_body = ogc.get_capabilities(job_list)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedGetCapabilities", origin_process="GetCapabilities",
                                              ex_message="Failed to get server capabilities. {}. {}"
                                              .format(ex.message, tb)),
                            mimetype='text/xml'), 500


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
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            response = hysds.get_mozart_job_info(job_id)
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
                                                         "of DPS".format(job_id, ex)), mimetype='text/xml'), 500

    def delete(self, job_id):
        """
        This will delete a job from the DPS
        It submits a lightweight HySDS job of type purge to delete a job.
        :param self:
        :param job_id:
        :return:
        """
        try:
            # set job type for removing a job
            not_found_string = "404 Client Error"
            response = hysds.delete_mozart_job(job_id=job_id)
            logging.info("Purge Job Submission Response: {}".format(json.dumps(response)))
            purge_id = response.get("result")
            if job_id is not None:
                # poll until purge job is completed
                poll = True
                while poll:
                    res = hysds.mozart_job_status(job_id=purge_id)
                    job_status = res.get("status")
                    if job_status == "failed":
                        logging.info("Failed to complete purge job for job {}. Job ID of purge job is {}"
                                     .format(job_id, purge_id))
                        raise Exception("Failed to complete purge job for job {}. Job ID of purge job is {}"
                                        .format(job_id, purge_id))
                    if job_status != "queued" and job_status != "started":
                        poll = True
                # verify if job is deleted
                job_response = hysds.mozart_job_status(job_id)
                if not_found_string in job_response.get("message") or job_response.get("success") == False:
                    # this means the job has been deleted.
                    return Response(ogc.execute_response(job_id=job_id, output=output), mimetype='text/xml')
                else:
                    return Response(ogc.get_exception(type="FailedJobDismiss", origin_process="Dismiss",
                                                      ex_message="Failed to dismiss job {}. Please try again or "
                                                                 "contact DPS administrator".format(job_id)),
                                    mimetype='text/xml'), 500
            else:
                raise Exception(response.get("message"))
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to dismiss job {}. Please try again or "
                                                         "contact DPS administrator".format(job_id)),
                            mimetype='text/xml'), 500


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
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            response = hysds.mozart_job_status(job_id=job_id)
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
                                              "of DPS".format(job_id)), mimetype='text/xml'), 500


@ns.route('/job/<string:username>/list')
class Jobs(Resource):

    def get(self, username):
        """
        This will return run a list of jobs for a specified user
        :return:
        """
        # request_xml = request.data
        # job_id = ogc.parse_status_request(request_xml)
        try:
            logging.info("Finding jobs for user: {}".format(username))
            response = hysds.get_mozart_jobs(username=username)
            job_list = response.get("result")
            logging.info("Found Jobs: {}".format(job_list))
            response_body = dict()
            response_body["code"] = 200
            response_body["jobs"] = job_list
            response_body["message"] = "success"
            return response_body
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetJobs", origin_process="GetJobs",
                                              ex_message="Failed to get jobs for user {}. " \
                                              " please contact administrator " \
                                              "of DPS".format(username)), mimetype='text/xml'), 500






