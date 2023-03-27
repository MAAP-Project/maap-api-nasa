import logging
from flask import request, Response
from flask_restx import Resource, reqparse
from flask_api import status
from api.restplus import api
import re
import json
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.settings as settings
import api.utils.ogc_translate as ogc
from api.cas.cas_auth import get_authorized_user, login_required
from api.maap_database import db
from api.models.member_algorithm import MemberAlgorithm
from sqlalchemy import or_, and_
from datetime import datetime

log = logging.getLogger(__name__)

ns = api.namespace('mas', description='Operations to register an algorithm')

visibility_private = "private"
visibility_public = "public"
visibility_all = "all"

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


algorithm_visibility_param = reqparse.RequestParser()
algorithm_visibility_param.add_argument('visibility', type=str, required=False,
                                        choices=[visibility_private, visibility_public, visibility_all],
                                        default=visibility_all)


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
            "disk_space": "minimum free disk usage required to run job specified as "\d+(GB|MB|KB)", e.g. "100GB", "20MB", "10KB"",
            "queue": "name of worker based on required memory for algorithm",
            "ade_webhook_url": "url to send algo registration updates to",
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
         "code_version": "master",
         "algorithm_description" : "Test Plant",
         "environment_name": "ubuntu",
         "docker_container_url": "http://url/to/container",
         "repo_url": "http://url/to/repo",
         "disk_space": "10GB",
         "queue": "maap-worker-8gb",
         "ade_webhook_url": "http://ade/url/webhook",
         "algorithm_params" : [
              {
              "field": "localize_urls",
              "download": true
              },
              {
              "field": "parameter1"
              }
            ]
        }
        """

        response_body = {"code": None, "message": None}

        """
        First, clone the register-job repo from Gitlab
        The CI/CD pipeline of this repo handles the registration of the algorithm specification in HySDS.
        So we need to update the repo with the required files and push the algorithm specs of the one being registered.
        """
        try:
            # remove any trailing commas
            regex = r'''(?<=[}\]"']),(?!\s*[{["'])'''
            req_data_string = request.data.decode("utf-8")
            req_data_string_cleaned = re.sub(regex, '', req_data_string, 0)
            req_data = json.loads(req_data_string_cleaned)
            repo = git.git_clone()
        except Exception as ex:
            tb = traceback.format_exc()
            log.debug(ex.message)
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Error during git clone"
            response_body["error"] = "{} Traceback: {}".format(ex.message, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

        try:
            invalid_attributes = ['timestamp']

            req_data = request.get_json()
            script_command = req_data.get("script_command")
            cmd_list = script_command.split(" ")
            docker_cmd = " "
            for index, item in enumerate(cmd_list):
                if "." in item:
                    if item.split(".")[-1] in settings.SUPPORTED_EXTENSIONS:
                        cmd_list[index] = "/{}/{}".format("app", item)
            script_command = docker_cmd.join(cmd_list)

            validate_register_inputs(script_command, req_data.get("algorithm_name"), req_data.get("environment_name"))
            algorithm_name = "{}_{}".format(req_data.get("algorithm_name"), req_data.get("environment_name"))
            algorithm_description = req_data.get("algorithm_description")
            algorithm_params = list(filter(lambda p: p['field'] not in invalid_attributes, req_data.get("algorithm_params")))
            disk_space = req_data.get("disk_space")
            resource = req_data.get("queue")

            log.debug("script_command: {}".format(script_command))
            log.debug("algorithm_name: {}".format(algorithm_name))
            log.debug("algorithm_description: {}".format(algorithm_description))
            log.debug("algorithm_params: {}".format(algorithm_params))
            log.debug("disk_space: {}".format(disk_space))
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

        try:
            # validate if input queue is valid
            if resource not in hysds.get_mozart_queues():
                response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["message"] = "The resource {} is invalid. Please select from one of {}".format(resource, hysds.get_mozart_queues())
                response_body["error"] = "Invalid queue in request: {}".format(req_data)
            # clean up any old specs from the repo
            repo = git.clean_up_git_repo(repo, repo_name=settings.REPO_NAME)
            # creating hysds-io file
            hysds_io = hysds.create_hysds_io(algorithm_description=algorithm_description,
                                             algorithm_params=algorithm_params)
            hysds.write_spec_file(spec_type="hysds-io", algorithm=algorithm_name, body=hysds_io)
            # creating job spec file
            job_spec = hysds.create_job_spec(script_command=script_command, algorithm_params=algorithm_params,
                                             disk_usage=disk_space,
                                             queue_name=resource)
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
                                                  repo_branch=req_data.get("code_version"),
                                                  build_command=req_data.get("build_command"))
                hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "config.txt", config)
            else:
                response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["message"] = "Please include repo URL in the request"
                response_body["error"] = "Missing key repo_url in request: {}".format(req_data)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

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
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to create spec files"
            response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

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
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <AlgorithmName></AlgorithmName>
        """

        return response_body, status.HTTP_200_OK

    @api.expect(algorithm_visibility_param)
    def get(self):
        """
        search algorithms
        :return:
        """
        response_body = {"code": None, "message": None}
        vis = request.args.get('visibility', None)

        try:
            member_algorithms = self._get_algorithms(vis if vis is not None else visibility_all)
            algo_list = list(map(lambda a: {'type': a.algorithm_key.split(":")[0],
                                            'version': a.algorithm_key.split(":")[1]}, member_algorithms))

            response_body["code"] = status.HTTP_200_OK
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
            msg = str(ex) if ex.message is None else ex.message
            return Response(ogc.get_exception(type="FailedSearch", origin_process="GetAlgorithms",
                            ex_message="Failed to get list of jobs. {}. {}".format(msg, tb)),
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            mimetype='text/xml')

    def _get_algorithms(self, visibility):
        member = get_authorized_user()

        if visibility == visibility_private:
            return [] if member is None else db.session.query(MemberAlgorithm).filter(and_(MemberAlgorithm.member_id == member.id,
                                                                                           not MemberAlgorithm.is_public)).all()
        elif visibility == visibility_all:
            return list(map(lambda a: MemberAlgorithm(algorithm_key=re.sub('^job-', '', a)), hysds.get_algorithms()))
        else:
            if member is None:
                return db.session.query(MemberAlgorithm).filter(MemberAlgorithm.is_public).all()
            else:
                return db.session.query(MemberAlgorithm).filter(or_(MemberAlgorithm.member_id == member.id,
                                                                    MemberAlgorithm.is_public)).all()


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
            queue = response.get("result").get("recommended-queues")[0]
            response_body = ogc.describe_process_response(algo_id, params, queue)
            return Response(response_body, mimetype='text/xml')
        except Exception as ex:
            tb = traceback.format_exc()
            return Response(
                ogc.get_exception(type="FailedDescribeAlgo", origin_process="DescribeProcess",
                                  ex_message="Failed to get parameters for algorithm. {} Traceback: {}"
                                  .format(ex, tb)), status=status.HTTP_500_INTERNAL_SERVER_ERROR, mimetype='text/xml')

    def delete(self, algo_id):
        """
        delete a registered algorithm
        :return:
        """
        response_body = {"code": None, "message": None}
        try:
            algo_id = "job-{}".format(algo_id)
            hysds.delete_mozart_job_type(algo_id)
            response_body["code"] = status.HTTP_200_OK
            response_body["message"] = "successfully deleted {}".format(algo_id)
            """
            <?xml version="1.0" encoding="UTF-8"?>
            <DeletedAlgorithm></DeletedAlgorithm>
            """
            return response_body
        except Exception as ex:
            tb = traceback.format_exc()
            response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["message"] = "Failed to process request to delete {}".format(algo_id)
            response_body["error"] = "{} Traceback: {}".format(ex, tb)
            return response_body, status.HTTP_404_NOT_FOUND


@ns.route('/algorithm/resource')
class ResourceList(Resource):
    def get(self):
        """
        This function would query DPS to see what resources (named based on memory space) are available for
        algorithms to run on.
        :return:
        """
        try:
            response_body = {"code": None, "message": None}
            queues = hysds.get_mozart_queues()
            response_body["code"] = status.HTTP_200_OK
            response_body["queues"] = queues
            response_body["message"] = "success"
            return response_body
        except Exception as ex:
            return Response(ogc.get_exception(type="FailedResource", origin_process="GetAlgorithmsQueues",
                                              ex_message="Failed to get list of queues. {}.".format(ex)),
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            mimetype='text/xml')


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
        response_body["code"] = status.HTTP_200_OK
        response_body["success"] = True

        # add endpoint call to front end

        return response_body


@ns.route('/publish')
class Publish(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required
    def post(self):
        """
        This endpoint is called by a logged-in user to make an algorithm public
        :return:
        """
        req_data = request.get_json()
        algo_id = req_data["algo_id"]
        version = req_data["version"]
        m = get_authorized_user()

        ma = MemberAlgorithm(member_id=m.id, algorithm_key="{}:{}".format(algo_id, version), is_public=True,
                             creation_date=datetime.utcnow())
        db.session.add(ma)
        db.session.commit()

        response_body = dict()
        response_body["message"] = "Successfully published algorithm {}".format(algo_id)
        response_body["code"] = status.HTTP_200_OK
        response_body["success"] = True

        return response_body




