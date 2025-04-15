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
        # try:
        #     raise Exception
        # except Exception as ex:
        #     error_object = {
        #         "type": "Not Found",
        #         "title": "Not Found",
        #         "status": 404,
        #         "detail": "Error getting processes",
        #         "instance": "Still unclear what this should be from specs "
        #     }
        #     response_body = {"code": status.HTTP_404_NOT_FOUND}
        #     response_body["message"] = [error_object]
        #     return response_body

        # Extract into dif file
        # Next step is to return a model when you call the GET endpoint 

        # if test:
        processes_object = {"processes": [
                {"title": "Process 1",
                "description": "Process 1 description",
                "keywords": [
                    "testing"
                ],
                "metadata": [
                    {
                        "href": "https://github.com/MAAP-Project",
                        "rel": "service",
                        "type": "application/json",
                        "hreflang": "en",
                        "title": "link for metadata",
                        "role": "Role for metadata"
                    }
                ],
                "id": "process-1",
                "version": "1.0.0",
                "jobControlOptions": [
                    "sync-execute"
                ],
                "links": [
                    {
                    "href": "https://github.com/MAAP-Project"
                    }
                ]
            },
            {
                "title": "sardem-sarsen",
                "description": "This application is designed to process Synthetic Aperture Radar (SAR) data from Sentinel-1 GRD (Ground Range Detected) products using a Digital Elevation Model (DEM) obtained from Copernicus. 1:46",
                "keywords": [
                    "ogc", 
                    "sar"
                ],
                "metadata": [
                    {
                        "href": "https://github.com/MAAP-Project",
                        "rel": "service",
                        "type": "application/json",
                        "hreflang": "en",
                        "title": "link for metadata",
                        "role": "Role for metadata"
                    }
                ],
                "id": "repo:softwareVersion",
                "version": "mlucas/nasa_ogc",
                "jobControlOptions": [
                    "sync-execute"
                ],
                "links": [
                    {
                    "href": "https://github.com/MAAP-Project"
                    }
                ]
            }],
            "links": [
                {
                "href": "https://github.com/MAAP-Project"
                },
                {
                "href": "https://github.com/MAAP-Project1"
                }
            ]}

        response_body = {"code": status.HTTP_200_OK, "message": "success"}
        response_body["processes"] = [processes_object]
        return response_body

        # else:
        #     error_object = {
        #         "type": "Not Found",
        #         "title": "Not Found",
        #         "status": 404,
        #         "detail": "No processes found",
        #         "instance": "Still unclear what this should be from specs "
        #     }
        #     response_body = {"code": status.HTTP_404_NOT_FOUND}
        #     response_body["message"] = [error_object]
        #     return response_body

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
                    "version": "2"
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
        process_id = req_data.get("processDescription").get("id")
        process_version = req_data.get("processDescription").get("version")

        existingProcess = db.session \
            .query(Process_db) \
            .filter_by(id=process_id, version=process_version) \
            .first()
        
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
            response_body["id"] = process_id
            response_body["version"] = process_version
            response_body["gitlabWorkflowLink"] = process_workflow_link

            user = get_authorized_user()

            ## in the database, need to store the ID and also the link to the building job 
            # processID should just be incrementing 
            process = Process_db(id=process_id,
                                version=process_version,
                                status="PENDING", # graceal get this constants from somewhere (like Role.ROLE_GUEST)
                                process_workflow_link=process_workflow_link,
                                user=user.id 
                                )
            db.session.add(process)
            db.session.commit()

            return response_body
        else:
            print(f"Error {response.status_code}: {response.text}")  
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to start CI/CD to deploy process. GitLab is likely down"
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
    
