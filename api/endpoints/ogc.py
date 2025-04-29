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
from api.auth.security import get_authorized_user, login_required
from api.maap_database import db
from api.models.process import Process as Process_db
from api.models.deployment import Deployment as Deployment_db
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

# Processes section for OGC Compliance 
@ns.route('/processes')
class Processes(Resource):

    def get(self):
        """
        search processes with OGC compliance 
        :return:
        """
        print("graceal in get of processes in new file")
        response_body = dict()
        existing_processes = []
        existing_links =[]

        existingProcesses = db.session \
            .query(Process_db).all()
        print("graceal1 printing existing processes")
        print(existingProcesses)

        for process in existingProcesses:
            existing_processes.append({'process_id': process.process_id,
                                       'id': process.id, 
                                       'version': process.version})
            existing_links.append({'href': process.cwl_link})
        
        response_body["processes"] = existing_processes
        response_body["links"] = existing_links
        return response_body, status.HTTP_200_OK

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """
        post a new process
        :return:
        """
        print("graceal in post of processes in new file")
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
            response_body["message"] = "Unable to access CWL"
            return response_body, status.HTTP_400_BAD_REQUEST
        
        # TODO right now this will make 2 requests to get the data and I should fix that later
        # ideally need to save all the contents to a file then read from that for load document
        # do saving and deleting of this file in try catch 
        cwl_obj = load_document_by_uri(cwl_link, load_all=True)

        workflow = None
        for i in range(len(cwl_obj)):
            if type(cwl_obj[i]) == cwl_v1_2.Workflow:
                workflow = cwl_obj[i]
        cwl_id = workflow.id
        match = re.search(r"s:version:\s*(\S+)", response, re.IGNORECASE)

        if not match or not cwl_id:
            response_body["code"] = status.HTTP_400_BAD_REQUEST
            response_body["message"] = "Need to provide version at s:version or id"
            print(match)
            print(cwl_id)
            return response_body, status.HTTP_400_BAD_REQUEST
        
        fragment = urllib.parse.urlparse(cwl_id).fragment
        cwl_id = os.path.basename(fragment)
        process_version = match.group(1)

        print("graceal1 id and version are")
        print(cwl_id)
        print(process_version)
        
        existingProcess = db.session \
            .query(Process_db) \
            .filter_by(id=cwl_id, version=process_version) \
            .first()
        print("graceal existing process is ")
        print(existingProcess)
        
        # If process with same ID and version is already present, tell the user they need to use PUT instead to modify
        if existingProcess is not None:
            response_body["code"] = status.HTTP_409_CONFLICT
            response_body["detail"] = "Duplicate process. Use PUT to modify existing process if you originally published it."
            return response_body, status.HTTP_409_CONFLICT

        user = get_authorized_user()

        print("graceal1 settings.DEPLOY_PROCESS_EXECUTION_VENUE is ")
        print(settings.DEPLOY_PROCESS_EXECUTION_VENUE)
        print("done printing deployment venue")

        # need to create deployment before this call to get the job_id 
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

        print("graceal1 created deployment and trying to get job_id")
        deployment_job_id = deployment.job_id
        print(deployment_job_id)
        
        deploymentJobsEndpoint = "/deploymentJobs/" + str(deployment_job_id)

        try:
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.create({
                'ref': settings.VERSION,
                'variables': [
                    {'key': 'CWL_URL', 'value': cwl_link},
                    {'key': 'CALLBACK_URL', 'value': deploymentJobsEndpoint}
                ]
            })
            print(f"Triggered pipeline ID: {pipeline.id}")
        except: 
            # TODO graceal make sure this is edited object correctly 
            print("graceal failed to submit process to pipeline")
            existingDeployment = db.session \
                .query(Deployment_db) \
                .filter_by(job_id=deployment_job_id) \
                .first()
            existingDeployment.status = "Failed to submit to "+ existingDeployment.execution_venue
            db.session.commit()

            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        # Update the deployment you just created with the pipeline id and status from gitlab
        existingDeployment = db.session \
            .query(Deployment_db) \
            .filter_by(job_id=deployment_job_id) \
            .first()
        existingDeployment.pipeline_id = pipeline.id

        response_body["id"] = cwl_id
        response_body["version"] = process_version
        response_body["deploymentJobsEndpoint"] = deploymentJobsEndpoint

        response_body["processPipelineLink"] = pipeline.web_url

        existingDeployment.status = "created" 
        
        db.session.commit()
        return response_body, status.HTTP_202_ACCEPTED
    
@ns.route('/deploymentJobs/<int:job_id>')
class Deployment(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, job_id):
        current_app.logger.debug("graceal1 in deployment jobs get")
        response_body = dict()
        deployment = db.session.query(Deployment_db).filter_by(job_id=job_id).first()

        if deployment is None:
            response_body["code"] = status.HTTP_404_NOT_FOUND
            response_body["message"] = "No deployment with that deployment ID found"
            return response_body, status.HTTP_404_NOT_FOUND
        
        gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
        pipeline = project.pipelines.get(deployment.pipeline_id)

        # Only query pipeline link if status is not finished 
        pending_status_options = ["created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"]
        if deployment.status in pending_status_options:
            current_app.logger.debug("graceal1 current deployment status was something that was pending")
            
            # Update the current pipeline status 
            deployment.status = pipeline.status
            db.session.commit()

            # if the status has changed to success, then add to the Process table 
            if pipeline.status == "success":
                current_app.logger.debug("graceal1 pipeline status was pending but is now success so adding ")
                existingProcess = db.session \
                    .query(Process_db) \
                    .filter_by(id=deployment.id, version=deployment.version) \
                    .first()
                # if process with same id and version already exist, you just need to overwrite with the same process id 
                if existingProcess:
                    current_app.logger.debug("graceal1 similar proces already in the same")
                    existingProcess.cwl_link = deployment.cwl_link
                    existingProcess.user = deployment.user
                    process_id = existingProcess.process_id
                else:
                    current_app.logger.debug("graceal1 creating new process to add to the table")
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
                
                deployment.process_location = "/processes/"+str(process_id)
                db.session.commit()
        
        response_body = {
            "created": deployment.created,
            "status": deployment.status,
            "pipeline": {
                "executionVenue": deployment.execution_venue,
                "pipelineId": deployment.pipeline_id,
                "processPipelineLink": pipeline.web_url
            },
            "cwl": deployment.cwl_link
        }

        if deployment.process_location:
            response_body["processLocation"] = deployment.process_location
        return response_body, status.HTTP_200_OK
        
   
@ns.route('/processes/<string:process_id>')
class Describe(Resource):

    def get(self, process_id):
        print("graceal in the body of describe")
        response_body = dict()

        existingProcess = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        if existingProcess is None:
            response_body["code"] = status.HTTP_404_NOT_FOUND
            response_body["message"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        # job_type = "job-{}:{}".format(existingProcess.id, existingProcess.version)
        # maybe change to get_hysds_io
        # response = hysds.get_job_spec(job_type)

        hysdsio_type = "hysds-io-{}:{}".format(existingProcess.id, existingProcess.version)
        response = hysds.get_hysds_io(hysdsio_type)
        current_app.logger.debug("graceal got response hysds io")
        current_app.logger.debug(response)
        print("graceal1 got response hysds io")
        print(response)
        if response is None or not response.get("success"):
            response_body["code"] = status.HTTP_404_NOT_FOUND
            response_body["message"] = "No process with that process ID found on HySDS"
            return response_body, status.HTTP_404_NOT_FOUND 

        response = response.get("result")
        print("graceal result of response")
        print(response)
        response_body["description"] = response.get("description")
        response_body["id"] = existingProcess.id
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
        response_body["links"] = [{"href": existingProcess.cwl_link}]
        
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
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed authenticate user"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
            
        # Get existing process 
        existingProcess = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id) \
                    .first()
        
        if existingProcess is None:
            response_body["code"] = status.HTTP_404_NOT_FOUND
            response_body["message"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        req_data_string = request.data.decode("utf-8")
        req_data = json.loads(req_data_string)

        print("graceal1 comparing the user ids")
        print(user.id)
        print(existingProcess.user)
        # Make sure same user who originally posted process 
        if user.id != existingProcess.user:
            response_body["code"] = status.HTTP_403_FORBIDDEN
            response_body["message"] = "You can only modify processes that you posted originally"
            return response_body, status.HTTP_403_FORBIDDEN 
        
        try:
            cwl_link = req_data.get("executionUnit").get("href")
            response = requests.get(cwl_link)
            response.raise_for_status()
            response = response.text
        except:
            print("Error accessing cwl file")
            response_body["message"] = "Unable to access CWL"
            return response_body, status.HTTP_400_BAD_REQUEST
        
        # delete the previous entry from HySDS 
        # try:
        #     job_type = "job-{}:{}".format(existingProcess.id, existingProcess.version)
        #     print("gracael1 about to delete the job in mozart")
        #     hysds.delete_mozart_job_type(job_type)
        #     print("graceal1 done deleting the job in mozart")
        # except: 
        #     response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
        #     response_body["message"] = "Failed to process request to delete {}".format(job_type)
        #     return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        # TODO right now this will make 2 requests to get the data and I should fix that later
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
            response_body["code"] = status.HTTP_400_BAD_REQUEST
            response_body["message"] = "Need to provide version at s:version or id"
            print(match)
            print(new_cwl_id)
            return response_body, status.HTTP_400_BAD_REQUEST
        
        fragment = urllib.parse.urlparse(new_cwl_id).fragment
        new_cwl_id = os.path.basename(fragment)
        new_process_version = match.group(1)

        print("graceal1 New id and version are")
        print(new_cwl_id)
        print(new_process_version)

        if new_cwl_id != existingProcess.id or new_process_version != existingProcess.version:
            response_body["code"] = status.HTTP_400_BAD_REQUEST
            response_body["message"] = "Need to provide same id and version as previous process which is {}:{}".format(existingProcess.id, existingProcess.version)
            return response_body, status.HTTP_400_BAD_REQUEST

        # need to create deployment before this call to get the job_id 
        deployment = Deployment_db(created=datetime.now(),
                                execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE, 
                                status="submitted", # TODO not consistent with gitlab status endpoints I think, but can update later 
                                cwl_link=cwl_link,
                                user=user.id,
                                id=existingProcess.id,
                                version=existingProcess.version)
        db.session.add(deployment)
        db.session.commit()

        # Get the deployment you just committed to access its now assigned job id 
        deployment = db.session \
                .query(Deployment_db) \
                .filter_by(id=existingProcess.id,version=existingProcess.version,status="submitted") \
                .first()

        deployment_job_id = deployment.job_id
        
        deploymentJobsEndpoint = "/deploymentJobs/" + str(deployment_job_id)

        # Post the process to the deployment venue 
        try:
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.create({
                'ref': settings.VERSION,
                'variables': [
                    {'key': 'CWL_URL', 'value': cwl_link},
                    {'key': 'CALLBACK_URL', 'value': deploymentJobsEndpoint}
                ]
            })
            print(f"Triggered pipeline ID: {pipeline.id}")
        except: 
            # TODO graceal make sure this is edited object correctly 
            print("graceal failed to submit process to pipeline")
            existingDeployment = db.session \
                .query(Deployment_db) \
                .filter_by(job_id=deployment_job_id) \
                .first()
            existingDeployment.status = "Failed to submit to "+ existingDeployment.execution_venue
            db.session.commit()

            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        # Update the deployment you just created with the pipeline id and status from gitlab
        existingDeployment = db.session \
            .query(Deployment_db) \
            .filter_by(job_id=deployment_job_id) \
            .first()
        existingDeployment.pipeline_id = pipeline.id

        response_body["id"] = existingProcess.id
        response_body["version"] = existingProcess.version
        response_body["deploymentJobsEndpoint"] = deploymentJobsEndpoint

        response_body["processPipelineLink"] = pipeline.web_url

        existingDeployment.status = "created" 
        
        db.session.commit()
        return response_body, status.HTTP_202_ACCEPTED
  
    
# @ns.route('/processes/<string:process_id>/execution')
# class Describe(Resource):

#     @api.doc(security='ApiKeyAuth')
#     @login_required()
#     def post(self, process_id):
#         """
#         This posts a job to execute 
#         Changes to OGC schema: 
#         - adding queue to request body 
#         :return:
#         """
#         print("graceal in the body of executing a job")
#         req_data_string = request.data.decode("utf-8")
#         req_data = json.loads(req_data_string)
#         response_body = dict()

#         existingProcess = db.session \
#                     .query(Process_db) \
#                     .filter_by(process_id=process_id) \
#                     .first()
#         if existingProcess is None:
#             response_body["code"] = status.HTTP_404_NOT_FOUND
#             response_body["message"] = "No process with that process ID found"
#             return response_body, status.HTTP_404_NOT_FOUND 
        
#         inputs = req_data.get("inputs")
#         print("graceal1 inputs from post are")
#         print(inputs)
#         job_type = "job-{}:{}".format(existingProcess.id, existingProcess.version)

#         # validate the inputs provided by user against the registered spec for the job
#         try:
#             hysdsio_type = job_type.replace("job-", "hysds-io-")
#             hysds_io = hysds.get_hysds_io(hysdsio_type)
#             logging.info("Found HySDS-IO: {}".format(hysds_io))
#             # graceal, should do this add add validation steps later 
#             # params = hysds.validate_job_submit(hysds_io, input_params)
#         except Exception as ex:
#             response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
#             response_body["message"] = "Error validating inputs with HySDS"
#             return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 

#         try:
#             user = get_authorized_user()
#             queue = req_data.get("queue")
#             queue = job_queue.validate_or_get_queue(queue, job_type, user.id)
#             job_time_limit = hysds_io.get("result").get("soft_time_limit", 86400)
#             if job_queue.contains_time_limit(queue):
#                 job_time_limit = int(queue.time_limit_minutes) * 60
#             # what is dedup?? 
#             response = hysds.mozart_submit_job(job_type=job_type, params=inputs, dedup=dedup, queue=queue.queue_name,
#                                                identifier="{}:{}".format(existingProcess.id, existingProcess.version), job_time_limit=int(job_time_limit))

#             logging.info("Mozart Response: {}".format(json.dumps(response)))
#             job_id = response.get("result")
#             if job_id is not None:
#                 logging.info("Submitted Job with HySDS ID: {}".format(job_id))
#                 # the status is hard coded because we query too fast before the record even shows up in ES
#                 # we wouldn't have a Job ID unless it was a valid payload and got accepted by the system
#                 if response.get("orig_job_status") is not None:
#                     job_status = response.get("orig_job_status")
#                 else:
#                     job_status = "job-queued"
#                 self._log_job_submission(job_id, input_params)
#                 return Response(ogc.status_response(job_id=job_id, job_status=job_status), mimetype='text/xml')
#             else:
#                 raise Exception(response.get("message"))
#         except ValueError as ex:
#             logging.error(traceback.format_exc())
#             return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
#                                               ex_message=str(ex)), status.HTTP_400_BAD_REQUEST)
#         except Exception as ex:
#             logging.info("Error submitting job: {}".format(ex))
#             return Response(ogc.get_exception(type="FailedJobSubmit", origin_process="Execute",
#                             ex_message="Failed to submit job of type {}. Exception Message: {}"
#                             .format(job_type, ex)), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
#         return response_body, status.HTTP_202_ACCEPTED