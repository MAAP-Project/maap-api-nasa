import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
import api.utils.hysds_util as hysds
import api.utils.ogc_translate as ogc
import json
import traceback
from xml.etree.ElementTree import Element, SubElement, Comment, tostring
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
                response = hysds.mozart_submit_job(job_type=job_type, params=params, dedup=dedup)
            logging.info("Mozart Response: {}".format(json.dumps(response)))
            job_id = response.get("result")
            response = hysds.mozart_job_status(job_id=job_id)
            job_status = response.get("status")

            if job_id is not None:
                logging.info("Submitted Job with HySDS ID: {}".format(job_id))
                return Response(ogc.status_response(job_id=job_id, job_status=job_status), mimetype='text/xml')
            else:
                raise Exception(response.get("message"))
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                            ex_message="Failed to submit job of type {}. Exception Message: {}"
                            .format(job_type, ex)), status=500)

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
                            mimetype='text/xml',
                            status=500)


@ns.route('/job/describeprocess/<string:algo_id>')
class Describe(Resource):
    def get(self, algo_id):
        """
        request detailed metadata on selected processes offered by a server
        :return:
        """
        try:
            job_type = "job-{}".format(algo_id)
            response = hysds.get_job_spec(job_type)
            print(json.dumps(response))
            params = response.get("result").get("params")
            response_body = ogc.describe_process_response(algo_id, params)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedDescribeProcess", origin_process="DescribeProcess",
                                              ex_message="Failed to get parameters for algorithm. {} Traceback: {}"
                                              .format(ex, tb)), status=500, mimetype='text/xml')


@ns.route('/job/<string:job_id>')
class Result(Resource):
    def get(self, job_id):
        """
        This will return the result of the job that successfully completed
        :return:
        """
        try:
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
                                                         "of DPS".format(job_id, ex)), mimetype='text/xml', status=500)

    def delete(self, job_id):
        """
        This will delete a job from the DPS
        It submits a lightweight HySDS job of type purge to delete a job.
        :param self:
        :param job_id:
        :return:
        """
        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))
            if current_status == "job-started":
                raise Exception("Cannot delete job with ID: {} in running state.".format(job_id))
            if current_status is None:
                raise Exception("Job with id {} was not found.".format(job_id))
            # submit purge job
            logging.info("Submitting Purge job for Job {}".format(job_id))
            purge_id, res = hysds.delete_mozart_job(job_id=job_id)
            logging.info("Purge Job Submission Response: {}".format(res))
            job_status = res.get("status")
            if job_status == "job-failed" or job_status == "job-revoked" or job_status == "job-offline":
                logging.info("Failed to complete purge job for job {}. Job ID of purge job is {}"
                             .format(job_id, purge_id))
                raise Exception("Failed to complete purge job for job {}. Job ID of purge job is {}"
                                .format(job_id, purge_id))
            # verify if job is deleted
            job_response = hysds.mozart_job_status(job_id)
            logging.info("Checkup on Deleted job. {}".format(job_response.get("success")))
            if job_response.get("status") is None and job_response.get("success") is False:
                # this means the job has been deleted.
                logging.info("Job successfully deleted")
                response = ogc.status_response(job_id=job_id, job_status="Deleted")
                logging.info(response)
                return Response(response=response, mimetype='text/xml')
            else:
                return Response(ogc.get_exception(type="FailedJobDelete", origin_process="Delete",
                                                  ex_message="Failed to delete job {}. Please try again or"
                                                             " contact DPS administrator".format(job_id)),
                                mimetype='text/xml',
                                status=500)
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to delete job {}. Please try again or "
                                                         "contact DPS administrator. {}".format(job_id, ex)),
                            mimetype='text/xml', status=500)


@ns.route('/job/<string:job_id>/status')
class Status(Resource):

    def get(self, job_id):
        """This will return run status of a job given a job id
        :return:
        """
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
                                              "of DPS".format(job_id)), mimetype='text/xml', status=500)


@ns.route('/job/<string:job_id>/metrics')
class Metrics(Resource):

    def get(self, job_id):
        """
        This will return the result of the job that successfully completed
        :return:
        """
        metrics = dict()
        response = dict()
        try:
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            try:
                mozart_response = hysds.get_mozart_job_info(job_id)
            except Exception:
                raise Exception("No job information found for {}. Maybe the job is currently queued or you entered the"
                                "incorrect Job ID."
                                .format(job_id))

            # get all the relevant metrics information
            job_info = mozart_response.get("job").get("job_info")
            job_facts = job_info.get("facts")
            architecture = job_facts.get("architecture")
            os = job_facts.get("operatingsystem")
            memoryfree = job_facts.get("memoryfree")
            memorysize = job_facts.get("memorysize")
            instance_typ = job_facts.get("ec2_instance_type")
            time_start = job_info.get("cmd_start")
            time_end = job_info.get("cmd_end")
            time_duration = job_info.get("cmd_duration")

            # build the metrics object
            """
            <?xml version="1.0" encoding="UTF-8"?>
            <Metrics>
            <machine_type></machine_type>
            <architecture></architecture>
            <machine_memory_size></machine_memory_size>
            <machine_memory_free></machine_memory_free>
            <job_start_time></job_start_time>
            <job_end_time></job_end_time>
            <job_duration_seconds></job_duration_seconds>
            <Metrics>
            """
            xml_response = Element("metrics")
            machine_type = SubElement(xml_response, "machine_type")
            machine_type.text = instance_typ
            arch = SubElement(xml_response, "architecture")
            arch.text = architecture
            machine_memory_size = SubElement(xml_response, "machine_memory_size")
            machine_memory_size.text = str(memorysize)
            machine_memory_free = SubElement(xml_response, "machine_memory_free")
            machine_memory_free.text = str(memoryfree)
            operating_system = SubElement(xml_response, "operating_system")
            operating_system.text = os
            job_start_time = SubElement(xml_response, "job_start_time")
            job_start_time.text = time_start
            job_end_time = SubElement(xml_response, "job_end_time")
            job_end_time.text = time_end
            job_duration_seconds = SubElement(xml_response, "job_duration_seconds")
            job_duration_seconds.text = str(time_duration)

            return Response(tostring(xml_response), mimetype="text/xml", status=200)
        except Exception as ex:
            print("Metrics Exception: {}".format(ex))
            return Response(ogc.get_exception(type="FailedGetMetrics", origin_process="GetMetrics",
                                              ex_message="Failed to get metrics of job {}. {}." \
                                              " please contact administrator " \
                                              "of DPS".format(job_id, ex)), mimetype='text/xml', status=500)


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
            """
                        <?xml version="1.0" encoding="UTF-8"?>
                        <Jobs>
                        <Job>
                            <JobID></JobID>
                            <JobStatus></JobStatus>
                            <JobType></JobType>
                            <JobParams></JobParams>
                        </Job>
                        <Job>...</Job>
                        <Job>...</Job>
                        ...
                        <Jobs>
            """
            return response_body
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetJobs", origin_process="GetJobs",
                                              ex_message="Failed to get jobs for user {}. " \
                                              " please contact administrator " \
                                              "of DPS".format(username)), mimetype='text/xml', status=500)


@ns.route('/job/revoke/<string:job_id>')
class StopJobs(Resource):

    def delete(self, job_id):
        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))
            if current_status != "job-started":
                raise Exception("Cannot revoke job with ID: {} in state other than started.".format(job_id))
            if current_status is None:
                raise Exception("Job with id {} was not found.".format(job_id))
            # submit purge job
            logging.info("Submitting Revoke job for Job {}".format(job_id))
            purge_id, res = hysds.revoke_mozart_job(job_id=job_id)
            logging.info("Revoke Job Submission Response: {}".format(res))
            job_status = res.get("status")
            if job_status == "job-failed" or job_status == "job-revoked" or job_status == "job-offline":
                logging.info("Failed to complete revoke job for job {}. Job ID of revoke job is {}"
                             .format(job_id, purge_id))
                raise Exception("Failed to complete revoke job for job {}. Job ID of revoke job is {}"
                                .format(job_id, purge_id))
            # verify if job is deleted
            job_response = hysds.mozart_job_status(job_id)
            logging.info("Checkup on Revoked job. {}".format(job_response.get("success")))
            if job_response.get("status") == "job-revoked":
                # this means the job has been revoked.
                logging.info("Job successfully revoked")
                response = ogc.status_response(job_id=job_id, job_status="job-revoked")
                logging.info(response)
                return Response(response=response, mimetype='text/xml')
            else:
                return Response(ogc.get_exception(type="FailedJobRevoke", origin_process="Dismiss",
                                                  ex_message="Failed to dismiss job {}. Please try again or"
                                                             " contact DPS administrator".format(job_id)),
                                mimetype='text/xml',
                                status=500)
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to dismiss job {}. Please try again or "
                                                         "contact DPS administrator. {}".format(job_id, ex)),
                            mimetype='text/xml', status=500)







