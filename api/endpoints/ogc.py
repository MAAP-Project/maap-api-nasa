import logging
import os
from collections import namedtuple

import sqlalchemy
from flask import request, Response
from flask_restx import Resource, reqparse
from flask_api import status
from flask import current_app

from api.models.member import Member
from api.restplus import api
import re
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.utils.http_util as http_util
import api.settings as settings
import api.utils.ogc_translate as ogc
from api.auth.security import get_authorized_user, login_required, authenticate_third_party
from api.maap_database import db
from api.models.process import Process as Process_db
from api.models.deployment import Deployment as Deployment_db
from api.models.process_job import ProcessJob as ProcessJob_db
from api.models.member_algorithm import MemberAlgorithm
from sqlalchemy import or_, and_
from datetime import datetime
import json
import requests
import gitlab
from cwl_utils.parser import load_document_by_uri, cwl_v1_2
import urllib.parse

from api.utils import job_queue

log = logging.getLogger(__name__)

ns = api.namespace('ogc', description='OGC compliant endpoints')

hysds_finished_statuses = ["job-revoked", "job-failed", "job-completed"]
pending_status_options = ["created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"]
# graceal- can this be hard coded in? Want to avoid making to get the pipeline to then get its web_url and 
# want to avoid storing it in the database, so storing it as a template makes the most sense 
pipeline_url_template = settings.GITLAB_URL_POST_PROCESS+"/root/deploy-ogc-hysds/-/pipelines/{pipeline_id}"

# Processes section for OGC Compliance 
@ns.route('/processes')
class Processes(Resource):

    def get(self):
        """
        search processes with OGC compliance 
        :return:
        """
        response_body = dict()
        existing_processes_return = []
        existing_links_return =[]

        existing_processes = db.session \
            .query(Process_db).all()

        for process in existing_processes:
            existing_processes_return.append({'process_id': process.process_id,
                                       'id': process.id, 
                                       'version': process.version})
            existing_links_return.append({'href': process.cwl_link})
        
        response_body["processes"] = existing_processes_return
        response_body["links"] = existing_links_return
        return response_body, status.HTTP_200_OK

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """
        post a new process
        Changes to OGC schema: 
        - for 409 error, adding additionalProperies which is a dictionary with the process id
        :return:
        """
        req_data_string = request.data.decode("utf-8")
        req_data = json.loads(req_data_string)
        response_body = dict()

        try:
            cwl_link = req_data.get("executionUnit").get("href")
            response = requests.get(cwl_link)
            response.raise_for_status()
            response = response.text
        except:
            print("Error accessing cwl file")
            # Technically response_body["type"] is required but that is a whole thing to implement with URIs: https://datatracker.ietf.org/doc/html/rfc7807
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Unable to access CWL"
            return response_body, status.HTTP_400_BAD_REQUEST
        
        # TODO right now this will make 2 requests to get the data and I should fix that later
        # ideally need to save all the contents to a file then read from that for load document
        # do saving and deleting of this file in try catch 
        try: 
            cwl_obj = load_document_by_uri(cwl_link, load_all=True)
        except: 
            print("Error parsing the cwl file")
            # Technically response_body["type"] is required but that is a whole thing to implement with URIs: https://datatracker.ietf.org/doc/html/rfc7807
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "CWL file is not in the right format"
            return response_body, status.HTTP_400_BAD_REQUEST

        workflow = None
        for i in range(len(cwl_obj)):
            if type(cwl_obj[i]) == cwl_v1_2.Workflow:
                workflow = cwl_obj[i]
        cwl_id = workflow.id
        match = re.search(r"s:version:\s*(\S+)", response, re.IGNORECASE)

        if not match or not cwl_id:
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Need to provide version at s:version or id"
            print(match)
            print(cwl_id)
            return response_body, status.HTTP_400_BAD_REQUEST
        
        fragment = urllib.parse.urlparse(cwl_id).fragment
        cwl_id = os.path.basename(fragment)
        process_version = match.group(1)
        
        existing_process = db.session \
            .query(Process_db) \
            .filter_by(id=cwl_id, version=process_version) \
            .first()
        
        # If process with same ID and version is already present, tell the user they need to use PUT instead to modify
        if existing_process is not None:
            response_body["status"] = status.HTTP_409_CONFLICT
            response_body["detail"] = "Duplicate process. Use PUT to modify existing process if you originally published it."
            response_body["additionalProperties"] = {"process_id": existing_process.process_id}
            return response_body, status.HTTP_409_CONFLICT

        user = get_authorized_user()

        try:
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.create({
                'ref': settings.VERSION,
                'variables': [
                    {'key': 'CWL_URL', 'value': cwl_link}
                ]
            })
            print(f"Triggered pipeline ID: {pipeline.id}")
            
            deployment = Deployment_db(created=datetime.now(),
                                    execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE, 
                                    status="submitted", # TODO not consistent with gitlab status endpoints I think, but can update later 
                                    cwl_link=cwl_link,
                                    user=user.id,
                                    id=cwl_id,
                                    version=process_version)
            db.session.add(deployment)
            db.session.commit()

            deployment = db.session \
                    .query(Deployment_db) \
                    .filter_by(id=cwl_id,version=process_version,status="submitted") \
                    .first()

            deployment_job_id = deployment.job_id
        except: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        # Update the deployment you just created with the pipeline id and status from gitlab
        existing_deployment = db.session \
            .query(Deployment_db) \
            .filter_by(job_id=deployment_job_id) \
            .first()
        existing_deployment.pipeline_id = pipeline.id

        response_body["id"] = cwl_id
        response_body["version"] = process_version
        response_body["deploymentJobEndpoint"] = "/deploymentJobs/" + str(deployment_job_id)

        response_body["processPipelineLink"] = pipeline.web_url

        existing_deployment.status = "created" 
        
        db.session.commit()
        return response_body, status.HTTP_202_ACCEPTED
    
"""
Updates the status of the deployment if the deployment was previously in a pending state
If the pipeline was successful, add the process to the table  
In the case where a logged in user is querying check the updated status by querying the pipeline
In the case where a authenticated 3rd party is making the call, get the updated status from the payload
"""
def update_status_post_process_if_applicable(deployment, req_data=None, query_pipeline=False):
    status_code = status.HTTP_200_OK

    response_body = dict()

    if deployment is None:
        response_body["status"] = status.HTTP_404_NOT_FOUND
        response_body["detail"] = "No deployment with that deployment ID found"
        return response_body, status.HTTP_404_NOT_FOUND

    # Only query pipeline link if status is not finished 
    if deployment.status in pending_status_options:
        # Get the updated status from a logged in user from querying the pipeline
        if query_pipeline:
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.get(deployment.pipeline_id)
            updated_status = pipeline.status
        # Get the updated status from an authenticated 3rd party from the payload 
        else:
            try:
                updated_status = req_data["object_attributes"]["status"]
            except:
                response_body["status"] = status.HTTP_400_BAD_REQUEST
                response_body["detail"] = 'Payload from 3rd party should have status at ["object_attributes"]["status"]]'
                return response_body, status.HTTP_400_BAD_REQUEST
        
        # Update the current pipeline status 
        deployment.status = updated_status
        db.session.commit()

        # if the status has changed to success, then add to the Process table 
        if updated_status == "success":
            existing_process = db.session \
                .query(Process_db) \
                .filter_by(id=deployment.id, version=deployment.version) \
                .first()
            # if process with same id and version already exist, you just need to overwrite with the same process id 
            # This is for the case when multiple deployments start before any of them can successfully finish
            # Now, if someone try to post a process with the same id/version, they would get a 409 duplicate error
            if existing_process:
                existing_process.cwl_link = deployment.cwl_link
                existing_process.user = deployment.user
                process_id = existing_process.process_id
            else:
                process = Process_db(id=deployment.id,
                                version=deployment.version,
                                cwl_link=deployment.cwl_link,
                                user=deployment.user)
                db.session.add(process)
                db.session.commit()

                process = db.session \
                    .query(Process_db) \
                    .filter_by(id=deployment.id, version=deployment.version) \
                    .first()
                process_id = process.process_id

            status_code = status.HTTP_201_CREATED
            
            deployment.process_location = "/processes/"+str(process_id)
            db.session.commit()
    pipeline_url = pipeline_url_template.replace("{pipeline_id}", str(deployment.pipeline_id))
    
    response_body = {
        "created": deployment.created,
        "status": deployment.status,
        "pipeline": {
            "executionVenue": deployment.execution_venue,
            "pipelineId": deployment.pipeline_id,
            "processPipelineLink": pipeline_url
        },
        "cwl": deployment.cwl_link
    }

    if deployment.process_location:
        response_body["processLocation"] = deployment.process_location

    return response_body, status_code

@ns.route('/deploymentJobs/<string:deployment_id>')
class Deployment(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, deployment_id):
        """
        Query the current status of an algorithm being deployed 
        """
        deployment = db.session.query(Deployment_db).filter_by(job_id=deployment_id).first()
        response_body, status_code = update_status_post_process_if_applicable(deployment, req_data=None, query_pipeline=True)
        
        return response_body, status_code
    
@ns.route('/deploymentJobs')
class Deployment(Resource):

    @api.doc(security='ApiKeyAuth')
    @authenticate_third_party()
    def post(self):
        """
        Update the status of a deployment once the pipeline has finished 
        :return:
        """
        response_body = dict()
        try:
            req_data_string = request.data.decode("utf-8")
            req_data = json.loads(req_data_string)
            pipeline_id = req_data["object_attributes"]["id"]
        except:
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = 'Expected request body to include job_id at ["object_attributes"]["id"]]'
            return response_body, status.HTTP_400_BAD_REQUEST
        
        # Filtering by current execution venue because pipeline id not guaranteed to be unique across different
        # deployment venues, so check for the current one 
        deployment = db.session.query(Deployment_db).filter_by(pipeline_id=pipeline_id,execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE).first()
        response_body, status_code = update_status_post_process_if_applicable(deployment, req_data, query_pipeline=False)

        return response_body, status_code
   
@ns.route('/processes/<string:process_id>')
class Describe(Resource):

    def get(self, process_id):
        response_body = dict()

        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        # job_type = "job-{}:{}".format(existing_process.id, existing_process.version)
        # maybe change to get_hysds_io
        # response = hysds.get_job_spec(job_type)

        hysdsio_type = "hysds-io-{}:{}".format(existing_process.id, existing_process.version)
        response = hysds.get_hysds_io(hysdsio_type)
        if response is None or not response.get("success"):
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found on HySDS"
            return response_body, status.HTTP_404_NOT_FOUND 

        response = response.get("result")
        response_body["description"] = response.get("description")
        response_body["id"] = existing_process.id
        response_body["version"] = response.get("job-version")
        # is this close enough to the same thing? 
        response_body["title"] = response.get("label")
        # need to refine this to be what OGC is expecting, etc.
        count = 1
        response_body["inputs"] = {}
        for param in response.get("params"):
            response_body["inputs"]["additionalProp"+str(count)] = {"title": param.get("name"), "description": param.get("description"), "type": param.get("type"), "placeholder": param.get("placeholder"), "default": param.get("default")}
            count+=1
        # important things missing: outputs, 
        response_body["links"] = [{"href": existing_process.cwl_link}]
        
        return response_body, status.HTTP_200_OK
    
    @api.doc(security='ApiKeyAuth')
    @login_required()
    def put(self, process_id):
        """
        replace an existing process
        Must be the same user who posted the process 
        :return:
        """
        response_body = dict()
        try:
            user = get_authorized_user()
        except:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed authenticate user"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
            
        # Get existing process 
        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        req_data_string = request.data.decode("utf-8")
        req_data = json.loads(req_data_string)

        # Make sure same user who originally posted process 
        if user.id != existing_process.user:
            response_body["status"] = status.HTTP_403_FORBIDDEN
            response_body["detail"] = "You can only modify processes that you posted originally"
            return response_body, status.HTTP_403_FORBIDDEN 
        
        try:
            cwl_link = req_data.get("executionUnit").get("href")
            response = requests.get(cwl_link)
            response.raise_for_status()
            response = response.text
        except:
            # TODO debatable what error code this should be 
            print("Error accessing cwl file")
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Unable to access CWL"
            return response_body, status.HTTP_400_BAD_REQUEST
        
        # TODO graceal right now this will make 2 requests to get the data and I should fix that later
        # ideally need to save all the contents to a file then read from that for load document
        # do saving and deleting of this file in try catch 
        cwl_obj = load_document_by_uri(cwl_link, load_all=True)

        workflow = None
        for i in range(len(cwl_obj)):
            if type(cwl_obj[i]) == cwl_v1_2.Workflow:
                workflow = cwl_obj[i]
        new_cwl_id = workflow.id
        match = re.search(r"s:version:\s*(\S+)", response, re.IGNORECASE)

        if not match or not new_cwl_id:
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Need to provide version at s:version or id"
            print(match)
            print(new_cwl_id)
            return response_body, status.HTTP_400_BAD_REQUEST
        
        fragment = urllib.parse.urlparse(new_cwl_id).fragment
        new_cwl_id = os.path.basename(fragment)
        new_process_version = match.group(1)

        if new_cwl_id != existing_process.id or new_process_version != existing_process.version:
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Need to provide same id and version as previous process which is {}:{}".format(existing_process.id, existing_process.version)
            return response_body, status.HTTP_400_BAD_REQUEST

        # Post the process to the deployment venue 
        try:
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.create({
                'ref': settings.VERSION,
                'variables': [
                    {'key': 'CWL_URL', 'value': cwl_link}
                ]
            })
            print(f"Triggered pipeline ID: {pipeline.id}")
            deployment = Deployment_db(created=datetime.now(),
                                execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE, 
                                status="submitted", # TODO not consistent with gitlab status endpoints I think, but can update later 
                                cwl_link=cwl_link,
                                user=user.id,
                                id=existing_process.id,
                                version=existing_process.version)
            db.session.add(deployment)
            db.session.commit()

            # Get the deployment you just committed to access its now assigned job id 
            deployment = db.session \
                    .query(Deployment_db) \
                    .filter_by(id=existing_process.id,version=existing_process.version,status="submitted") \
                    .first()

            deployment_job_id = deployment.job_id
        except: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        # Update the deployment you just created with the pipeline id and status from gitlab
        existing_deployment = db.session \
            .query(Deployment_db) \
            .filter_by(job_id=deployment_job_id) \
            .first()
        existing_deployment.pipeline_id = pipeline.id

        response_body["id"] = existing_process.id
        response_body["version"] = existing_process.version
        response_body["deploymentJobEndpoint"] = "/deploymentJobs/" + str(deployment_job_id)

        response_body["processPipelineLink"] = pipeline.web_url

        existing_deployment.status = "created" 
        
        db.session.commit()
        return response_body, status.HTTP_202_ACCEPTED
    
    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, process_id):
        """
        delete an existing process
        Must be the same user who posted the process 
        :return:
        """
        response_body = dict()
        try:
            user = get_authorized_user()
        except:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed authenticate user"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
            
        # Get existing process 
        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 

        # Make sure same user who originally posted process 
        if user.id != existing_process.user:
            response_body["status"] = status.HTTP_403_FORBIDDEN
            response_body["detail"] = "You can only modify processes that you posted originally"
            return response_body, status.HTTP_403_FORBIDDEN 
        
        # delete the process from HySDS 
        try:
            job_type = "job-{}:{}".format(existing_process.id, existing_process.version)
            hysds.delete_mozart_job_type(job_type)
            # Delete from database
            db.session.delete(existing_process)
            db.session.commit()
            response_body["status"] = status.HTTP_200_OK 
            response_body["detail"] = "Deleted process"
            return response_body, status.HTTP_200_OK 
        except: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to process request to delete {}".format(job_type)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        

@ns.route('/processes/<string:process_id>/execution')
class ExecuteJob(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self, process_id):
        """
        This posts a job to execute 
        Changes to OGC schema: 
        - adding queue to request body 
        - adding dedup to request body (optional)
        - adding tag to the request body
        :return:
        """
        req_data_string = request.data.decode("utf-8")
        req_data = json.loads(req_data_string)
        response_body = dict()

        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        inputs = req_data.get("inputs")
        queue = req_data.get("queue")
        dedup = req_data.get("dedup")
        tag = req_data.get("tag")
        
        job_type = "job-{}:{}".format(existing_process.id, existing_process.version)
        try:
            user = get_authorized_user()
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Error validating user"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 

        # validate the inputs provided by user against the registered spec for the job
        try:
            hysdsio_type = job_type.replace("job-", "hysds-io-")
            hysds_io = hysds.get_hysds_io(hysdsio_type)
            logging.info("Found HySDS-IO: {}".format(hysds_io))
            params = hysds.validate_job_submit(hysds_io, inputs, user.username)
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Error validating inputs with HySDS"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 

        try:
            # dedup will be optional for clientside. The point of dedup is to catch 
            # If the user is submitting the same job with the same inputs so that it isn't run again 
            dedup = "false" if dedup is None else dedup
            queue = job_queue.validate_or_get_queue(queue, job_type, user.id)
            job_time_limit = hysds_io.get("result").get("soft_time_limit", 86400)
            if job_queue.contains_time_limit(queue):
                job_time_limit = int(queue.time_limit_minutes) * 60
            response = hysds.mozart_submit_job(job_type=job_type, params=params, dedup=dedup, queue=queue.queue_name,
                                               identifier=tag or "{}:{}".format(existing_process.id, existing_process.version), job_time_limit=int(job_time_limit))

            logging.info("Mozart Response: {}".format(json.dumps(response)))
            job_id = response.get("result")
            if job_id is not None:
                logging.info("Submitted Job with HySDS ID: {}".format(job_id))
                # the status is hard coded because we query too fast before the record even shows up in ES
                # we wouldn't have a Job ID unless it was a valid payload and got accepted by the system
                # TODO right now I am just hardcoding accepted for the status because that is what OGC wants, 
                # one of: accepted, running, failed, successful, dismissed
                # if response.get("orig_job_status") is not None:
                #     job_status = response.get("orig_job_status")
                # else:
                #     job_status = "job-queued"
                submitted_time = datetime.now()
                process_job = ProcessJob_db(user=user.id,
                    id=job_id, 
                    submitted_time=submitted_time, 
                    process_id=existing_process.process_id,
                    status="accepted")
                db.session.add(process_job)
                db.session.commit()
                response_body = {"id": job_id, "processID": existing_process.process_id, "created": submitted_time.isoformat(), "status": "accepted"}
                return response_body, status.HTTP_202_ACCEPTED
            else:
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["detail"] = response.get("message")
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
        except ValueError as ex:
            logging.error(traceback.format_exc())
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "FailedJobSubmit: " + str(ex)
            return response_body, status.HTTP_400_BAD_REQUEST 
        
        except Exception as ex:
            logging.info("Error submitting job: {}".format(ex))
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "FailedJobSubmit: " + str(ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
        

@ns.route('/job/<string:job_id>/results')
class Result(Resource):
    
    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, job_id):
        """
        This will return the result of the job that successfully completed or failed. If job failed, you can see the
         error traceback.
        :return:
        """
        response_body = dict()

        try:
            prod_list = list()
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            existing_job = db.session \
                .query(ProcessJob_db) \
                .filter_by(id=job_id) \
                .first()
            if existing_job is None:
                response_body["status"] = status.HTTP_404_NOT_FOUND
                response_body["detail"] = "No job with that job ID found"
                return response_body, status.HTTP_404_NOT_FOUND 

            response = hysds.get_mozart_job(existing_job.id)
            print("graceal1 response from mozart with results is ")
            print(response)
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
                        # TODO graceal pass prod_list even if failed??
                        response_body["status"] = status.HTTP_200_OK
                        response_body["detail"] = "Job failed and traceback is " + str(traceback)
                        return response_body, status.HTTP_200_OK 
                count = 1
                for prod_item in prod_list:
                    response_body["additionalProp"+str(count)] = prod_item
                    count += 1
                return response_body, status.HTTP_200_OK 
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to get job result of job with id: {}. " \
                                                         "{}. If you don't see expected results," \
                                                         " please contact administrator " \
                                                         "of DPS".format(job_id, ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        
@ns.route('/job/<string:job_id>')
class Status(Resource):
    parser = api.parser()
    parser.add_argument('wait_for_completion', default=False, required=False, type=bool,
                        help="Wait for Cancel job to finish")

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, job_id):
        """
        Shows the status of the job
        :return:
        """
        response_body = dict()

        existing_job = db.session \
            .query(ProcessJob_db) \
            .filter_by(id=job_id) \
            .first()
        if existing_job is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No job with that job ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        # print("graceal1 getting more detailed information from mozart")
        # print(hysds.get_jobs_info(existing_job.id))
        
        response_body["created"] = existing_job.submitted_time.isoformat()
        response_body["processID"] = existing_job.process_id
        response_body["id"] = existing_job.id
        
        # Dont update if status is already finished
        # graceal is job-offline a finished status? I don't think so
        # Also if I could get more information from hysds about the job like time to complete, etc. 
        # that would be useful for the client, right now can copy the way that jobs list is doing it 
        if existing_job.status in hysds_finished_statuses:
            response_body["status"] = existing_job.status
            # response_body["finished"] = existing_job.completed_time.isoformat()
            return response_body, status.HTTP_200_OK 
        else:
            try:
                # Request to HySDS to check the current status if last checked the job hadnt finished 
                response = hysds.mozart_job_status(job_id=existing_job.id)
                current_status = response.get("status")
                # TODO graceal make status conform to OGC? 
                response_body["status"] = current_status
                # graceal try to get useful information 
                # If status has now changed to completed, update some information about the job for easy access later
                #if current_status in hysds_finished_statuses:
                    # response_body["finished"] = completed_time.isoformat()
                    # graceal comment these in when I have completed time right 
                    # existing_job.completed_time = completed_time
                existing_job.status = current_status
                db.session.commit()
                return response_body, status.HTTP_200_OK 
            except: 
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["detail"] = "Failed to get job status of job with id: {}. " \
                                              "Please check back a little later for " \
                                              "job execution status. If still not found," \
                                              " please contact administrator " \
                                              "of DPS".format(job_id)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
    
    @api.doc(security='ApiKeyAuth')
    @login_required() 
    def delete(self, job_id):
        """
        This will cancel a running job or delete a queued job
        :return:
        """
        response_body = dict()
        # TODO: add optional parameter wait_for_completion to wait for cancel job to complete.
        # Since this can take a long time, we don't wait by default.
        wait_for_completion = request.args.get("wait_for_completion", False)
        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))

            if current_status is None:
                response_body["status"] = status.HTTP_404_NOT_FOUND
                response_body["detail"] = "Job with id {} not found".format(job_id)
                return response_body, status.HTTP_404_NOT_FOUND 

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
                response_body["status"] = status.HTTP_400_BAD_REQUEST
                response_body["detail"] = "Not allowed to cancel job with status {}".format(current_status)
                return response_body, status.HTTP_400_BAD_REQUEST 

            print("graceal1 printing response to see where date is in it")
            print(response)
            if not wait_for_completion:
                response_body["status"] = status.HTTP_202_ACCEPTED
                response_body["detail"] = response
                return response_body, status.HTTP_202_ACCEPTED 
            else:
                cancel_job_status = res.get("status")
                response = ogc.status_response(job_id=job_id, job_status=res.get("status"))
                if not cancel_job_status == hysds.STATUS_JOB_COMPLETED:
                    response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                    response_body["detail"] = response
                    return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
                else:
                    response_body["status"] = status.HTTP_202_ACCEPTED
                    response_body["detail"] = response
                    return response_body, status.HTTP_202_ACCEPTED 
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to dismiss job {}. Please try again or contact DPS administrator. {}".format(job_id, ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
