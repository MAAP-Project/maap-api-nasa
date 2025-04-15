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
from api.models.member_algorithm import MemberAlgorithm
from sqlalchemy import or_, and_
from datetime import datetime
import json
import requests

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
            existing_processes.append({'id': process.id, 
                                       'process_id': process.process_id, 
                                       'version': process.version,
                                       'gitlabWorkflowLink': process.process_workflow_link,
                                       'status': process.status})
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
                "processDescription": {
                    "id": "test",
                    "version": "1"
                },
                # note that this represents the CWL from the user 
                "executionUnit": {
                    "href": "https://raw.githubusercontent.com/MAAP-Project/sardem-sarsen/refs/heads/mlucas/nasa-ogc/workflows/process_sardem-sarsen_mlucas_nasa-ogc.cwl"
                }
            }
        req_data = sample_object
        response_body = dict()

        gitlab_post_process_token = settings.GITLAB_POST_PROCESS_TOKEN
        url_to_post_cwl = "https://repo.dit.maap-project.org/api/v4/projects/31/ref/main/trigger/pipeline?token=" + gitlab_post_process_token

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Check if id and version already present in our database
        id = req_data.get("processDescription").get("id")
        process_version = req_data.get("processDescription").get("version")
        
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

        cwl_link = req_data.get("executionUnit").get("href")
        cwl_payload = {"CWL_URL": cwl_link}  

        response = requests.post(url_to_post_cwl, json=cwl_payload, headers=headers)

        if response.status_code == status.HTTP_201_CREATED:
            response = response.json()
            print("Success:", response) 
            process_workflow_link = response['web_url']
            response_body["code"] = status.HTTP_201_CREATED
            response_body["id"] = id
            response_body["version"] = process_version
            response_body["gitlabWorkflowLink"] = process_workflow_link

            user = get_authorized_user()

            ## in the database, need to store the ID and also the link to the building job 
            # processID should just be incrementing 
            process = Process_db(id=id,
                                version=process_version,
                                status="PENDING", # graceal get this constants from somewhere (like Role.ROLE_GUEST)
                                process_workflow_link=process_workflow_link,
                                cwl_link = cwl_link,
                                user=user.id
                                )
            db.session.add(process)
            db.session.commit()

            return response_body, status.HTTP_201_CREATED
        else:
            print(f"Error {response.status_code}: {response.text}")  
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. GitLab is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        
@ns.route('/algorithm/<string:process_id>')
class Describe(Resource):
    def get(self, process_id):
        # Remember to do laxy loading, unsure how to get updated status
        db.session.query(Process_db).filter(process_id=process_id).first()
        # Need to get the rest from hysds 