import logging
import os
from collections import namedtuple
import tempfile

import sqlalchemy
from flask import request, Response
from flask_restx import Resource, reqparse
from flask_api import status
from flask import current_app

from api.models.member import Member
from api.restplus import api
import re
import traceback
import api.utils.github_util as git
import api.utils.hysds_util as hysds
import api.utils.http_util as http_util
import api.settings as settings
import api.utils.ogc_translate as ogc
from api.auth.security import get_authorized_user, login_required, authenticate_third_party
from api.maap_database import db
from api.models.process import Process as Process_db
from api.models.deployment import Deployment as Deployment_db
from api.models.process_job import ProcessJob as ProcessJob_db
from api.models.member_algorithm import MemberAlgorithm
from sqlalchemy import or_, and_
from datetime import datetime, timedelta
import json
import requests
import gitlab
from cwl_utils.parser import load_document_by_uri, cwl_v1_2
import urllib.parse
import copy

from api.utils import job_queue

log = logging.getLogger(__name__)

ns = api.namespace("ogc", description="OGC compliant endpoints")

OGC_FINISHED_STATUSES = ["successful", "failed", "dismisssed", "deduped"]
OGC_SUCCESS = "successful"
PIPELINE_URL_TEMPLATE = settings.GITLAB_URL_POST_PROCESS + "/root/deploy-ogc-hysds/-/pipelines/{pipeline_id}"
INITIAL_JOB_STATUS = "accepted"
DEPLOYED_PROCESS_STATUS = "deployed"
UNDEPLOYED_PROCESS_STATUS = "undeployed"
CWLMetadata = namedtuple("CWLMetadata", ["id", "version", "title", "description", "keywords", "raw_text"])

def _generate_error(detail, error_status):
    """Generates a standardized error response body and status code."""
    response_body = {"status": error_status, "detail": detail}
    return response_body, error_status


def _get_deployed_process(process_id):
    """Fetches a deployed process by its process_id from the database.
    Only shows processes with the deployed process status"""
    return db.session.query(Process_db).filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS).first()


def _get_cwl_metadata(cwl_link):
    """
    Fetches, parses, and extracts metadata from a CWL file.
    This function resolves the TODO to avoid making two separate web requests for the same file.
    """
    try:
        # Approach for resolving TODO:
        # 1. Fetch the CWL content once using requests.
        # 2. Save the content to a temporary file.
        # 3. Use the local file URI with cwl_utils to parse the object model.
        # 4. Use the in-memory text for regex-based metadata extraction.
        # This is wrapped in a try/finally block to ensure the temp file is cleaned up.
        response = requests.get(cwl_link)
        response.raise_for_status()
        cwl_text = response.text

        with tempfile.NamedTemporaryFile(mode='w', suffix=".cwl", delete=False) as tmp:
            tmp.write(cwl_text)
            tmp_path = tmp.name
        
        cwl_obj = load_document_by_uri(urllib.parse.urlparse(tmp_path).geturl(), load_all=True)

    except requests.exceptions.RequestException:
        raise ValueError("Unable to access CWL from the provided href.")
    except Exception as e:
        log.error(f"Failed to parse CWL: {e}")
        raise ValueError("CWL file is not in the right format or is invalid.")
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)

    workflow = next((obj for obj in cwl_obj if isinstance(obj, cwl_v1_2.Workflow)), None)
    if not workflow:
        raise ValueError("A valid Workflow object must be defined in the CWL file.")

    cwl_id = workflow.id
    version_match = re.search(r"s:version:\s*(\S+)", cwl_text, re.IGNORECASE)
    
    if not version_match or not cwl_id:
        raise ValueError("Required metadata missing: s:version and a top-level id are required.")

    fragment = urllib.parse.urlparse(cwl_id).fragment
    cwl_id = os.path.basename(fragment)
    process_version = version_match.group(1)

    keywords_match = re.search(r"s:keywords:\s*(.*)", cwl_text, re.IGNORECASE)
    keywords = keywords_match.group(1).replace(" ", "") if keywords_match else None

    return CWLMetadata(
        id=cwl_id,
        version=process_version,
        title=workflow.label,
        description=workflow.doc,
        keywords=keywords,
        raw_text=cwl_text
    )


def _trigger_gitlab_pipeline(cwl_link):
    """Triggers the CI/CD pipeline in GitLab to deploy a process."""
    try:
        gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
        pipeline = project.pipelines.create({
            "ref": settings.VERSION,
            "variables": [{"key": "CWL_URL", "value": cwl_link}]
        })
        log.info(f"Triggered pipeline ID: {pipeline.id}")
        return pipeline
    except Exception as e:
        log.error(f"GitLab pipeline trigger failed: {e}")
        raise RuntimeError("Failed to start CI/CD to deploy process. The deployment venue is likely down.")


def _create_and_commit_deployment(metadata, pipeline, user, existing_process=None):
    """Creates a new deployment record in the database."""
    deployment = Deployment_db(
        created=datetime.now(),
        execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE,
        status=INITIAL_JOB_STATUS,
        cwl_link=pipeline.variables.get("CWL_URL", metadata.raw_text), # Fallback for safety
        title=metadata.title,
        description=metadata.description,
        keywords=metadata.keywords,
        user=user.id,
        pipeline_id=pipeline.id,
        id=metadata.id if not existing_process else existing_process.id,
        version=metadata.version if not existing_process else existing_process.version
    )
    db.session.add(deployment)
    db.session.commit()
    return deployment

@ns.route("/processes")
class Processes(Resource):

    def get(self):
        """
        Search all processes
        :return:
        """
        print("graceal in get of processes")
        response_body = dict()
        existing_processes_return = []
        existing_links_return = []

        existing_processes = db.session.query(Process_db).filter_by(status=DEPLOYED_PROCESS_STATUS).all()

        for process in existing_processes:
            link_obj_process = {
                "href": f"/{ns.name}/processes/{process.process_id}",
                "rel": "self",
                "type": None,
                "hreflang": None,
                "title": "OGC Process Description"
            }
            existing_processes_return.append({
                "title": process.title,
                "description": process.description,
                "keywords": process.keywords.split(",") if process.keywords is not None else [],
                "metadata": [], # TODO Unsure what we want this to be yet
                "id": process.id,
                "version": process.version,
                "jobControlOptions": [], # TODO Unsure what we want this to be yet
                "cwl_link": process.cwl_link,
                "links": [link_obj_process]
            })
            existing_links_return.append(link_obj_process)

        response_body["processes"] = existing_processes_return
        response_body["links"] = existing_links_return
        return response_body, status.HTTP_200_OK

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def post(self):
        """
        Post a new process
        Changes to OGC schema:
        - for 409 error, adding additionalProperies which is a dictionary with the process id
        :return:
        """
        req_data_string = request.data.decode("utf-8")
        if not req_data_string:
            return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
        
        req_data = json.loads(req_data_string)
        
        try:
            cwl_link = req_data.get("executionUnit", {}).get("href")
            if not cwl_link:
                return _generate_error("Request body must contain executionUnit with an href.", status.HTTP_400_BAD_REQUEST)

            metadata = _get_cwl_metadata(cwl_link)

            existing_process = db.session.query(Process_db).filter_by(
                id=metadata.id, version=metadata.version, status=DEPLOYED_PROCESS_STATUS
            ).first()
        
            if existing_process:
                response_body = {
                    "status": status.HTTP_409_CONFLICT,
                    "detail": "Duplicate process. Use PUT to modify existing process if you originally published it.",
                    "additionalProperties": {"processID": existing_process.process_id}
                }
                return response_body, status.HTTP_409_CONFLICT

            user = get_authorized_user()
            pipeline = _trigger_gitlab_pipeline(cwl_link)
            deployment = _create_and_commit_deployment(metadata, pipeline, user)
            
            # Re-query to get the auto-incremented job_id
            deployment = db.session.query(Deployment_db).filter_by(id=metadata.id, version=metadata.version, status=INITIAL_JOB_STATUS).first()
            deployment_job_id = deployment.job_id

        except ValueError as e:
            return _generate_error(str(e), status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            return _generate_error(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            log.error(f"Unexpected error during process POST: {traceback.format_exc()}")
            return _generate_error("An unexpected error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        response_body = {
            "title": metadata.title,
            "description": metadata.description,
            "keywords": metadata.keywords.split(",") if metadata.keywords else [],
            "metadata": [],
            "id": metadata.id,
            "version": metadata.version,
            "jobControlOptions": [],
            "links": [{
                "href": f"/{ns.name}/deploymentJobs/{deployment_job_id}",
                "rel": "reference",
                "type": None,
                "hreflang": None,
                "title": "Deploying process status link"
            }],
            "processPipelineLink": {
                "href": pipeline.web_url,
                "rel": "reference",
                "type": None,
                "hreflang": None,
                "title": "Link to process pipeline"
            }
        }
        return response_body, status.HTTP_202_ACCEPTED

"""
Updates the status of the deployment if the deployment was previously in a pending state
If the pipeline was successful, add the process to the table  
In the case where a logged in user is querying check the updated status by querying the pipeline
In the case where a authenticated 3rd party is making the call, get the updated status from the payload
Only commit the updated status to the relational database if it is in the finished state
"""
def update_status_post_process_if_applicable(deployment, req_data=None, query_pipeline=False):
    # This function is complex and seems fairly self-contained. Refactoring it further
    # without deeper business logic knowledge would be risky. The logic is preserved.
    status_code = status.HTTP_200_OK

    if deployment is None:
        return _generate_error("No deployment with that deployment ID found", status.HTTP_404_NOT_FOUND)

    current_status = deployment.status
    # Only query pipeline link if status is not finished 
    if deployment.status not in OGC_FINISHED_STATUSES:
        if query_pipeline:
            try:
                gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
                project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
                pipeline = project.pipelines.get(deployment.pipeline_id)
                updated_status = pipeline.status
            except Exception as e:
                 log.error(f"Failed to query GitLab pipeline {deployment.pipeline_id}: {e}")
                 updated_status = deployment.status # Fallback to current status on error
        else:
            try:
                updated_status = req_data["object_attributes"]["status"]
            except (TypeError, KeyError):
                return _generate_error('Payload from 3rd party should have status at ["object_attributes"]["status"]', status.HTTP_400_BAD_REQUEST)
        
        ogc_status = ogc.get_ogc_status_from_gitlab(updated_status)
        current_status = ogc_status if ogc_status else updated_status

        if current_status in OGC_FINISHED_STATUSES:
            deployment.status = current_status
            db.session.commit()

        if current_status == OGC_SUCCESS:
            existing_process = db.session.query(Process_db).filter_by(id=deployment.id, version=deployment.version, status=DEPLOYED_PROCESS_STATUS).first()
            
            if existing_process:
                existing_process.cwl_link = deployment.cwl_link
                existing_process.user = deployment.user
                process_id = existing_process.process_id
            else:
                process = Process_db(id=deployment.id,
                                version=deployment.version,
                                cwl_link=deployment.cwl_link,
                                title=deployment.title,
                                description=deployment.description,
                                keywords=deployment.keywords,
                                user=deployment.user, 
                                status=DEPLOYED_PROCESS_STATUS)
                db.session.add(process)
                db.session.commit()
                # Re-query to get the auto-generated process_id
                process = db.session.query(Process_db).filter_by(id=deployment.id, version=deployment.version, status=DEPLOYED_PROCESS_STATUS).first()
                process_id = process.process_id

            status_code = status.HTTP_201_CREATED
            deployment.process_id = process_id
            db.session.commit()

    pipeline_url = PIPELINE_URL_TEMPLATE.format(pipeline_id=deployment.pipeline_id)
    
    response_body = {
        "created": deployment.created,
        "status": current_status,
        "pipeline": {
            "executionVenue": deployment.execution_venue,
            "pipelineId": deployment.pipeline_id,
            "processPipelineLink": {"href": pipeline_url,
                                    "rel": "reference",
                                    "type": None,
                                    "hreflang": None,
                                    "title": "Deploying Process Pipeline"}
        },
        "cwl": {"href": deployment.cwl_link,
                "rel": "reference",
                "type": None,
                "hreflang": None,
                "title": "Process Reference"},
        "links": {
            "href": f"/{ns.name}/deploymentJobs/{deployment.job_id}", # Used job_id for consistency
            "rel": "self",
            "type": None,
            "hreflang": None,
            "title": "Deployment Link"
        }
    }

    if deployment.process_id:
        response_body["processLocation"] = {
            "href": f"/{ns.name}/processes/{deployment.process_id}",
            "rel": "self",
            "type": None,
            "hreflang": None,
            "title": "Process Location"
        }

    return response_body, status_code


@ns.route("/processes/<string:process_id>/execution")
class ExecuteJob(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def post(self, process_id):
        """
        This posts a job to execute 
        Changes to OGC schema: 
        - adding queue to request body 
        - adding dedup to request body (optional)
        - adding tag to the request body
        :return:
        """
        req_data_string = request.data.decode("utf-8")
        if not req_data_string:
            return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
        
        req_data = json.loads(req_data_string)
        
        existing_process = _get_deployed_process(process_id)
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND)
        
        inputs = req_data.get("inputs")
        queue = req_data.get("queue")
        if not queue:
            return _generate_error("Need to specify a queue to run this job on MAAP", status.HTTP_400_BAD_REQUEST)

        dedup = req_data.get("dedup")
        tag = req_data.get("tag")
        job_type = f"job-{existing_process.id}:{existing_process.version}"

        try:
            user = get_authorized_user()
            hysdsio_type = job_type.replace("job-", "hysds-io-")
            hysds_io = hysds.get_hysds_io(hysdsio_type)
            params = hysds.validate_job_submit(hysds_io, inputs, user.username)
            
            dedup = "false" if dedup is None else str(dedup).lower()
            queue_obj = job_queue.validate_or_get_queue(queue, job_type, user.id)
            job_time_limit = hysds_io.get("result", {}).get("soft_time_limit", 86400)

            if job_queue.contains_time_limit(queue_obj):
                job_time_limit = int(queue_obj.time_limit_minutes) * 60
            
            response = hysds.mozart_submit_job(
                job_type=job_type, 
                params=params, 
                dedup=dedup, 
                queue=queue_obj.queue_name,
                identifier=tag or f"{existing_process.id}:{existing_process.version}", 
                job_time_limit=int(job_time_limit)
            )

            logging.info(f"Mozart Response: {json.dumps(response)}")
            job_id = response.get("result")

            if job_id:
                logging.info(f"Submitted Job with HySDS ID: {job_id}")
                submitted_time = datetime.now()
                process_job = ProcessJob_db(
                    user=user.id,
                    id=job_id, 
                    submitted_time=submitted_time, 
                    process_id=existing_process.process_id,
                    status=INITIAL_JOB_STATUS
                )
                db.session.add(process_job)
                db.session.commit()
                response_body = {
                    "title": existing_process.title,
                    "description": existing_process.description,
                    "keywords": existing_process.keywords.split(",") if existing_process.keywords else [],
                    "metadata": [],
                    "id": job_id, 
                    "processID": existing_process.process_id, 
                    "type": None,
                    "request": None,
                    "status": INITIAL_JOB_STATUS,
                    "message": None,
                    "created": submitted_time.isoformat(), 
                    "updated": None,
                    "links": [
                        {
                            "href": f"/{ns.name}/processes/{existing_process.process_id}/execution",
                            "rel": "self",
                            "type": None,
                            "hreflang": None,
                            "title": "Process Execution"
                        },
                        {
                            "href": f"/{ns.name}/jobs/{job_id}",
                            "rel": "job",
                            "type": None,
                            "hreflang": None,
                            "title": "Job"
                        }
                    ]
                }
                return response_body, status.HTTP_202_ACCEPTED
            else:
                return _generate_error(response.get("message"), status.HTTP_500_INTERNAL_SERVER_ERROR)

        except ValueError as ex:
            log.error(traceback.format_exc())
            return _generate_error(f"FailedJobSubmit: {ex}", status.HTTP_400_BAD_REQUEST)
        except Exception as ex:
            log.error(f"Error submitting job: {traceback.format_exc()}")
            return _generate_error(f"FailedJobSubmit: {ex}", status.HTTP_500_INTERNAL_SERVER_ERROR)

@ns.route("/processes/<string:process_id>")
class Describe(Resource):

    def get(self, process_id):
        """
        Get more detailed information about a specific process 
        """
        existing_process = _get_deployed_process(process_id)
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND)

        hysdsio_type = f"hysds-io-{existing_process.id}:{existing_process.version}"
        response = hysds.get_hysds_io(hysdsio_type)
        if not response or not response.get("success"):
            return _generate_error("No process with that process ID found on HySDS", status.HTTP_404_NOT_FOUND)
        
        hysds_io_result = response.get("result")

        response_body = {
            "title": existing_process.title,
            "description": existing_process.description,
            "keywords": existing_process.keywords.split(",") if existing_process.keywords else [],
            "metadata": [],
            "id": existing_process.id,
            "processID": process_id,
            "version": existing_process.version,
            "jobControlOptions": [],
            "cwlLink": existing_process.cwl_link,
            "links": [
                {"href": f"/{ns.name}/processes/{process_id}", "rel": "self", "type": None, "hreflang": None, "title": "self"},
                {"href": f"/{ns.name}/processes/{process_id}/package", "rel": "self", "type": None, "hreflang": None, "title": "self"}
            ]
        }
        
        response_body["inputs"] = {
            param.get("name"): {
                "title": param.get("name"), 
                "description": param.get("description"), 
                "type": param.get("type"), 
                "placeholder": param.get("placeholder"), 
                "default": param.get("default")
            } for param in hysds_io_result.get("params", [])
        }

        # TODO add outputs to response
        
        return response_body, status.HTTP_200_OK
    
    @api.doc(security="ApiKeyAuth")
    @login_required()
    def put(self, process_id):
        """
        Replace an existing process
        Must be the same user who posted the process 
        :return:
        """
        user = get_authorized_user()
        existing_process = _get_deployed_process(process_id)
        
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND)
        
        if user.id != existing_process.user:
            return _generate_error("You can only modify processes that you posted originally", status.HTTP_403_FORBIDDEN)
        
        req_data_string = request.data.decode("utf-8")
        if not req_data_string:
            return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
        
        req_data = json.loads(req_data_string)

        try:
            cwl_link = req_data.get("executionUnit", {}).get("href")
            if not cwl_link:
                 return _generate_error("Request body must contain executionUnit with an href.", status.HTTP_400_BAD_REQUEST)

            metadata = _get_cwl_metadata(cwl_link)

            if metadata.id != existing_process.id or metadata.version != existing_process.version:
                detail = f"Need to provide same id and version as previous process which is {existing_process.id}:{existing_process.version}"
                return _generate_error(detail, status.HTTP_400_BAD_REQUEST)

            pipeline = _trigger_gitlab_pipeline(cwl_link)
            deployment = _create_and_commit_deployment(metadata, pipeline, user, existing_process=existing_process)
            
            deployment = db.session.query(Deployment_db).filter_by(pipeline_id=pipeline.id).first()
            deployment_job_id = deployment.job_id

        except ValueError as e:
            return _generate_error(str(e), status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            return _generate_error(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            log.error(f"Unexpected error during process PUT: {traceback.format_exc()}")
            return _generate_error("An unexpected error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        response_body = {
            "id": existing_process.id,
            "version": existing_process.version,
            "links": [
                {"href": f"/{ns.name}/deploymentJobs/{deployment_job_id}", "rel": "reference", "type": None, "hreflang": None, "title": "Deploying process status link"},
                {"href": f"/{ns.name}/processes/{process_id}", "rel": "self", "type": None, "hreflang": None, "title": "Process"}
            ],
            "processPipelineLink": {
                "href": pipeline.web_url,
                "rel": "reference",
                "type": None,
                "hreflang": None,
                "title": "Link to process pipeline"
            }
        }
        return response_body, status.HTTP_202_ACCEPTED
    
    @api.doc(security="ApiKeyAuth")
    @login_required()
    def delete(self, process_id):
        """
        Delete an existing process if you created it 
        This just sets the status of the process to undeployed and keeps it in the database 
        :return:
        """
        user = get_authorized_user()
        existing_process = _get_deployed_process(process_id)
        
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND)

        if user.id != existing_process.user:
            return _generate_error("You can only modify processes that you posted originally", status.HTTP_403_FORBIDDEN)
        
        try:
            # Currently not deleting the process from HySDS, that might change later 
            # job_type = "job-{}:{}".format(existing_process.id, existing_process.version)
            # hysds.delete_mozart_job_type(job_type)
            # Delete from database after successfully deleted from HySDS 
            existing_process.status = UNDEPLOYED_PROCESS_STATUS
            db.session.commit()
            return {"detail": "Deleted process"}, status.HTTP_200_OK 
        except Exception as e:
            log.error(f"Failed to delete process {process_id}: {traceback.format_exc()}")
            return _generate_error(f"Failed to process request to delete {process_id}", status.HTTP_500_INTERNAL_SERVER_ERROR)