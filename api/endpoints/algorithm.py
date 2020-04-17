import logging
from flask import request, Response
from flask_restplus import Resource
from api.restplus import api
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.settings as settings
import api.utils.ogc_translate as ogc

log = logging.getLogger(__name__)

ns = api.namespace('mas', description='Operations to register an algorithm')


def is_empty(item):
    if item is None or len(item) == 0:
        return True
    else:
        return False


def validate_register_inputs(script_command, algorithm_name, environment_name):
    if is_empty(script_command):
        raise Exception("Command to run script is required")
    if is_empty(algorithm_name):
        raise Exception("Algorithm Name is required")
    if is_empty(environment_name):
        raise Exception("Environment Name is required")


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
            "repo_url": "http://url/to/repo",
            "code_version": "master",
            "environment_name": "ubuntu",
            "docker_container_url": "http://url/to/container",
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
         "label" : "test plant algorithm",
         "code_version": "master",
         "algorithm_description" : "Test Plant",
         "environment_name": "ubuntu",
         "docker_container_url": "http://url/to/container",
         "repo_url": "http://url/to/repo",



         "algorithm_params" : [
              {
              "field": "localize_urls",
              "download": true
              },
              {
              "field": "timestamp"
              },
              {
              "field": "username"
              }
            ]
        }
        """

        response_body = {"code": None, "message": None}

        try:
            req_data = request.get_json()
            repo = git.git_clone()
        except Exception as ex:
            tb = traceback.format_exc()
            log.debug(ex.message)
            response_body["code"] = 500
            response_body["message"] = "Error during git clone"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, 500

        try:
            req_data = request.get_json()
            script_command = req_data.get("script_command")
            cmd_list = script_command.split(" ")
            docker_cmd = " "
            for index, item in enumerate(cmd_list):
                if "." in item:
                    if item.split(".")[1] in settings.SUPPORTED_EXTENSIONS:
                        cmd_list[index] = "/{}/{}".format("app", item)
            script_command = docker_cmd.join(cmd_list)

            validate_register_inputs(script_command, req_data.get("algorithm_name"), req_data.get("environment_name"))
            algorithm_name = "{}_{}".format(req_data.get("algorithm_name"), req_data.get("environment_name"))
            algorithm_description = req_data.get("algorithm_description")
            algorithm_params = req_data.get("algorithm_params")

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
            return response_body, 500

        try:
            # clean up any old specs from the repo
            repo = git.clean_up_git_repo(repo, repo_name=settings.REPO_NAME)
            # creating hysds-io file
            # adding a mandatory field - username to every spec
            algorithm_params.append({"field": "username"})
            hysds_io = hysds.create_hysds_io(algorithm_description=algorithm_description,
                                             algorithm_params=algorithm_params)
            hysds.write_spec_file(spec_type="hysds-io", algorithm=algorithm_name, body=hysds_io)
            # creating job spec file
            job_spec = hysds.create_job_spec(script_command=script_command, algorithm_params=algorithm_params)
            hysds.write_spec_file(spec_type="job-spec", algorithm=algorithm_name, body=job_spec)

            # creating JSON file with all code information
            if req_data.get("repo_url") is not None:
                repo_url = req_data.get("repo_url")
                split = repo_url.split("://")
                repo_url = "{}://gitlab-ci-token:$TOKEN@{}".format(split[0], split[1])
                repo_name = split[1].split(".git")
                repo_name = repo_name[0][repo_name[0].rfind("/") + 1:]
                code = hysds.create_code_info(repo_url=repo_url, repo_name=repo_name,
                                              docker_container_url=req_data.get("docker_container_url"))
                hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "code_config.json", code)

                # creating config file
                config = hysds.create_config_file(repo_name=repo_name,
                                                  docker_container_url=req_data.get("docker_container_url"),
                                                  repo_url_w_token=req_data.get("repo_url"),
                                                  repo_branch=req_data.get("code_version"))
                hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "config.txt", config)

            # creating file whose contents are returned on ci build success
            if req_data.get("code_version") is not None:
                job_submission_json = hysds.get_job_submission_json(algorithm_name, req_data.get("code_version"))
            else:
                job_submission_json = hysds.get_job_submission_json(algorithm_name)
            hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "job-submission.json",
                             job_submission_json)
            log.debug("Created spec files")
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to create spec files"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, 500

        try:
            git.update_git_repo(repo, repo_name=settings.REPO_NAME,
                                algorithm_name=hysds.get_algorithm_file_name(algorithm_name))
            log.debug("Updated Git Repo")
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to register {}".format(algorithm_name)
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, 500

        response_body["code"] = 200
        response_body["message"] = "Successfully registered {}:{}".format(algorithm_name, req_data.get("code_version"))
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <AlgorithmName></AlgorithmName>
        """

        return response_body

    def get(self):
        """
        search algorithms
        :return:
        """
        response_body = {"code": None, "message": None}

        try:
            job_list = hysds.get_algorithms()
            algo_list = list()
            for job_type in job_list:
                algo = dict()
                algo["type"] = job_type.strip("job-").split(":")[0]
                algo["version"] = job_type.strip("job-").split(":")[1]
                algo_list.append(algo)
            response_body["code"] = 200
            response_body["algorithms"] = algo_list
            response_body["message"] = "success"
            """
            <?xml version="1.0" encoding="UTF-8"?>
            <Algorithms>
            <AlgorithmName></AlgorithmName>
            <AlgorithmName></AlgorithmName>
            ....
            </Algorithms>
            """
            return response_body
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedSearch", origin_process="GetAlgorithms",
                            ex_message="Failed to get list of jobs. {}. {}".format(ex.message, tb)),
                            status=500,
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
            response_body = ogc.describe_process_response(algo_id, params)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(ogc.get_exception(type="FailedDescribeAlgo", origin_process="DescribeProcess",
                                              ex_message="Failed to get parameters for algorithm. {} Traceback: {}"
                                              .format(ex, tb)), status=500, mimetype='text/xml')

    def delete(self, algo_id):
        """
        delete a registered algorithm
        :return:
        """
        response_body = {"code": None, "message": None}
        try:
            algo_id = "job-{}".format(algo_id)
            hysds.delete_mozart_job_type(algo_id)
            response_body["code"] = 200
            response_body["message"] = "successfully deleted {}".format(algo_id)
            """
            <?xml version="1.0" encoding="UTF-8"?>
            <DeletedAlgorithm></DeletedAlgorithm>
            """
            return response_body
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = "Failed to process request to delete {}".format(algo_id)
            response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, 404


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
        response_body["message"] = "Successfully completed registration of job type {}".format(job_type)
        response_body["code"] = 200
        response_body["success"] = True

        # add endpoint call to front end

        return response_body




