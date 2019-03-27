import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.utils.job_id_store as db
import api.settings as settings
import api.utils.ogc_translate as ogc
import json

log = logging.getLogger(__name__)

ns = api.namespace('mas', description='Operations to register an algorithm')


def is_empty(item):
    if item is None or len(item) == 0:
        return True
    else:
        return False


def validate_register_inputs(script_command, algorithm_name):
    if is_empty(script_command):
        raise Exception("Command to run script is required")
    if is_empty(algorithm_name):
        raise Exception("Algorithm Name is required")


@ns.route('/algorithm')
class Register(Resource):

    def post(self):
        """
        This will create the hysds spec files and commit to git
        and registers algorithm container
        Format of JSON to post:
        {
            "script_command" : "python /home/ops/path/to/script.py",
            "algorithm_description" : "Description",
            "algorithm_name" : "name_without_spaces",
            "algorithm_params": [
                {
                "field": "param_name1",
                "download":  true/false
                },
                {
                "field": "param_name2"
                }
            ]
        }

        Sample JSON to post:
        { "script_command" : "python /app/plant.py",
        "algorithm_name" : "plant_test",
         "algorithm_description" : "Test Plant",
         "algorithm_params" : [
              {
              "field": "localize_urls",
              "download": true
              },
              {
              "field": "timestamp"
              }
            ]
        }
        """

        response_body = {"code": None, "message": None}

        try:
            repo = git.git_clone()
        except Exception as ex:
            tb = traceback.format_exc()
            log.debug(ex.message)
            response_body["code"] = 500
            response_body["message"] = "Error during git clone"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body


        try:
            req_data = request.get_json()
            docker_container_url = settings.CONTAINER_URL
            script_command = req_data["script_command"]
            algorithm_name = req_data["algorithm_name"]
            algorithm_description = req_data["algorithm_description"]
            algorithm_params = req_data["algorithm_params"]
            validate_register_inputs(script_command, algorithm_name)

            log.debug("docker_container_url: {}".format(docker_container_url))
            log.debug("script_command: {}".format(script_command))
            log.debug("algorithm_name: {}".format(algorithm_name))
            log.debug("algorithm_description: {}".format(algorithm_description))
            log.debug("algorithm_params: {}".format(algorithm_params))
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to parse parameters"
            try:
                log.debug(ex.message)
                response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            except AttributeError:
                log.debug(ex)
                response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body

        try:
            # creating hysds-io file
            hysds_io = hysds.create_hysds_io(algorithm_description=algorithm_description,
                                             algorithm_params=algorithm_params)

            hysds.write_spec_file(spec_type="hysds-io", algorithm=algorithm_name, body=hysds_io)
            # creating job spec file
            job_spec = hysds.create_job_spec(script_command=script_command, algorithm_params=algorithm_params)
            hysds.write_spec_file(spec_type="job-spec", algorithm=algorithm_name, body=job_spec)
            # creating config file
            config = hysds.create_config_file(docker_container_url=docker_container_url)
            hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "config.txt", config)
            # creating file whose contents are returned on ci build success
            job_submission_json = hysds.get_job_submission_json(algorithm_name, algorithm_params)
            hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME),"job-submission.json",
                             job_submission_json)
            log.debug("Created spec files")
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to create spec files"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body

        try:
            git.update_git_repo(repo, repo_name=settings.REPO_NAME,
                                algorithm_name=hysds.get_algorithm_file_name(algorithm_name))
            log.debug("Updated Git Repo")
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to register {}".format(algorithm_name)
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body

        response_body["code"] = 200
        response_body["message"] = "Successfully registered {}".format(algorithm_name)

        print(response_body)
        return response_body

    def get(self):
        """
        search algorithms
        :return:
        """
        response_body = {"code": None, "message": None}

        try:
            job_list = hysds.get_algorithms().get("result")
            algo_list = list()
            for job_type in job_list:
                algo = dict()
                algo["type"] = job_type.strip("job-").split(":")[0]
                algo["version"] = job_type.strip("job-").split(":")[1]
                algo_list.append(algo)
            response_body["code"] = 200
            response_body["algorithms"] = algo_list
            response_body["message"] = "success"
            return response_body
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedSearch", origin_process="GetAlgorithms",
                            ex_message="Failed to get list of jobs. {}. {}".format(ex.message, tb)),
                            mimetype='text/xml')


@ns.route('/algorithm/<string:algo_id>')
class Describe(Resource):
    def get(self, algo_id):
        """
        request detailed metadata on selected processes offered by a server
        :return:
        """
        try:
            job_type = "job-{}".format(algo_id)
            response = hysds.get_job_spec(job_type)
            params = response.get("result").get("params")
            response_body = ogc.describe_process_response(params)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedDescribeAlgo", origin_process="DescribeProcess",
                                              ex_message="Failed to get parameters for algorithm. {} Traceback: {}"
                                              .format(ex.message, tb)), mimetype='text/xml')


@ns.route('/build')
class Build(Resource):

    def post(self):
        """
        This endpoint is called by CI to acknowledge successful build.
        :return:
        """
        req_data = request.get_json()
        job_type = req_data["job_type"]

        response_body = dict()
        response_body["message"] = "Successfully completed registration of  job type {}".format(job_type)
        response_body["code"] = 200
        response_body["success"] = True

        # add endpoint call to front end

        return response_body




