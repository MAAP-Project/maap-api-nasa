import logging
import os
from flask import request, Response
from flask_restx import Resource, reqparse
from flask_api import status

from api.models.member import Member
from api.restplus import api
import re
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.settings as settings
import api.utils.ogc_translate as ogc
from api.auth.security import get_authorized_user, login_required
from api.maap_database import db
from api.models.member_algorithm import MemberAlgorithm
from sqlalchemy import or_, and_
from datetime import datetime
import json

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


def validate_register_inputs(run_command, algorithm_name):
    if is_empty(run_command):
        raise Exception("Command to run script is required")
    if is_empty(algorithm_name):
        raise Exception("Algorithm Name is required")


algorithm_visibility_param = reqparse.RequestParser()
algorithm_visibility_param.add_argument('visibility', type=str, required=False,
                                        choices=[visibility_private, visibility_public, visibility_all],
                                        default=visibility_all)


@ns.route('/algorithm')
class Register(Resource):
    parser = api.parser()
    parser.add_argument('run_command', required=True, type=str,
                        help="path to your script relative from the top level of your git repo")
    parser.add_argument('algorithm_description', required=True, type=str,
                        help="Provide a description of what this algorithm does")
    parser.add_argument('algorithm_name', required=False, type=int,
                        help='Appropriately name your algorithm without spaces or -')
    parser.add_argument('repository_url', required=True, type=str,
                        help='Provide the publicly accessible link to your code on git')
    parser.add_argument('algorithm_version', required=True,
                        type=str, help='Version should correspond to a git ref (branch name or tag) in your git repo')
    parser.add_argument('docker_container_url', required=True,
                        type=str,
                        help='Provide the docker images base where your code can run '
                             '(has installed dependency libraries)')
    parser.add_argument('ecosml_verified', required=True,
                        type=bool, help='Specify whether algorithm is EcoSML verified')
    parser.add_argument('queue', required=True,
                        type=str, help='specify recommended queue')
    parser.add_argument('ade_webhook_url', required=False,
                        type=str, help='URL to ADE\'s Webhook')
    parser.add_argument('disk_space', required=True,
                        type=str, help='Specify how much space is needed for algorithm to run in GB '
                                        'e.g. "100GB", "20GB", "10GB"')
    parser.add_argument('inputs', required=True, type=str,
                        help="""Inputs and their types , e.g. [
              {
              "field": "localize_urls",
              "type":  "download"
              },
              {
              "field": "parameter1",
              "type": "positional"
              },
              {
              "field": "runtime_params",
              "type": "config",
              "default": "value"
              }
            ]""")

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        """
        This will create the hysds spec files and commit to git
        and registers algorithm container
        Format of JSON to post:
        {
            "run_command" : "python /home/ops/path/to/script.py",
            "algorithm_description" : "Description",
            "algorithm_name" : "name_without_spaces",
            "repository_url": "http://url/to/repo",
            "code_version": "master",
            "docker_container_url": "http://url/to/container",
            "ecosml_verified": True/False,
            "disk_space": "minimum free disk usage required to run job specified as "\d+(GB|MB|KB)", e.g. "100GB", "20MB", "10KB"",
            "queue": "name of worker based on required memory for algorithm",
            "ade_webhook_url": "url to send algo registration updates to",
            "inputs": {
                "file": [
                    {
                    "field": "param_name1",
                    "type":  "file"
                    }
                ],
                "positional": [
                    {
                    "field": "param_name2",
                    "type": "positional"
                    }
                ],
                "config": [
                    {
                    "name": "param_name3",
                    "type":  "config",
                    "default": "default_val"
                    }
                ]
            }
        }

        Sample JSON to post:
        {
            "run_command" : "sister-isofit/.imgspec/install.sh",
            "build_command": "sister-isofit/.imgspec/install.sh",
            "algorithm_name" : "sister-isofit",
            "algorithm_version": "1.0.0",
            "algorithm_description" : "The SISTER wrapper for ISOFIT. ISOFIT (Imaging Spectrometer Optimal FITting) contains a set of routines and utilities for fitting surface, atmosphere and instrument models to imaging spectrometer data.",

            "docker_container_url": "registry.imgspec.org/root/ade_base_images/plant:latest",
            "repository_url" : "https://gitlab.com/geospec/hytools.git",
            "disk_space": "70GB",
            "queue": "geospec-job_worker-32gb",
            "ecosml_verified": true,
            "inputs" : {
                "positional":
                [
                    {
                        "name": "verbose",
                        "default": "False",
                        "data_type": "boolean"

                    }
                ],
                "file":
                [
                    {
                        "name": "l1_granule"
                    }
                ],
                "config":
                [
                    {
                        "name": "surface_reflectance_spectra"
                    },
                    {
                        "name": "vegetation_reflectance_spectra"
                    },
                    {
                        "name": "water_reflectance_spectra"
                    },
                    {
                        "name": "snow_and_liquids_reflectance_spectra"
                    },
                    {
                        "name": "segmentation_size"
                    },
                    {
                        "name": " n_cores",
                        "default": "32",
                        "data_type": "number"
                    }
                ]
            }
        }

        """

        response_body = dict()

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
            ecosml_verified = request.form.get("ecosml_verified", req_data.get("ecosml_verified", False))
            if type(ecosml_verified) is not bool:
                ecosml_verified = json.loads(ecosml_verified.lower())
            run_command = request.form.get(
                'run_command', req_data.get("run_command"))
            cmd_list = run_command.split(" ")
            docker_cmd = " "
            for index, item in enumerate(cmd_list):
                # update: 2020.12.03: fix: finding extension using "os" library. need to ignore the `.` of the extension
                if os.path.splitext(item)[1][1:] in settings.SUPPORTED_EXTENSIONS:
                    cmd_list[index] = "/{}/{}".format("app", item)
            run_command = docker_cmd.join(cmd_list)

            validate_register_inputs(run_command,
                                     request.form.get("algorithm_name", req_data.get("algorithm_name")))
            algorithm_name = "{}".format(request.form.get("algorithm_name", req_data.get("algorithm_name")))
            algorithm_description = request.form.get("algorithm_description", req_data.get("algorithm_description"))
            inputs = request.form.get("inputs", req_data.get("inputs"))
            disk_space = request.form.get("disk_space", req_data.get("disk_space"))
            resource = request.form.get("queue", req_data.get("queue"))

            log.debug("run_command: {}".format(run_command))
            log.debug("algorithm_name: {}".format(algorithm_name))
            log.debug("algorithm_description: {}".format(algorithm_description))
            log.debug("inputs: {}".format(inputs))
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
            if resource is None:
                resource = settings.DEFAULT_QUEUE
            valid_queues = hysds.get_mozart_queues()
            if resource not in valid_queues:
                response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["message"] = "The resource {} is invalid. Please select from one of {}".format(resource, valid_queues)
                response_body["error"] = "Invalid queue in request: {}".format(req_data)
                return response_body, status.HTTP_400_BAD_REQUEST
            # clean up any old specs from the repo
            repo = git.clean_up_git_repo(repo, repo_name=settings.REPO_NAME)
            # creating hysds-io file
            hysds_io = hysds.create_hysds_io(algorithm_description=algorithm_description,
                                             inputs=inputs,
                                             verified=ecosml_verified
                                             )
            hysds.write_spec_file(spec_type="hysds-io", algorithm=algorithm_name, body=hysds_io)
            # creating job spec file
            job_spec = hysds.create_job_spec(run_command=run_command, inputs=inputs,
                                             disk_usage=disk_space,
                                             queue_name=resource,
                                             verified=ecosml_verified)
            hysds.write_spec_file(spec_type="job-spec", algorithm=algorithm_name, body=job_spec)

            # creating JSON file with all code information
            if request.form.get("repository_url", req_data.get("repository_url")) is not None:
                repository_url = request.form.get("repository_url", req_data.get("repository_url"))
                split = repository_url.split("://")
                # repository_url = "{}://gitlab-ci-token:$TOKEN@{}".format(split[0], split[1])
                repo_name = split[1].split(".git")
                repo_name = repo_name[0][repo_name[0].rfind("/") + 1:]

                # creating config file
                config = hysds.create_config_file(repo_name=repo_name,
                                                  docker_container_url=request.form.get("docker_container_url",
                                                                                        req_data.get("docker_container_url")),
                                                  repo_url_w_token=request.form.get("repository_url",
                                                                                    req_data.get("repository_url")),
                                                  repo_branch=request.form.get("algorithm_version",
                                                                               req_data.get("algorithm_version")),
                                                  build_command=req_data.get("build_command"),
                                                  verified=ecosml_verified)
                hysds.write_file("{}/{}".format(settings.REPO_PATH, settings.REPO_NAME), "config.txt", config)
            else:
                response_body["code"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["message"] = "Please include repo URL in the request"
                response_body["error"] = "Missing key repo_url in request: {}".format(req_data)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

            # creating file whose contents are returned on ci build success
            if request.form.get("algorithm_version", req_data.get("algorithm_version")) is not None:
                job_submission_json = hysds.get_job_submission_json(algorithm_name,
                                                                    request.form.get("algorithm_version",
                                                                                     req_data.get("algorithm_version")))
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
        vis = request.args.get('visibility', 'all')  # fix: defaulting visibility to "all" if the query param is missing

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

    @api.doc(security='ApiKeyAuth')
    @login_required()
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
    @login_required()
    def post(self):
        """
        This endpoint is called by a logged-in user to make an algorithm public
        :return:
        """
        req_data = request.get_json()
        algo_id = req_data["algo_id"]
        version = req_data["version"]
        # m = get_authorized_user()
        member = db.session.query(Member).filter_by(username='imgspecs').first()

        if member is None:
            member = Member(first_name='imgspecs',
                            last_name='imgspecs',
                            username='imgspecs',
                            email='wai.phyo@jpl.nasa.gov',
                            organization='nasa')
            db.session.add(member)
            db.session.commit()
        log.info('imgspecs member id: {}'.format(member.id))
        # ma = MemberAlgorithm(member_id=m.id, algorithm_key="{}:{}".format(algo_id, version), is_public=True,
        #                      creation_date=datetime.utcnow())
        ma = MemberAlgorithm(member_id=member.id, algorithm_key="{}:{}".format(algo_id, version), is_public=True,
                             creation_date=datetime.utcnow())
        db.session.add(ma)
        db.session.commit()

        response_body = dict()
        response_body["message"] = "Successfully published algorithm {}".format(algo_id)
        response_body["code"] = status.HTTP_200_OK
        response_body["success"] = True

        return response_body




