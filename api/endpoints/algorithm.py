import logging
from flask import request
from flask_restplus import Resource
from api.restplus import api
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.settings as settings

log = logging.getLogger(__name__)

ns = api.namespace('algorithm', description='Operations to register an algorithm')
response_body = {"code": None, "message": None}


@ns.route('/register')
class Register(Resource):

    def post(self):
        """
        This will create the hysds spec files and commit to git
        Format of JSON to post:
        {
            "script_command" : "python /home/ops/path/to/script.py",
            "algorithm_description" : "Description",
            "algorithm_name" : "name_without_spaces",
            "algorithm_params": [
            {
                "param_name1": "value"
            },
            {
                "param_name2": "value"
            }
            ]
        }

        Sample JSON to post:
        { "script_command" : "python /home/ops/path/to/script.py",
        "algorithm_name" : "test_slc",
         "algorithm_description" : "Test SLC",
         "algorithm_params" : [
         {
              "localize_url":"https://gsfc-ngap-p-d72c09e1-2d17-5303-b611-b9600db83e8b.s3.amazonaws.com/S1A_IW_SLC__1SDV_20180419T141553_20180419T141620_021537_0251C7_48FB.zip?Expires=1531290148&Signature=CwbE%2BnzG41PN"
              },
              {
              "file":"S1A_IW_SLC__1SDV_20180419T141553_20180419T141620_021537_0251C7_48FB.zip"
              },
              {
              "prod_name" : "S1A_IW_SLC__1SDV_20180419T141553_20180419T141620_021537_0251C7_48FB"
              },
              {
              "prod_date": "2018-07-10"
              },
              {
               "start_time":"2018-10-09T00:00:00:00Z"
            }]
        }
        """
        repo = git.git_clone()

        try:
            req_data = request.get_json()
            docker_container_url = settings.CONTAINER_URL
            script_command = req_data["script_command"]
            algorithm_name = req_data["algorithm_name"]
            algorithm_description = req_data["algorithm_description"]
            algorithm_params = req_data["algorithm_params"]

            log.debug("docker_container_url: {}".format(docker_container_url))
            log.debug("script_command: {}".format(script_command))
            log.debug("algorithm_name: {}".format(algorithm_name))
            log.debug("algorithm_description: {}".format(algorithm_description))
            log.debug("algorithm_params: {}".format(algorithm_params))
        except Exception as ex:
            log.debug(ex.message)
            response_body["status"] = 500
            response_body["message"] = "Failed to parse parameters"
            response_body["error"] = ex.message
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
            # creating file whose contents are returned on ci job success
            job_submission_json = hysds.get_job_submission_json(algorithm_name, algorithm_params)
            hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME),"job-submission.json", job_submission_json)
            log.debug("Created spec files")
        except Exception as ex:
            response_body["status"] = 500
            response_body["message"] = "Failed to create spec files"
            response_body["error"] = ex.message
            return response_body

        git.update_git_repo(repo, repo_name=settings.REPO_NAME,
                            algorithm_name=hysds.get_algorithm_file_name(algorithm_name))
        log.debug("Updated Git Repo")

        response_body["status"] = 200
        response_body["message"] = "Successfully registered {}".format(algorithm_name)

        return response_body

