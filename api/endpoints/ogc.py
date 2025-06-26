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
from datetime import datetime, timedelta
import json
import requests
import gitlab
from cwl_utils.parser import load_document_by_uri, cwl_v1_2
import urllib.parse
import copy

from api.utils import job_queue

log = logging.getLogger(__name__)

ns = api.namespace('ogc', description='OGC compliant endpoints')

OGC_FINISHED_STATUSES = ["successful", "failed", "dismisssed", "deduped"]
OGC_SUCCESS = "successful"
PIPELINE_URL_TEMPLATE = settings.GITLAB_URL_POST_PROCESS+"/root/deploy-ogc-hysds/-/pipelines/{pipeline_id}"
INITIAL_JOB_STATUS="accepted"
DEPLOYED_PROCESS_STATUS="deployed"

# TODO run through chatgpt to refactor 

# Processes section for OGC Compliance 
@ns.route('/processes')
class Processes(Resource):

    def get(self):
        """
        Search all processes 
        :return:
        """
        print("graceal in get of processes")
        response_body = dict()
        existing_processes_return = []
        existing_links_return =[]

        existing_processes = db.session \
            .query(Process_db).filter_by(status=DEPLOYED_PROCESS_STATUS).all()

        for process in existing_processes:
            link_obj_process = {'href': '/'+ns.name+'/processes/'+str(process.process_id),
                        'rel': 'self',
                        'type': None,
                        'hreflang': None,
                        'title': 'OGC Process Description'
                    }
            existing_processes_return.append({'title': process.title,
                                       'description': process.description,
                                       'keywords': process.keywords.split(",") if process.keywords is not None else [], 
                                       'metadata': [],
                                       'id': process.id, 
                                       'version': process.version,
                                       'jobControlOptions': [], # TODO Unsure what we want this to be yet
                                       'cwl_link': process.cwl_link,
                                       'links': [link_obj_process]
                                    })
            existing_links_return.append(link_obj_process)
        
        response_body["processes"] = existing_processes_return
        response_body["links"] = existing_links_return
        return response_body, status.HTTP_200_OK

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """
        Post a new process
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

        # TODO make sure no errors when these are null 
        # We will need to extract all this information ourselves because HySDS doesnt have it yet
        keywords = re.search(r"s:keywords:\s*(\S+)", response, re.IGNORECASE)
        if keywords: 
            keywords = keywords.group(1)
        print("graceal1 keywords is ")
        print(keywords)

        title = workflow.label
        print("graceal1 title is ")
        print(title)
        description = workflow.doc
        print("graceal1 description is ")
        print(description)

        if not match or not cwl_id:
            response_body["status"] = status.HTTP_400_BAD_REQUEST
            response_body["detail"] = "Need to provide version at s:version or id"
            return response_body, status.HTTP_400_BAD_REQUEST
        
        fragment = urllib.parse.urlparse(cwl_id).fragment
        cwl_id = os.path.basename(fragment)
        process_version = match.group(1)
        
        existing_process = db.session \
            .query(Process_db) \
            .filter_by(id=cwl_id, version=process_version, status=DEPLOYED_PROCESS_STATUS) \
            .first()
        
        # If process with same ID and version is already present, tell the user they need to use PUT instead to modify
        if existing_process is not None:
            response_body["status"] = status.HTTP_409_CONFLICT
            response_body["detail"] = "Duplicate process. Use PUT to modify existing process if you originally published it."
            response_body["additionalProperties"] = {"processID": existing_process.process_id}
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
            
            # Create the deployment which tracks the status of a deploying process 
            deployment = Deployment_db(created=datetime.now(),
                                    execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE, 
                                    status=INITIAL_JOB_STATUS,
                                    cwl_link=cwl_link,
                                    title=title,
                                    description=description,
                                    keywords=keywords,
                                    user=user.id,
                                    pipeline_id=pipeline.id,
                                    id=cwl_id,
                                    version=process_version)
            db.session.add(deployment)
            db.session.commit()

            # Query the deployment that you just created to get its job_id for your response 
            deployment = db.session \
                    .query(Deployment_db) \
                    .filter_by(id=cwl_id,version=process_version,status=INITIAL_JOB_STATUS) \
                    .first()
            deployment_job_id = deployment.job_id
        except: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        response_body["title"] = title
        response_body["description"] = description
        response_body["keywords"] =  keywords.split(",") if keywords is not None else []
        response_body["metadata"] = []
        response_body["id"] = cwl_id
        response_body["version"] = process_version
        response_body["jobControlOptions"] = []
        response_body["links"] = [{
            "href": "/"+ns.name+"/deploymentJobs/" + str(deployment_job_id),
            "rel": "self",
            "type": None,
            "hreflang": None,
            "title": "Deploying process status link"
        }]
        response_body["processPipelineLink"] = {
            "href": pipeline.web_url,
            "rel": "reference",
            "type": None,
            "hreflang": None,
            "title": "Link to process pipeline"
        }
        
        return response_body, status.HTTP_202_ACCEPTED
    
"""
Updates the status of the deployment if the deployment was previously in a pending state
If the pipeline was successful, add the process to the table  
In the case where a logged in user is querying check the updated status by querying the pipeline
In the case where a authenticated 3rd party is making the call, get the updated status from the payload
Only commit the updated status to the relational database if it is in the finished state
"""
def update_status_post_process_if_applicable(deployment, req_data=None, query_pipeline=False):
    status_code = status.HTTP_200_OK

    response_body = dict()

    if deployment is None:
        response_body["status"] = status.HTTP_404_NOT_FOUND
        response_body["detail"] = "No deployment with that deployment ID found"
        return response_body, status.HTTP_404_NOT_FOUND

    current_status = None
    # Only query pipeline link if status is not finished 
    if deployment.status not in OGC_FINISHED_STATUSES:
        # Get the updated status for a logged in user from querying the pipeline
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
        ogc_status = ogc.get_ogc_status_from_gitlab(updated_status)
        current_status = ogc_status if ogc_status else updated_status

        # Only update the deployment status in the database if status is now finished
        if current_status in OGC_FINISHED_STATUSES:
            print("graceal status was in finished so updating for deployment")
            deployment.status = current_status
            db.session.commit()

        print("graceal this might be the weird part, checking updated status (should be in OGC) againest successful")
        print(current_status)
        # if the status has changed to success, then add to the Process table 
        if current_status == OGC_SUCCESS:
            existing_process = db.session \
                .query(Process_db) \
                .filter_by(id=deployment.id, version=deployment.version, status=DEPLOYED_PROCESS_STATUS) \
                .first()
            # if process with same id and version already exist, you just need to overwrite with the same process id 
            # This is for the case when multiple deployments start before any of them can successfully finish
            # The process would have been overwritten in HySDS anyway
            # Now, if someone try to post a process with the same id/version, they would get a 409 duplicate error
            if existing_process:
                existing_process.cwl_link = deployment.cwl_link
                existing_process.user = deployment.user
                process_id = existing_process.process_id
            else:
                process = Process_db(id=deployment.id,
                                version=deployment.version,
                                cwl_link=deployment.cwl_link,
                                title=deployment.title,
                                description=deployment.description,
                                keywords=deployment.keywords,
                                user=deployment.user, 
                                status=DEPLOYED_PROCESS_STATUS)
                db.session.add(process)
                db.session.commit()

                process = db.session \
                    .query(Process_db) \
                    .filter_by(id=deployment.id, version=deployment.version, status=DEPLOYED_PROCESS_STATUS) \
                    .first()
                process_id = process.process_id

            status_code = status.HTTP_201_CREATED
            
            deployment.process_location = "/processes/"+str(process_id)
            db.session.commit()
    else:
        current_status = deployment.status
    pipeline_url = PIPELINE_URL_TEMPLATE.replace("{pipeline_id}", str(deployment.pipeline_id))
    
    response_body = {
        "created": deployment.created,
        "status": current_status,
        "pipeline": {
            "executionVenue": deployment.execution_venue,
            "pipelineId": deployment.pipeline_id,
            "processPipelineLink": {"href": pipeline_url,
                                    'rel': 'reference',
                                    'type': None,
                                    'hreflang': None,
                                    'title': 'Deploying Process Pipeline'}
        },
        "cwl": {"href": deployment.cwl_link,
                'rel': 'reference',
                'type': None,
                'hreflang': None,
                'title': 'Deployment Link'}
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
        Called by authenticated 3rd parties to update the status of a deploying process via webhooks
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
        """
        Get more detailed information about a specific process 
        """
        response_body = dict()

        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS) \
                    .first()
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 

        hysdsio_type = "hysds-io-{}:{}".format(existing_process.id, existing_process.version)
        response = hysds.get_hysds_io(hysdsio_type)
        if response is None or not response.get("success"):
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found on HySDS"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        response = response.get("result")

        response_body = {
            "title": existing_process.title,
            "description": existing_process.description,
            "keywords": existing_process.keywords.split(",") if existing_process.keywords else [],
            "metadata": [],
            "id": existing_process.id,
            "processID": process_id,
            "version": existing_process.version,
            "jobControlOptions": [],
            "cwlLink": existing_process.cwl_link,
            "links": [
                {
                    "href": f"/{ns.name}/processes/{process_id}",
                    "rel": "self",
                    "type": None,
                    "hreflang": None,
                    "title": "self"
                },
                {
                    "href": f"/{ns.name}/processes/{process_id}/package",
                    "rel": "self",
                    "type": None,
                    "hreflang": None,
                    "title": "self"
                }
            ]
        }
        # need to refine this to be what OGC is expecting, etc.
        count = 1
        response_body["inputs"] = {}
        for param in response.get("params"):
            response_body["inputs"][param.get("name")] = {"title": param.get("name"), "description": param.get("description"), "type": param.get("type"), "placeholder": param.get("placeholder"), "default": param.get("default")}
            count+=1
        # TODO add outputs to response
        
        return response_body, status.HTTP_200_OK
    
    @api.doc(security='ApiKeyAuth')
    @login_required()
    def put(self, process_id):
        """
        Replace an existing process
        Must be the same user who posted the process 
        :return:
        """
        response_body = dict()
        user = get_authorized_user()
            
        # Get existing process 
        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS) \
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
                                status=INITIAL_JOB_STATUS, 
                                cwl_link=cwl_link,
                                user=user.id,
                                pipeline_id=pipeline.id,
                                id=existing_process.id,
                                version=existing_process.version)
            db.session.add(deployment)
            db.session.commit()

            # Get the deployment you just committed to access its now assigned job id 
            deployment = db.session \
                    .query(Deployment_db) \
                    .filter_by(id=existing_process.id,version=existing_process.version,status=INITIAL_JOB_STATUS) \
                    .first()

            deployment_job_id = deployment.job_id
        except Exception as ex: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. "+settings.DEPLOY_PROCESS_EXECUTION_VENUE+" is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        response_body["id"] = existing_process.id
        response_body["version"] = existing_process.version
        response_body["deploymentJobsEndpoint"] = "/deploymentJobs/" + str(deployment_job_id)
        response_body["processPipelineLink"] = {"href": pipeline.web_url}
        return response_body, status.HTTP_202_ACCEPTED
    
    @api.doc(security='ApiKeyAuth')
    @login_required()
    def delete(self, process_id):
        """
        Delete an existing process if you created it 
        This just sets the status of the process to undeployed and keeps it in the database 
        :return:
        """
        response_body = dict()
        user = get_authorized_user()
            
        # Get existing process 
        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS) \
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
            # Currently not deleting the process from HySDS, that might change later 
            # job_type = "job-{}:{}".format(existing_process.id, existing_process.version)
            # hysds.delete_mozart_job_type(job_type)
            # Delete from database after successfully deleted from HySDS 
            existing_process.status = "undeployed"
            # db.session.delete(existing_process)
            db.session.commit()
            response_body["detail"] = "Deleted process"
            return response_body, status.HTTP_200_OK 
        except: 
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to process request to delete {}".format(process_id)
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
                    .filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS) \
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
                submitted_time = datetime.now()
                process_job = ProcessJob_db(user=user.id,
                    id=job_id, 
                    submitted_time=submitted_time, 
                    process_id=existing_process.process_id,
                    status=INITIAL_JOB_STATUS)
                db.session.add(process_job)
                db.session.commit()
                response_body = {"title": existing_process.title,
                                "description": existing_process.description,
                                "keywords": existing_process.keywords.split(",") if existing_process.keywords is not None else [],
                                "metadata": [],
                                "id": job_id, 
                                "processID": existing_process.process_id, 
                                "type": None,
                                "request": None,
                                "status": INITIAL_JOB_STATUS,
                                "message": None,
                                "created": submitted_time.isoformat(), 
                                "updated": None,
                                "links": [
                                    {
                                        "href": "/"+ns.name+"/processes/"+str(existing_process.process_id)+"/execution",
                                        "rel": "self",
                                        "type": None,
                                        "hreflang": None,
                                        "title": "Process Execution"
                                    },
                                    {
                                        "href": "/"+ns.name+"/jobs/"+str(job_id),
                                        "rel": "job",
                                        "type": None,
                                        "hreflang": None,
                                        "title": "Job"
                                    }
                                ]
                            }
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
        
@ns.route('/processes/<string:process_id>/package')
class Package(Resource):

    def get(self, process_id):
        """
        Access the formal description that can be used to deploy a process on an OGC API - Processes Server Instance
        :return:
        """
        response_body = dict()
            
        # Get existing process 
        existing_process = db.session \
                    .query(Process_db) \
                    .filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS) \
                    .first()
        
        if existing_process is None:
            response_body["status"] = status.HTTP_404_NOT_FOUND
            response_body["detail"] = "No process with that process ID found"
            return response_body, status.HTTP_404_NOT_FOUND 
        
        response_body["processDescription"] = existing_process.description
        response_body["executionUnit"] = {
                "href": existing_process.cwl_link,
                "rel": "reference",
                "type": None,
                "hreflang": None,
                "title": "Process Reference"
            }
        return response_body, status.HTTP_200_OK 
        

@ns.route('/jobs/<string:job_id>/results')
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
            job_info = response.get("job").get("job_info").get("metrics").get("products_staged")
            traceback = response.get("traceback")
            if job_info is not None:
                for product in job_info:
                    prod = dict()
                    prod["links"] = []
                    clickable_url = "https://s3.console.aws.amazon.com/s3/buckets/"
                    for url in product.get("urls"):
                        prod["links"].append({"href": url})
                        if url.startswith("s3://"):
                            clickable_url += url.split(":80/")[1] + "/?region=us-east-1&tab=overview"
                    prod["links"].append({"href": clickable_url})
                    prod["id"] = product.get("id")
                    prod_list.append(prod)
                    if traceback is not None:
                        # TODO graceal pass prod_list even if failed??
                        response_body["detail"] = "Job failed and traceback is " + str(traceback)
                        return response_body, status.HTTP_200_OK 
                count = 1
                for prod_item in prod_list:
                    response_body[prod_item["id"]] = prod_item
                    count += 1
                return response_body, status.HTTP_200_OK 
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to get job result of job with id: {}. " \
                                                         "{}. If you don't see expected results," \
                                                         " please contact administrator " \
                                                         "of DPS".format(job_id, ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        
@ns.route('/jobs/<string:job_id>')
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
        
        # For now, leave this so it can access all deployed and undeployed processes 
        existing_process = db.session \
            .query(Process_db) \
            .filter_by(process_id=existing_job.process_id) \
            .first()
        
        if not existing_process:
            response_body = {
                "title": None,
                "description": None,
                "keywords": [],
            }
        else:
            response_body = {
                "title": existing_process.title,
                "description": existing_process.description,
                "keywords": existing_process.keywords.split(",") if existing_process.keywords is not None else [], 
            }
        response_body.update({
            "id": job_id,
            "processID": existing_job.process_id,
            # TODO graceal should this be hard coded in if the example options are process, wps, openeo?
            "type": None,
            "request": None,
            "status": None,
            "message": None,
            "created": existing_job.submitted_time.isoformat(),
            "started": None,
            "finished": None,
            "updated": None,
            "progress": None,
            "links": [
                {
                    "href": "/"+ns.name+"/jobs/"+str(job_id),
                    "rel": "self",
                    "type": None,
                    "hreflang": None,
                    "title": "Job Status"
                }
            ]
        })
        
        # Dont update if status is already finished
        # Also if I could get more information from hysds about the job like time to complete, etc. 
        # that would be useful for the client, right now can copy the way that jobs list is doing it 
        if existing_job.status in OGC_FINISHED_STATUSES:
            response_body["status"] = existing_job.status
            # response_body["finished"] = existing_job.completed_time.isoformat()
            return response_body, status.HTTP_200_OK 
        else:
            try:
                # Request to HySDS to check the current status if last checked the job hadnt finished 
                response = hysds.mozart_job_status(job_id=job_id)
                current_status = response.get("status")
                # If the current job status is still the INITIAL_JOB_STATUS and the mozart status is None
                # but the job was submitted less than 10 seconds ago, then 
                # status probably just hasn't updated in mozart yet 
                if existing_job.status == INITIAL_JOB_STATUS and current_status is None and datetime.now() < existing_job.submitted_time + timedelta(seconds=10): 
                    current_status = "job-queued"
                current_status = ogc.hysds_to_ogc_status(current_status)
                response_body["status"] = current_status
                # Only update the current status in the database if it is complete 
                if current_status in OGC_FINISHED_STATUSES:
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

        existing_job = db.session \
            .query(ProcessJob_db) \
            .filter_by(id=job_id) \
            .first()
        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))

            if current_status is None:
                response_body["status"] = status.HTTP_404_NOT_FOUND 
                response_body["detail"] = "Job with id {} not found".format(job_id)
                return response_body, status.HTTP_404_NOT_FOUND 
            
            # This is for the case when user did not wait for a previous dismissal of a job but it was successful
            elif current_status == hysds.STATUS_JOB_REVOKED and existing_job.status != "dismissed":
                existing_job.status = "dismissed"
                db.session.commit()

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

            response_body["id"] = job_id
            response_body["type"] = "process"
            if not wait_for_completion:
                response_body["detail"] = response.decode("utf-8")
                response_body["status"] = "dismissed"
                return response_body, status.HTTP_202_ACCEPTED
            else:
                cancel_job_status = res.get("status")
                response = ogc.status_response(job_id=job_id, job_status=res.get("status"))
                if not cancel_job_status == hysds.STATUS_JOB_COMPLETED:
                    response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR 
                    response_body["detail"] = response.decode("utf-8")
                    return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
                else:
                    response_body["status"] = "dismissed"
                    response_body["detail"] = response.decode("utf-8")
                    existing_job.status = "dismissed"
                    db.session.commit()
                    return response_body, status.HTTP_202_ACCEPTED 
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR 
            response_body["detail"] = "Failed to dismiss job {}. Please try again or contact DPS administrator. {}".format(job_id, ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 

@ns.route('/jobs')
class Jobs(Resource):
    parser = api.parser()
    parser.add_argument('page_size', required=False, type=str, help="Job Listing Pagination Size")
    parser.add_argument('offset', required=False, type=str, help="Job Listing Pagination Offset")
    parser.add_argument('job_type', type=str, help="Job type + version, e.g. topsapp:v1.0", required=False)
    parser.add_argument('tag', type=str, help="User-defined job tag", required=False)
    parser.add_argument('queue', type=str, help="Submitted job queue", required=False)
    parser.add_argument('priority', type=int, help="Job priority, 0-9", required=False)
    parser.add_argument('start_time', type=str, help="Start time of @timestamp field", required=False)
    parser.add_argument('end_time', type=str, help="Start time of @timestamp field", required=False)
    parser.add_argument('get_job_details', type=bool, help="Return full details if True. "
                                                           "List of job id's if false. Default True.", required=False)
    parser.add_argument('status', type=str, help="Job status, e.g. job-started, job-completed, job-failed, etc.",
                        required=False)
    parser.add_argument('username', required=False, type=str, help="Username of job submitter")

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self):
        """
        Returns a list of jobs for a given user

        :param get_job_details: Boolean that returns job details if set to True or just job ID's if set to False. Default is True.
        :param page_size: Page size for pagination
        :param offset: Offset for pagination
        :param status: Job status
        :param end_time: End time
        :param start_time: Start time
        :param min_duration: Minimum duration in seconds
        :param max_duration: Maximum duration in seconds
        :param priority: Job priority
        :param queue: Queue
        :param tag: User tag
        :param process_id: Process ID
        :param username: Username
        :param limit: Limit of jobs to send back
        :return: List of jobs for a given user that matches query params provided
        """

        user = get_authorized_user()
        params = dict(request.args)
        response_body = dict()
        # change process id to job_type and send that so HySDS understands 
        if request.args.get("process_id"):
            existing_process = db.session \
                .query(Process_db) \
                .filter_by(process_id=request.args.get("process_id"), status=DEPLOYED_PROCESS_STATUS) \
                .first()
            if existing_process is not None:
                params["job_type"]="job-"+existing_process.id+":"+existing_process.version
            else:
                response_body["jobs"] = []
                return response_body, status.HTTP_200_OK
            
        # If status is provided, make sure it is HySDS-compliant
        if params.get('status') is not None:
            params['status'] = ogc.get_hysds_status_from_ogc(params['status'])
        response_body, status = hysds.get_mozart_jobs_from_query_params(params, user)
        
        jobs_list = response_body["jobs"]
        # Filter based on start and end times if min/ max duration was passed as a parameter 
        if (request.args.get("min_duration") or request.args.get("max_duration")):
            jobs_in_duration_range = []
            try:
                min_duration = float(request.args.get("min_duration")) if request.args.get("min_duration") else None
                max_duration = float(request.args.get("max_duration")) if request.args.get("max_duration") else None  
            except:
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["detail"] = "Min/ max duration must be able to be converted to integers or floats"
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

            for job in jobs_list:
                try:
                    time_start = job[next(iter(job))]["job"]["job_info"]["time_start"]
                    time_end = job[next(iter(job))]["job"]["job_info"]["time_end"]
                    if time_start and time_end:
                        fmt = "%Y-%m-%dT%H:%M:%S.%f"
                        # Remove the Z and format 
                        start_dt = datetime.strptime(time_start[:-1], fmt)
                        end_dt = datetime.strptime(time_end[:-1], fmt)

                        duration = (end_dt - start_dt).total_seconds()
                        
                        if ((min_duration is None or duration >= min_duration) and
                            (max_duration is None or duration <= max_duration)):
                            jobs_in_duration_range.append(job)
                except Exception as ex:
                    print(ex)
                    print("Unable to determine if job falls in min/max duration range because not in correct format")
            response_body["jobs"] = jobs_in_duration_range
                
        
        # Apply the limit if it was passed as a param
        if response_body["jobs"] and request.args.get("limit"):
            limit = request.args.get("limit")
            if limit.isdigit():
                limit = int(limit)
                response_body["jobs"] = response_body["jobs"][:limit]

        links = []
        jobs_with_required_fields = []
        # Need to get the CWLs to return as links with the jobs 
        for job in response_body["jobs"]:
            try:
                job_with_required_fields = job
                job_with_required_fields["id"] = next(iter(job))
                # TODO graceal should this be hard coded in if the example options are process, wps, openeo?
                job_with_required_fields["type"] = "process"
                hysds_status = job[next(iter(job))]["status"]
                ogc_status = ogc.hysds_to_ogc_status(hysds_status)
                job_with_required_fields["status"] = ogc_status
                links.append({"href": "/"+ns.name+"/job/"+job_with_required_fields["id"]})
                jobs_with_required_fields.append(job_with_required_fields)
            except: 
                print("Error getting job type to get CWLs")
        response_body["links"] = links
        response_body["jobs"] = jobs_with_required_fields
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
        return response_body, status
    
@ns.route('/jobs/<string:job_id>/metrics')
class Status(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def get(self, job_id):
        response_body = dict()
        docker_metrics = None

        try:
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            try:
                mozart_response = hysds.get_mozart_job(job_id)
            except Exception as ex:
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR 
                response_body["detail"] = "Failed to get job information found for {}. Reason: {}".format(job_id, ex)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 

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

            if job_info.get("metrics").get("usage_stats"):
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

            # Create the JSON
            response_body["machine_type"] = instance_typ
            response_body["architecture"] = architecture
            response_body["machine_memory_size"] = memorysize
            response_body["directory_size"] = dir_size
            response_body["operating_system"] = os
            response_body["job_start_time"] = time_start
            response_body["job_end_time"] = time_end
            response_body["job_duration_seconds"] = time_duration

            if docker_metrics:
                response_body["cpu_usage"] = cpu_stats
                response_body["cache_usage"] = cache_stat
                response_body["mem_usage"] = mem_usage
                response_body["max_mem_usage"] = max_mem_usage
                response_body["swap_usage"] = swap_usage
                response_body["read_io_stats"] = read_io_stats
                response_body["write_io_stats"] = write_io_stats
                response_body["sync_io_stats"] = sync_io_stats
                response_body["async_io_stats"] = async_io_stats
                response_body["total_io_stats"] = total_io_stats

            return response_body, status.HTTP_200_OK
        except Exception as ex:
            print("Metrics Exception: {}".format(ex))
            print(ex)
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR 
            response_body["detail"] = "Failed to get job metrics. {}. Please contact administrator of DPS for clarification if needed".format(ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 