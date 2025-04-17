import logging
import os
from collections import namedtuple

import sqlalchemy
from flask import request, Response
from flask_restx import Resource, reqparse
from flask_api import status

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
import time

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
            print("graceal1 eixsting processes ")
            print(process)
            print(process.id)
            print(process.process_id)
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
        # execution unit should be a cwl with the algorithm 
        sample_object = {
                # note that this represents the CWL from the user 
                "executionUnit": {
                    "href": "https://raw.githubusercontent.com/MAAP-Project/sardem-sarsen/refs/heads/mlucas/nasa-ogc/workflows/process_sardem-sarsen_mlucas_nasa-ogc.cwl"
                }
            }
        req_data = sample_object
        response_body = dict()

        # Check if id and version already present in our database
        # Need to get the CWL and parse it for id and version myself 
        id = "test"
        process_version = 1
        
        existingProcess = db.session \
            .query(Process_db) \
            .filter_by(id=id, version=process_version) \
            .first()
        print("graceal existing process is ")
        print(existingProcess)
        
        # If process with same ID and version is already present, tell the user they need to use PUT instead to modify
        if existingProcess is not None:
            response_body["code"] = status.HTTP_409_CONFLICT
            response_body["detail"] = "Duplicate process. Use PUT to modify existing algorithm if you originally published it."
            return response_body, status.HTTP_409_CONFLICT

        user = get_authorized_user()
        cwl_link = req_data.get("executionUnit").get("href")

        # need to create deployment before this call to get the job_id 
        deployment = Deployment_db(created=datetime.now(),
                                execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE, 
                                status="submitted", # TODO not consistent with gitlab status endpoints I think, but can update later 
                                cwl_link = cwl_link,
                                user=user.id,
                                id=id,
                                version=process_version)
        print("graceal1 created deployment and trying to get job_id")
        deployment_job_id = deployment.job_id
        print(deployment_job_id)
        db.session.add(deployment)
        db.session.commit()

        # TODO fix this so that it creates a url right  
        deploymentJobsEndpoint = CURRENT_API_ENDPOINT + ns + "/deploymentJobs/" + deployment_job_id

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

        if response.status_code == status.HTTP_202_ACCEPTED:
            response = response.json()
            print("Success:", response) 
            
            pipeline_id = response['id']
            
            response_body["id"] = id
            response_body["version"] = process_version
            response_body["processPipelineLink"] = process_pipeline_link
            response_body["deploymentJobsEndpoint"] = deploymentJobsEndpoint

            # Update the deployment you just created with the pipeline id and status from gitlab
            existingDeployment = db.session \
                .query(Deployment_db) \
                .filter_by(job_id=deployment_job_id) \
                .first()
            existingDeployment.pipeline_id = pipeline_id

            # TODO need to somehow get this from putting things together and creating the pipeline
            process_pipeline_link = settings.DEPLOY_PROCESS_EXECUTION_LINK + pipeline_id

            # TODO check what first state is, just hard code this in 
            #because already making the cwl request in this function so slow
            existingDeployment.status = "first state" 
            
            db.session.commit()
            return response_body, status.HTTP_202_ACCEPTED
        else:
            # graceal make sure this is edited object correctly 
            existingDeployment = db.session \
                .query(Deployment_db) \
                .filter_by(job_id=deployment_job_id) \
                .first()
            existingDeployment.status = "failed to submit to "+ existingDeployment.execution_venue
            db.session.commit()

            print(f"Error {response.status_code}: {response.text}")  
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. GitLab is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR


@ns.route('/deploymentJobs/<integer:job_id>')
class Deployment(Resource):

    def get(self, job_id):
        deployment = db.session.query(Deployment_db).filter(job_id=job_id).first()

        if (not deployment):
            # TODO return 404 or whatever 
            return None

        # make constant with all possible pending statuses 
        if (deployment.status == "pending"):
            # Only query pipeline link if status is not finished 
            gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
            project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
            pipeline = project.pipelines.get(deployment.pipeline_id)
            deployment.status = pipeline.status
            db.session.commit()

            # if the status has changed to successful, then add to the Process table 
            if (pipeline.status == "successful"):
                existingProcess = db.session \
                    .query(Process_db) \
                    .filter_by(id=deployment.id, version=deployment.version) \
                    .first()
                # if process with same id and version already exist, you just need to overwrite with the same process id 
                if (existingProcess):
                    existingProcess.cwl_link = deployment.cwl_link
                    existingProcess.user = deployment.user
                    process_id = existingProcess.process_id
                else:
                    process = Process_db(id=deployment.id,
                                    version=deployment.version,
                                    cwl_link=deployment.cwl_link,
                                    user=deployment.user)
                    db.session.add(process)
                    process_id = process.process_id
                
                # TODO correct endpoint 
                deployment.process_location = CURRENT_API_ENDPOINT + ns + "/processes/"+process_id
                db.session.commit()
        
        response_body = {
            "created": deployment.created,
            "status": deployment.status,
            "pipeline": {
                "executionVenue": deployment.execution_venue,
                "pipelineId": deployment.pipeline_id,
                "processPipelineLink": settings.DEPLOY_PROCESS_EXECUTION_LINK + deployment.pipeline_id
            },
            "cwl": deployment.cwl_link
        }

        if (deployment.process_location):
            response_body["processLocation"] = deployment.process_location
        return response_body, status.HTTP_200_OK
        
   
@ns.route('/algorithm/<string:process_id>')
class Describe(Resource):

    def get(self, process_id):
        process = db.session.query(Process_db).filter(process_id=process_id).first()
        # Need to get the rest from hysds, figure out how to make calls from Sujen 