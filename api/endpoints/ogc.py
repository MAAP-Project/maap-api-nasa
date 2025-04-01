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
        # I think schema field for the input might be wrong 
        # I think execution unit should be a cwl with the algorithm 
        sample_object = {"processDescription": {
                    "process": {
                        "title": "sample input process",
                        "description": "testing",
                        "metadata": [
                            {
                                "href": "https://github.com/MAAP-Project",
                                "role": "Role for metadata"
                            }
                        ],
                        "id": "process-1-test",
                        "version": "1.0.0",
                        "inputs": {
                            "additionalProp1": {
                                "title": "input1",
                                "description": "input1",
                                "keywords": [
                                    "string"
                                ],
                                "schema": {
                                    "$ref": "string" 
                                }
                            }
                        }
                    }
                },
                "executionUnit": {
                    "href": "https://github.com/grallewellyn/test-algorithm.git"
                }
            }
        # then need to write to HySDS with this information which bypasses using the relational 
        # database because that is how registering algorithms is done 
        response_body = dict()

        """
        First, clone the register-job repo from Gitlab
        The CI/CD pipeline of this repo handles the registration of the algorithm specification in HySDS.
        So we need to update the repo with the required files and push the algorithm specs of the one being registered.
        """
        try:
            # remove any trailing commas
            # regex = r'''(?<=[}\]"']),(?!\s*[{["'])'''
            # req_data_string = request.data.decode("utf-8")
            # req_data_string_cleaned = re.sub(regex, '', req_data_string, 0)
            # req_data = json.loads(req_data_string_cleaned)
            req_data = sample_object
            repo = git.git_clone()
        except Exception as ex:
            tb = traceback.format_exc()
            log.debug(ex.message)
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Error during git clone"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        print("graceal1 done cloning the register job repo ")

        try:
            invalid_attributes = ['timestamp']

            # req_data = request.get_json()
            # ecosml_verified = request.form.get("ecosml_verified", req_data.get("ecosml_verified", False))
            ecosml_verified = True
            # if type(ecosml_verified) is not bool:
            #     ecosml_verified = json.loads(ecosml_verified.lower())
            # graceal how do we get the run command now? 
            # run_command = request.form.get(
            #     'run_command', req_data.get("run_command"))
            # cmd_list = run_command.split(" ")
            # docker_cmd = " "
            # for index, item in enumerate(cmd_list):
            #     # update: 2020.12.03: fix: finding extension using "os" library. need to ignore the `.` of the extension
            #     if os.path.splitext(item)[1][1:] in settings.SUPPORTED_EXTENSIONS:
            #         cmd_list[index] = "/{}/{}".format("app", item)
            # run_command = docker_cmd.join(cmd_list)
            run_command = ""

            # validate_register_inputs(run_command,
            #                          request.form.get("algorithm_name", req_data.get("algorithm_name")))
            process = req_data.get("processDescription").get("process")
            algorithm_name = "{}".format(request.form.get("algorithm_name", process.get("id")))
            print("graceal1 algorithm name is ")
            print(algorithm_name)
            algorithm_description = request.form.get("algorithm_description", process.get("description"))
            inputs = request.form.get("inputs", process.get("inputs"))
            # disk_space = request.form.get("disk_space", req_data.get("disk_space"))
            disk_space = 1
            # resource = request.form.get("queue", req_data.get("queue"))
            resource = "maap-dps-sandbox"

            # log.debug("run_command: {}".format(run_command))
            log.debug("algorithm_name: {}".format(algorithm_name))
            log.debug("algorithm_description: {}".format(algorithm_description))
            log.debug("inputs: {}".format(inputs))
            # log.debug("disk_space: {}".format(disk_space))
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to parse parameters"
            try:
                log.debug(ex.message)
                response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            except AttributeError:
                log.debug(ex)
                response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        print("graceal1 done getting parameters ")

        try:
            # graceal are we still going to do queues? 
            # validate if input queue is valid
            # user = get_authorized_user()
            # if resource is None:
            #     resource = job_queue.get_default_queue().queue_name
            # else:
            #     valid_queues = job_queue.get_user_queues(user.id)
            #     valid_queue_names = list(map(lambda q: q.queue_name, valid_queues))
            #     if resource not in valid_queue_names:
            #         return http_util.err_response(msg=f"User does not have permissions for resource {resource}."
            #                                           f"Please select from one of {valid_queue_names}",
            #                                       code=status.HTTP_400_BAD_REQUEST)
            # clean up any old specs from the repo
            repo = git.clean_up_git_repo(repo, repo_name=settings.REPO_NAME)
            # creating hysds-io file
            hysds_io = hysds.create_hysds_io_ogc(algorithm_description=algorithm_description,
                                             inputs=inputs,
                                             verified=ecosml_verified
                                             )
            hysds.write_spec_file(spec_type="hysds-io", algorithm=algorithm_name, body=hysds_io)
            # creating job spec file
            job_spec = hysds.create_job_spec_ogc(run_command=run_command, inputs=inputs,
                                             disk_usage=disk_space,
                                             queue_name=resource,
                                             verified=ecosml_verified)
            hysds.write_spec_file(spec_type="job-spec", algorithm=algorithm_name, body=job_spec)

            # creating JSON file with all code information
            if request.form.get("repository_url", req_data.get("executionUnit").get("href")) is not None:
                repository_url = request.form.get("repository_url", req_data.get("executionUnit").get("href"))
                split = repository_url.split("://")
                # repository_url = "{}://gitlab-ci-token:$TOKEN@{}".format(split[0], split[1])
                repo_name = split[1].split(".git")
                repo_name = repo_name[0][repo_name[0].rfind("/") + 1:]

                # creating config file
                config = hysds.create_config_file(repo_name=repo_name,
                                                  docker_container_url='mas.maap-project.org/root/maap-workspaces/custom_images/maap_base:v4.2.0',
                                                  repo_url_w_token=request.form.get("repository_url",
                                                                                    req_data.get("executionUnit").get("href")),
                                                  repo_branch=request.form.get("algorithm_version",
                                                                               process.get("version")),
                                                  build_command=None,
                                                  verified=ecosml_verified)
                hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "config.txt", config)
            else:
                response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["message"] = "Please include repo URL in the request"
                response_body["error"] = "Missing key repo_url in request: {}".format(req_data)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
            print("graceal1 done creating the hysds config file ")

            # creating file whose contents are returned on ci build success
            if request.form.get("algorithm_version", process.get("version")) is not None:
                job_submission_json = hysds.get_job_submission_json(algorithm_name,
                                                                    request.form.get("algorithm_version",
                                                                                     process.get("version")))
            else:
                job_submission_json = hysds.get_job_submission_json(algorithm_name)
            hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "job-submission.json",
                             job_submission_json)
            logging.debug("Created spec files")
            
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to create spec files"
            response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        print("graceal1 done creating spec files ")


        try:
            commit_hash = git.update_git_repo(repo, repo_name=settings.REPO_NAME,
                                              algorithm_name=hysds.get_algorithm_file_name(algorithm_name))
            logging.info("Updated Git Repo with hash {}".format(commit_hash))
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to register {}.".format(algorithm_name)
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        try:
            # Check and return the pipeline info and status
            if commit_hash is None:
                raise Exception("Commit Hash can not be None.")
            gitlab_response = git.get_git_pipeline_status(project_id=settings.REGISTER_JOB_REPO_ID,
                                                          commit_hash=commit_hash)
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to get registration build information."
            response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        response_body["code"] = status.HTTP_200_OK
        response_body["message"] = gitlab_response
        print("graceal1 returning at the end of posting a processes ")
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <AlgorithmName></AlgorithmName>
        """

        return response_body, status.HTTP_200_OK

    
