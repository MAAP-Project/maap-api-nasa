import logging
from flask import request, Response
from flask_restx import Resource
from flask_api import status
from api.restplus import api
import api.utils.hysds_util as hysds
import api.utils.ogc_translate as ogc
import api.settings as settings
try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse
import json
import os
import requests
import traceback
from api.cas.cas_auth import get_authorized_user, login_required
from api.maap_database import db
from api.models.member_job import MemberJob
from api.models.member import Member
from sqlalchemy import or_, and_
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, Comment, tostring, fromstring
import uuid

log = logging.getLogger(__name__)

ns = api.namespace('dps', description='Operations to interface with HySDS Mozart')


@ns.route('/job')
class Submit(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required
    def post(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        Based on OGC Standard of wps:Execute
        :return:
        """
        request_xml = request.data
        job_type, input_params, queue, output, dedup, identifier = ogc.parse_execute_request(request_xml)
        logging.info("Received request for Job Submission")
        logging.info("Job Type: {}".format(job_type))
        logging.info("Input Parameters: {}".format(input_params))
        logging.info("Queue: {}".format(queue))
        logging.info("Output: {}".format(output))
        logging.info("Dedup: {}".format(dedup))
        logging.info("Identifier: {}".format(identifier))

        # validate the inputs provided by user against the registered spec for the job
        try:
            hysdsio_type = job_type.replace("job-", "hysds-io-")
            hysds_io = hysds.get_hysds_io(hysdsio_type)
            logging.info("Found HySDS-IO: {}".format(hysds_io))
            params = hysds.validate_job_submit(hysds_io, input_params)
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                            ex_message="Failed to submit job of type {}. Exception Message: {}"
                            .format(job_type, ex)), status=500)

        try:
            dedup = "false" if dedup is None else dedup
            queue = hysds.get_recommended_queue(job_type=job_type) if queue==None or queue=="" else queue
            response = hysds.mozart_submit_job(job_type=job_type, params=params, dedup=dedup, queue=queue,
                                               identifier=identifier)

            logging.info("Mozart Response: {}".format(json.dumps(response)))
            job_id = response.get("result")
            if job_id is not None:
                logging.info("Submitted Job with HySDS ID: {}".format(job_id))
                # the status is hard coded because we query too fast before the record even shows up in ES
                # we wouldn't have a Job ID unless it was a valid payload and got accepted by the system
                if response.get("orig_job_status") is not None:
                    job_status = response.get("orig_job_status")
                else:
                    job_status = "job-queued"
                self._log_job_submission(job_id, input_params)
                return Response(ogc.status_response(job_id=job_id, job_status=job_status), mimetype='text/xml')
            else:
                raise Exception(response.get("message"))
        except Exception as ex:
            logging.info("Error submitting job: {}".format(ex))
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                            ex_message="Failed to submit job of type {}. Exception Message: {}"
                            .format(job_type, ex)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self):
        """
        This will request information about the server's capabilities and processes offered
        :return:
        """

        try:
            job_list = hysds.get_algorithms()
            response_body = ogc.get_capabilities(request.url_root, job_list)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedGetCapabilities", origin_process="GetCapabilities",
                                              ex_message="Failed to get server capabilities. {}. {}"
                                              .format(ex.message, tb)),
                            mimetype='text/xml',
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _log_job_submission(self, job_id, params={}):
        _user_id = self._get_user_id(params)

        if _user_id is not None:
            ma = MemberJob(member_id=_user_id, job_id=job_id, submitted_date=datetime.utcnow())
            db.session.add(ma)
            db.session.commit()

    def _get_user_id(self, params={}):
        # First try request token
        user = get_authorized_user()
        if user is None:
            # Not an authenticated request, so try from username param
            _username = hysds.get_username_from_job_submission(params)

            if _username is None:
                return None
            else:
                # Get user id from username
                member = db.session.query(Member).filter_by(username=_username).first()    
                return None if member is None else member.id
        else:
            return user.id


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
            queue = response.get("result").get("recommended-queues")[0]
            response_body = ogc.describe_process_response(algo_id, params, queue)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedDescribeProcess", origin_process="DescribeProcess",
                                              ex_message="Failed to get parameters for algorithm. {} Traceback: {}"
                                              .format(ex, tb)), status=status.HTTP_500_INTERNAL_SERVER_ERROR, mimetype='text/xml')


@ns.route('/job/<string:job_id>')
class Result(Resource):
    def get(self, job_id):
        """
        This will return the result of the job that successfully completed or failed. If job failed, you can see the
         error traceback.
        :return:
        """
        try:
            prod_list = list()
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            response = hysds.get_mozart_job(job_id)
            job_info = response.get("job").get("job_info").get("metrics").get("products_staged")
            traceback = response.get("traceback")
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
                    if traceback is not None:
                        return Response(ogc.result_response(job_id=job_id, job_result=prod_list, error=traceback),
                                        mimetype='text/xml')
                return Response(ogc.result_response(job_id=job_id, job_result=prod_list), mimetype='text/xml')
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetResult", origin_process="GetResult",
                                              ex_message="Failed to get job result of job with id: {}. " \
                                                         "{}. If you don't see expected results," \
                                                         " please contact administrator " \
                                                         "of DPS".format(job_id, ex)), mimetype='text/xml',
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
                                              "of DPS".format(job_id)), mimetype='text/xml',
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@ns.route('/job/cmr_delivery_status/delivery_job/<string:job_id>')
class CMR_Delivery_Job(Resource):
    def get(self, job_id):
        """
        This will return the cmr_delivery status of a product only if the product is verified.
        :return:
        """
        delivery_response = dict()

        try:
            logging.info("Checking if cmr_delivery job {} is finished.".format(job_id))
            try:
                # Find cmr_delivery job's status
                logging.info("Finding status of job with id {}".format(job_id))
                logging.info("Retrieved Mozart job id: {}".format(job_id))
                response = hysds.mozart_job_status(job_id=job_id)
                job_status = response.get("status")
                logging.info("Found Job Status: {}".format(job_status))
                # If cmr_delivery job's status is complete / failed then prepare response
                if job_status == "job-completed" or job_status == "job-failed":
                    info_response = hysds.get_mozart_job(job_id)
                    job_products = info_response.get("job").get("job_info").get("metrics").get("products_staged")
                    traceback = response.get("traceback")
                    if traceback is not None:
                        return Response(ogc.result_response(job_id=job_id, error=traceback), mimetype='text/xml')
                    elif job_products is not None:
                        delivery_response["code"] = 200
                        delivery_response["message"] = "CMR Delivery was successful."
                        return Response(delivery_response, status=200)
                # If cmr_delivery job's status is complete / failed then prepare response
                elif job_status == "job-queued" or job_status == "job-started":
                    delivery_response["code"] = 200
                    delivery_response["message"] = "CMR Delivery Job is still in progress with status {}." \
                                                   "Please try again later".format(job_status)
                    return delivery_response, 200
                else:
                    delivery_response["code"] = 200
                    delivery_response["message"] = "CMR Delivery Job didn't finish. Current status {}." \
                                                   "Please try again later".format(job_status)
                    return delivery_response, 200
            except Exception as ex:
                return Response(ogc.get_exception(type="FailedGetCMRStatus", origin_process="GetCMRStatus",
                                                  ex_message="Failed to get CMR Delivery Status for "
                                                             " product {}. Error: {}".format(ex),
                                                  mimetype='text/xml',
                                                  status=500))
            return Response(delivery_response)
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetStatus", origin_process="GetStatus",
                                              ex_message="Failed to get job status of job with id: {}. " \
                                              "Please check back a little later for " \
                                              "job execution status. If still not found," \
                                              " please contact administrator " \
                                              "of DPS".format(job_id)), mimetype='text/xml', status=500)
def get_search_headers():
    accept = next(iter(request.headers.getlist('accept') or ['application/json']), ['application/json'])
    logging.info("accept value: {}".format(accept))
    search_header = {
            'Accept': accept,
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }
    logging.info("CMR Search headers: {}".format(json.dumps(search_header)))
    return search_header

# Preserves keys that occur more than once, as allowed for in CMR
def parse_query_string(qs):
    return urlparse.parse_qs(qs)


@ns.route('/job/cmr_delivery_status/product/<string:granule_id>')
class CMR_Delivery(Resource):
    def get(self, granule_id):
        try:
            logging.info("Checking if product {} is can be found in CMR".format(granule_id))
            try:
                response = dict()
                # Parse the metadata and check ecosml_verified
                url = os.path.join(settings.CMR_URL, 'search', 'granules')
                granule_url = url +"?granule_ur=" + granule_id
                logging.info("GET request to CMR: {}".format(granule_url))
                try:
                    resp = requests.get(granule_url, verify=False)
                    code = resp.status_code
                    logging.info("Status code: {}".format(code))
                    logging.info("CMR Text Response: {}".format(resp.text))
                except Exception as ex:
                    return Response(ogc.get_exception(type="FailedGetCMRStatus", origin_process="GetCMRStatus",
                                                      ex_message="Failed to make request to CMR "
                                                                 " {}. Error: {}".format(granule_url, ex),
                                                      mimetype='text/xml',
                                                      status=500))
                # parse the xml result and get no of hits
                # if hits >= 1 then say delivery was a success
                granule_resp = fromstring(resp.text)
                hits = int(granule_resp[0].text)
                logging.info("Found {}  hits".format(hits))
                if hits >= 1:
                    response["message"] = "Granule {} was found in CMR".format(granule_id)
                    response["code"] = 200
                    return response
                elif hits == 0:
                    response["message"] = "Granule {} was not found in CMR".format(granule_id)
                    response["code"] = 200
                    return response
            except Exception as ex:
                return Response(ogc.get_exception(type="FailedGetCMRStatus", origin_process="GetCMRStatus",
                                                  ex_message="Failed to get CMR Delivery Status for "
                                                             " product {}. Error: {}".format(granule_id, ex),
                                                  mimetype='text/xml',
                                                  status=500))
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedGetCMRStatus", origin_process="GetCMRDelivStatus",
                                              ex_message="Failed to get cmr delivery status of product: {}. " \
                                                         "Please check back a little later for " \
                                                         "job execution status. If still not found," \
                                                         " please contact administrator " \
                                                         "of DPS".format(granule_id)), mimetype='text/xml', status=500)


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
                mozart_response = hysds.get_mozart_job(job_id)
            except Exception as ex:
                raise Exception("Failed to get job information found for {}. Reason: {}"
                                .format(job_id, ex))

            # get all the relevant metrics information
            job_info = mozart_response.get("job").get("job_info")
            dir_size = job_info.get("metrics").get("job_dir_size")
            job_facts = job_info.get("facts")
            architecture = job_facts.get("architecture")
            os = job_facts.get("operatingsystem")
            memorysize = job_facts.get("memorysize")
            instance_typ = job_facts.get("ec2_instance_type")
            time_start = job_info.get("cmd_start")
            time_end = job_info.get("cmd_end")
            time_duration = job_info.get("cmd_duration")

            docker_metrics = job_info.get("metrics").get("usage_stats")[0].get("cgroups")
            if docker_metrics is not None:
                cpu_stats = docker_metrics.get("cpu_stats").get("cpu_usage").get("total_usage")
                memory_stats = docker_metrics.get("memory_stats")
                cache_stat = memory_stats.get("cache")
                mem_usage = memory_stats.get("usage").get("usage")
                max_mem_usage = memory_stats.get("usage").get("max_usage")
                swap_usage = memory_stats.get("stats").get("swap")

                # total bytes transferred during all the I/O operations performed by the container
                io_stats = docker_metrics.get("blkio_stats").get("io_service_bytes_recursive")
                for io in io_stats:
                    op = io.get("op")
                    if op == "Read":
                        read_io_stats = io.get("value", 0)
                    elif op == "Write":
                        write_io_stats = io.get("value", 0)
                    elif op == "Sync":
                        sync_io_stats = io.get("value", 0)
                    elif op == "Async":
                        async_io_stats = io.get("value", 0)
                    elif op == "Total":
                        total_io_stats = io.get("value", 0)


            # build the metrics object
            """
            <?xml version="1.0" encoding="UTF-8"?>
            <Metrics>
            <machine_type></machine_type>
            <architecture></architecture>
            <machine_memory_size></machine_memory_size>
            <>
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
            directory_size = SubElement(xml_response, "directory_size")
            directory_size.text = str(dir_size)
            operating_system = SubElement(xml_response, "operating_system")
            operating_system.text = os
            job_start_time = SubElement(xml_response, "job_start_time")
            job_start_time.text = time_start
            job_end_time = SubElement(xml_response, "job_end_time")
            job_end_time.text = time_end
            job_duration_seconds = SubElement(xml_response, "job_duration_seconds")
            job_duration_seconds.text = str(time_duration)
            if docker_metrics is not None:
                cpu_usage = SubElement(xml_response, "cpu_usage")
                cpu_usage.text = str(cpu_stats)
                cache_usage = SubElement(xml_response, "cache_usage")
                cache_usage.text = str(cache_stat)
                mem_usage = SubElement(xml_response, "mem_usage")
                mem_usage.text = str(mem_usage)
                max_mem_usage = SubElement(xml_response, "max_mem_usage")
                max_mem_usage.text = str(max_mem_usage)
                swap_usage = SubElement(xml_response, "swap_usage")
                swap_usage.text = str(swap_usage)
                read_io_stats = SubElement(xml_response, "read_io_stats")
                read_io_stats.text = str(read_io_stats)
                write_io_stats = SubElement(xml_response, "write_io_stats")
                write_io_stats.text = str(write_io_stats)
                sync_io_stats = SubElement(xml_response, "sync_io_stats")
                sync_io_stats.text = str(sync_io_stats)
                async_io_stats = SubElement(xml_response, "async_io_stats")
                async_io_stats.text = str(async_io_stats)
                total_io_stats = SubElement(xml_response, "total_io_stats")
                total_io_stats.text = str(total_io_stats)
            return Response(tostring(xml_response), mimetype="text/xml", status=status.HTTP_200_OK)
        except Exception as ex:
            print("Metrics Exception: {}".format(ex))
            return Response(ogc.get_exception(type="FailedGetMetrics", origin_process="GetMetrics",
                                              ex_message="Failed to get job metrics. {}." \
                                              " Please contact administrator " \
                                              "of DPS for clarification if needed".format(ex)), mimetype='text/xml',
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@ns.route('/job/<string:username>/list')
class Jobs(Resource):
    parser = api.parser()
    parser.add_argument('page_size', required=False, type=str,
                        help="Job Listing Pagination Size")
    parser.add_argument('offset', required=False, type=str,
                        help="Job Listing Pagination Offset")

    @api.doc(security='ApiKeyAuth')
    @login_required
    def get(self, username):
        """
        This will return run a list of jobs for a specified user
        :return:
        """
        offset = request.args.get("offset", 0)
        page_size = request.args.get("page_size", 250)
        try:
            logging.info("Finding jobs for user: {}".format(username))
            # get list of jobs ids for the user
            response = hysds.get_mozart_jobs(username=username, offset=offset, page_size=page_size)
            job_list = response.get("result")
            logging.info("Found Jobs: {}".format(job_list))
            #if settings.HYSDS_VERSION == "v4.0":
            # get job info per job
            job_list = hysds.get_jobs_info(x.get("id") for x in job_list)
            response_body = dict()
            response_body["code"] = status.HTTP_200_OK
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
                                              "of DPS".format(username)), mimetype='text/xml',
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@ns.route('/job/cancel/<string:job_id>')
class StopJobs(Resource):
    parser = api.parser()
    parser.add_argument('wait_for_completion', default=False, required=False, type=bool,
                        help="Wait for Cancel job to finish")

    @api.doc(security='ApiKeyAuth')
    @login_required
    def post(self, job_id):
        # TODO: add optional parameter wait_for_completion to wait for cancel job to complete.
        # Since this can take a long time, we don't wait by default.
        wait_for_completion = request.args.get("wait_for_completion", False)
        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))

            if current_status is None:
                raise Exception("Job with id {} was not found.".format(job_id))

            # Revoke if job started
            elif current_status == hysds.STATUS_JOB_STARTED:
                logging.info("Submitting Revoke job for Job {}".format(job_id))
                purge_id, res = hysds.revoke_mozart_job(job_id=job_id, wait_for_completion=wait_for_completion)
                logging.info("Revoke Job Submission Response: {} {}".format(purge_id, res))
                response = ogc.status_response(job_id=job_id, job_status=hysds.STATUS_JOB_QUEUED)

            # Purge if job queued
            elif current_status == hysds.STATUS_JOB_QUEUED:
                logging.info("Submitting Purge job for Job {}".format(job_id))
                purge_id, res = hysds.delete_mozart_job(job_id=job_id, wait_for_completion=wait_for_completion)
                logging.info("Purge Job Submission Response: {} {}".format(purge_id, res))
                response = ogc.status_response(job_id=job_id, job_status=hysds.STATUS_JOB_QUEUED)
            # For all other statuses, we cannot cancel
            else:
                response = ogc.get_exception(type="FailedJobCancel", origin_process="Dismiss",
                                             ex_message="Not allowed cancel job with status {}".format(current_status))
                return Response(status=status.HTTP_400_BAD_REQUEST, response=response)

            if not wait_for_completion:
                return Response(status=status.HTTP_202_ACCEPTED, response=response, mimetype='text/xml')
            else:
                cancel_job_status = res.get("status")
                response = ogc.status_response(job_id=job_id, job_status=res.get("status"))
                if not cancel_job_status == hysds.STATUS_JOB_COMPLETED:
                    return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR, response=response, mimetype='text/xml')
                else:
                    return Response(status=status.HTTP_202_ACCEPTED, response=response,
                                    mimetype='text/xml')
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
                                              ex_message="Failed to dismiss job {}. Please try again or "
                                                         "contact DPS administrator. {}".format(job_id, ex)),
                            mimetype='text/xml', status=status.HTTP_500_INTERNAL_SERVER_ERROR)
