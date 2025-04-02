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

    # @api.doc(security='ApiKeyAuth')
    # @login_required()
    def post(self):
        """
        post a new process
        :return:
        """
        print("graceal in post of processes in new file")
        # execution unit should be a cwl with the algorithm 
        sample_object = {
                "executionUnit": {
                    "href": "https://github.com/grallewellyn/test-algorithm.git"
                }
            }
        req_data = sample_object
        response_body = dict()

        # Should I update the headers for this to work??

        # url from Sujen to post CWL at payload
        url_to_post_cwl = "https://github.com/MAAP-Project"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        cwl_link = req_data.get("executionUnit").get("href")

        cwl_payload = {"cwl_link": cwl_link}  

        response = requests.post(url_to_post_cwl, json=cwl_payload, headers=headers)

        if response.status_code == status.HTTP_200_OK:
            print("Success:", response.json()) 
            # This is returned by the call to the url that Sujen provides, need to parse this response 
            gitlab_response = "" 
        else:
            # graceal make sure this error shows up okay
            print(f"Error {response.status_code}: {response.text}")  
            response_body["code"] = status.HTTP_400_BAD_REQUEST
            response_body["message"] = "Failed to start CI/CD to dpeloy process. GitLab is likely down"
            response_body["error"] = "Error {}: {}".format(response.status_code, response.text)
            return response_body, status.HTTP_400_BAD_REQUEST

        response_body["code"] = status.HTTP_200_OK
        response_body["message"] = gitlab_response
        print("graceal1 returning at the end of posting a processes ")
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <AlgorithmName></AlgorithmName>
        """

        return response_body, status.HTTP_200_OK

    
