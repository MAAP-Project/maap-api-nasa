import logging
import os
from collections import namedtuple
import tempfile

from flask import request
from flask_restx import Resource
from flask_api import status

from api.restplus import api
import re
import traceback
import api.utils.hysds_util as hysds
import api.settings as settings
import api.utils.ogc_translate as ogc
from api.auth.security import get_authorized_user, login_required, authenticate_third_party
from api.maap_database import db
from api.models.process import Process as Process_db
from api.models.deployment import Deployment as Deployment_db
from api.models.process_job import ProcessJob as ProcessJob_db
from api.models.member import Member as Member_db
from datetime import datetime, timedelta
import json
import requests
import gitlab
from cwl_utils.parser import load_document_by_uri, cwl_v1_2
import urllib.parse

from api.utils import job_queue

log = logging.getLogger(__name__)

ns = api.namespace("ogc", description="OGC compliant endpoints")

OGC_FINISHED_STATUSES = ["successful", "failed", "dismisssed", "deduped"]
OGC_SUCCESS = "successful"
PIPELINE_URL_TEMPLATE = settings.GITLAB_URL_POST_PROCESS + "/root/deploy-ogc-hysds/-/pipelines/{pipeline_id}"
INITIAL_JOB_STATUS = "accepted"
DEPLOYED_PROCESS_STATUS = "deployed"
UNDEPLOYED_PROCESS_STATUS = "undeployed"
CWL_METADATA = namedtuple("CWL_METADATA", ["id", "version", "title", "description", "keywords", "raw_text", "github_url", "git_commit_hash", "cwl_link", "ram_min", "cores_min", "base_command", "author"])
HREF_LANG = "en"
ERROR_TYPE_PREFIX="http://www.opengis.net/def/exceptions/"

def _generate_error(detail, error_status, error_type=None):
    """Generates a standardized error response body and status code."""
    full_error_type = f"{ERROR_TYPE_PREFIX}{error_type}" if error_type is not None else None
    response_body = {"type": full_error_type,
                    "title": detail,
                    "status": error_status,
                    "detail": detail,
                    "instance": ""} #TODO Description for this field: A URI reference that identifies the specific occurrence of the problem. Keep null for now 
    return response_body, error_status


def _get_deployed_process(process_id):
    """Fetches a deployed process by its process_id from the database.
    Only shows processes with the deployed process status"""
    return db.session.query(Process_db).filter_by(process_id=process_id, status=DEPLOYED_PROCESS_STATUS).first()


def _get_cwl_metadata(cwl_link):
    """
    Fetches, parses, and extracts metadata from a CWL file. This approach avoid making 
    two separate web requests for the same file
    """
    try:
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

    # Get git information
    github_url = re.search(r"s:codeRepository:\s*(\S+)", cwl_text, re.IGNORECASE)
    github_url = github_url.group(1) if github_url else None
    git_commit_hash = re.search(r"s:commitHash:\s*(\S+)", cwl_text, re.IGNORECASE)
    git_commit_hash = git_commit_hash.group(1) if git_commit_hash else None

    keywords_match = re.search(r"s:keywords:\s*(.*)", cwl_text, re.IGNORECASE)
    keywords = keywords_match.group(1).replace(" ", "") if keywords_match else None

    try:
        author_match = re.search(
            r"s:author:.*?s:name:\s*(\S+)",
            cwl_text,
            re.DOTALL | re.IGNORECASE
        )
        author = author_match.group(1) if author_match else None
    except Exception as e:
        author = None
        log.error(f"Failed to get author name: {e}")

    # Find the CommandLineTool run by the first step of the workflow
    if workflow.steps:
        # Get the ID of the tool to run (e.g., '#main')
        tool_id_ref = workflow.steps[0].run
        # The actual ID is the part after the '#'
        tool_id = os.path.basename(tool_id_ref)

        #Find the CommandLineTool object in the parsed CWL graph
        command_line_tool = next((obj for obj in cwl_obj if isinstance(obj, cwl_v1_2.CommandLineTool) and obj.id.endswith(tool_id)), None)
    
        if command_line_tool:
            # Extract the baseCommand directly
            base_command = command_line_tool.baseCommand
    
            # Find the ResourceRequirement to extract ramMin and coresMin
            if command_line_tool.requirements:
                for req in command_line_tool.requirements:
                    if isinstance(req, cwl_v1_2.ResourceRequirement):
                        ram_min = req.ramMin if req.ramMin else ram_min
                        cores_min = req.coresMin if req.coresMin else cores_min
                        break # Stop after finding the first ResourceRequirement

    return CWL_METADATA(
        id=cwl_id,
        version=process_version,
        title=workflow.label,
        description=workflow.doc,
        keywords=keywords,
        raw_text=cwl_text,
        github_url=github_url,
        git_commit_hash=git_commit_hash,
        cwl_link=cwl_link,
        ram_min=ram_min,
        cores_min=cores_min,
        base_command=base_command,
        author=author
    )


def _trigger_gitlab_pipeline(cwl_link, version):
    """Triggers the CI/CD pipeline in GitLab to deploy a process."""
    try:
        # random process name to allow algorithms later having the same id/version if the deployer is different 
        process_name_hysds = datetime.now().isoformat()+os.urandom(10).hex()
        gl = gitlab.Gitlab(settings.GITLAB_URL_POST_PROCESS, private_token=settings.GITLAB_POST_PROCESS_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
        pipeline = project.pipelines.create({
            "ref": settings.VERSION,
            "variables": [{"key": "CWL_URL", "value": cwl_link}, {"key": "PROCESS_NAME_HYSDS", "value": process_name_hysds}]
        })
        process_name_hysds = process_name_hysds+":"+version
        log.info(f"Triggered pipeline ID: {pipeline.id}")
        return pipeline, process_name_hysds
    except Exception as e:
        log.error(f"GitLab pipeline trigger failed: {e}")
        raise RuntimeError("Failed to start CI/CD to deploy process. The deployment venue is likely down.")


def _create_and_commit_deployment(metadata, pipeline, user, process_name_hysds, existing_process=None):
    """Creates a new deployment record in the database."""
    deployment = Deployment_db(
        created=datetime.now(),
        process_name_hysds=process_name_hysds,
        execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE,
        status=INITIAL_JOB_STATUS,
        cwl_link=metadata.cwl_link, 
        title=metadata.title,
        description=metadata.description,
        keywords=metadata.keywords,
        deployer=user.id,
        author=metadata.author,
        pipeline_id=pipeline.id,
        github_url=metadata.github_url,
        git_commit_hash=metadata.git_commit_hash,
        id=metadata.id if not existing_process else existing_process.id,
        version=metadata.version if not existing_process else existing_process.version,
        ram_min = metadata.ram_min,
        cores_min = metadata.cores_min,
        base_command = metadata.base_command
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
        response_body = dict()
        existing_processes_return = []
        existing_links_return = []

        existing_processes = db.session.query(Process_db).filter_by(status=DEPLOYED_PROCESS_STATUS).all()

        for process in existing_processes:
            deployer = db.session.query(Member_db).filter_by(id=process.deployer).first()
            link_obj_process = {
                "href": f"/{ns.name}/processes/{process.process_id}",
                "rel": "self",
                "type": "application/json",
                "hreflang": HREF_LANG,
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
                "author": process.author,
                "deployedBy": deployer.username,
                "lastModifiedTime": process.last_modified_time.isoformat(),
                "cwlLink": process.cwl_link,
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

            user = get_authorized_user()
            if existing_process and existing_process.deployer == user.id:
                response_body, code = _generate_error("Duplicate process. Use PUT to modify existing process if you originally published it.", status.HTTP_409_CONFLICT, "ogcapi-processes-2/1.0/duplicated-process")
                response_body["additionalProperties"] = {"processID": existing_process.process_id}
                return response_body, code

            pipeline, process_name_hysds = _trigger_gitlab_pipeline(cwl_link, metadata.version)
            deployment = _create_and_commit_deployment(metadata, pipeline, user, process_name_hysds)
            
            # Re-query to get the auto-incremented job_id
            deployment = db.session.query(Deployment_db).filter_by(id=metadata.id, version=metadata.version, status=INITIAL_JOB_STATUS).first()
            deployment_job_id = deployment.job_id

        except ValueError as e:
            return _generate_error(str(e), status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            return _generate_error(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f"Unexpected error during process POST: {traceback.format_exc()}")
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
                "rel": "monitor",
                "type": "application/json",
                "hreflang": HREF_LANG,
                "title": "Deploying process status link"
            }],
            "processPipelineLink": {
                "href": pipeline.web_url,
                "rel": "monitor",
                "type": "text/html",
                "hreflang": HREF_LANG,
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
                existing_process.deployer = deployment.deployer
                process_id = existing_process.process_id
                existing_process.github_url=deployment.github_url
                existing_process.git_commit_hash=deployment.git_commit_hash
                existing_process.last_modified_time=datetime.now()
            else:
                process = Process_db(id=deployment.id,
                                version=deployment.version,
                                process_name_hysds=deployment.process_name_hysds,
                                cwl_link=deployment.cwl_link,
                                title=deployment.title,
                                description=deployment.description,
                                keywords=deployment.keywords,
                                deployer=deployment.deployer, 
                                author=deployment.author,
                                github_url=deployment.github_url,
                                git_commit_hash=deployment.git_commit_hash,
                                last_modified_time=datetime.now(),
                                status=DEPLOYED_PROCESS_STATUS,
                                ram_min=deployment.ram_min,
                                cores_min=deployment.cores_min,
                                base_command=deployment.base_command)
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
                                    "rel": "monitor",
                                    "type": 'text/html',
                                    "hreflang": HREF_LANG,
                                    "title": "Deploying Process Pipeline"}
        },
        "cwl": {"href": deployment.cwl_link,
                "rel": "service-desc",
                "type": "application/cwl",
                "hreflang": HREF_LANG,
                "title": "Process Reference"},
        "links": {
            "href": f"/{ns.name}/deploymentJobs/{deployment.job_id}", # Used job_id for consistency
            "rel": "self",
            "type": "application/json",
            "hreflang": HREF_LANG,
            "title": "Deployment Link"
        }
    }

    if deployment.process_id:
        response_body["processLocation"] = {
            "href": f"/{ns.name}/processes/{deployment.process_id}",
            "rel": "service-doc",
            "type": "application/json",
            "hreflang": HREF_LANG,
            "title": "Process Location"
        }

    return response_body, status_code

@ns.route("/deploymentJobs/<string:deployment_id>")
class Deployment(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, deployment_id):
        """
        Query the current status of an algorithm being deployed 
        """
        deployment = db.session.query(Deployment_db).filter_by(job_id=deployment_id).first()
        response_body, status_code = update_status_post_process_if_applicable(deployment, req_data=None, query_pipeline=True)
        
        return response_body, status_code
    
@ns.route("/deploymentJobs")
class Deployment(Resource):

    @api.doc(security="ApiKeyAuth")
    @authenticate_third_party()
    def post(self):
        """
        Called by authenticated 3rd parties to update the status of a deploying process via webhooks
        :return:
        """
        response_body = dict()
        try:
            req_data_string = request.data.decode("utf-8")
            if not req_data_string:
                return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
            
            req_data = json.loads(req_data_string)
            pipeline_id = req_data["object_attributes"]["id"]
        except:
            return _generate_error('Expected request body to include job_id at ["object_attributes"]["id"]]', status.HTTP_400_BAD_REQUEST)
        
        # Filtering by current execution venue because pipeline id not guaranteed to be unique across different
        # deployment venues, so check for the current one 
        deployment = db.session.query(Deployment_db).filter_by(pipeline_id=pipeline_id,execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE).first()
        response_body, status_code = update_status_post_process_if_applicable(deployment, req_data, query_pipeline=False)

        return response_body, status_code

@ns.route("/processes/<string:process_id>")
class Describe(Resource):

    def get(self, process_id):
        """
        Get more detailed information about a specific process 
        """
        existing_process = _get_deployed_process(process_id)
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")

        hysdsio_type = f"hysds-io-{existing_process.process_name_hysds}"
        response = hysds.get_hysds_io(hysdsio_type)
        if not response or not response.get("success"):
            return _generate_error("No process with that process ID found on HySDS", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")
        
        hysds_io_result = response.get("result")

        deployer = db.session.query(Member_db).filter_by(id=existing_process.deployer).first()

        response_body = {
            "title": existing_process.title,
            "description": existing_process.description,
            "keywords": existing_process.keywords.split(",") if existing_process.keywords else [],
            "metadata": [],
            "id": existing_process.id,
            "processID": process_id,
            "version": existing_process.version,
            "jobControlOptions": [],
            "author": existing_process.author,
            "deployedBy": deployer.username,
            "githubUrl": existing_process.github_url,
            "gitCommitHash": existing_process.git_commit_hash,
            "cwlLink": existing_process.cwl_link,
            "ramMin": existing_process.ram_min,
            "coresMin": existing_process.cores_min,
            "baseCommand": existing_process.base_command,
            "links": [
                {"href": f"/{ns.name}/processes/{process_id}", "rel": "self", "type": "application/json", "hreflang": HREF_LANG, "title": "OGC Process Description"},
                {"href": f"/{ns.name}/processes/{process_id}/package", "rel": "service-desc", "type": "application/json", "hreflang": HREF_LANG, "title": "OGC Process Package Description"}
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
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")
        
        if user.id != existing_process.deployer:
            return _generate_error("You can only modify processes that you posted originally", status.HTTP_403_FORBIDDEN, "ogcapi-processes-2/1.0/immutable-process")
        
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

            pipeline, process_name_hysds = _trigger_gitlab_pipeline(cwl_link, metadata.version)
            deployment = _create_and_commit_deployment(metadata, pipeline, user, process_name_hysds, existing_process)
            
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
                {"href": f"/{ns.name}/deploymentJobs/{deployment_job_id}", "rel": "monitor", "type": "application/json", "hreflang": HREF_LANG, "title": "Deploying process status link"},
                {"href": f"/{ns.name}/processes/{process_id}", "rel": "self", "type": "application/json", "hreflang": HREF_LANG, "title": "Process"}
            ],
            "processPipelineLink": {
                "href": pipeline.web_url,
                "rel": "monitor",
                "type": "text/html",
                "hreflang": HREF_LANG,
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
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")

        if user.id != existing_process.deployer:
            return _generate_error("You can only modify processes that you posted originally", status.HTTP_403_FORBIDDEN, "ogcapi-processes-2/1.0/immutable-process")
        
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
        
@ns.route("/processes/<string:process_id>/package")
class Package(Resource):

    def get(self, process_id):
        """
        Access the formal description that can be used to deploy a process on an OGC API - Processes Server Instance
        :return:
        """
        response_body = dict()
            
        existing_process = _get_deployed_process(process_id)
        if not existing_process:
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")
        
        response_body["processDescription"] = existing_process.description
        response_body["executionUnit"] = {
                "href": existing_process.cwl_link,
                "rel": "monitor-desc",
                "type": "text/html",
                "hreflang": HREF_LANG,
                "title": "Process Reference"
            }
        return response_body, status.HTTP_200_OK 

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
            return _generate_error("No process with that process ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-process")
        
        inputs = req_data.get("inputs")
        queue = req_data.get("queue")
        if not queue:
            return _generate_error("Need to specify a queue to run this job on MAAP", status.HTTP_400_BAD_REQUEST)

        dedup = req_data.get("dedup")
        tag = req_data.get("tag")
        job_type = f"job-{existing_process.process_name_hysds}"

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
                identifier=tag or existing_process.process_name_hysds, 
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
                            "type": "application/json",
                            "hreflang": HREF_LANG,
                            "title": "Process Execution"
                        },
                        {
                            "href": f"/{ns.name}/jobs/{job_id}",
                            "rel": "monitor",
                            "type": "application/json",
                            "hreflang": HREF_LANG,
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

@ns.route("/jobs/<string:job_id>/results")
class Result(Resource):
    
    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, job_id):
        """
        This will return the result of the job that successfully completed or failed. If job failed, you can see the
         error traceback.
        :return:
        """
        response_body = dict()

        try:
            prod_list = list()
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            existing_job = db.session \
                .query(ProcessJob_db) \
                .filter_by(id=job_id) \
                .first()
            if existing_job is None:
                return _generate_error("No job with that job ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-job")

            response = hysds.get_mozart_job(existing_job.id)
            job_info = response.get("job").get("job_info").get("metrics").get("products_staged")
            traceback = response.get("traceback")
            if job_info is not None:
                for product in job_info:
                    prod = dict()
                    prod["links"] = []
                    clickable_url = "https://s3.console.aws.amazon.com/s3/buckets/"
                    for url in product.get("urls"):
                        prod["links"].append({"href": url})
                        if url.startswith("s3://"):
                            clickable_url += url.split(":80/")[1] + "/?region=us-east-1&tab=overview"
                    prod["links"].append({"href": clickable_url})
                    prod["id"] = product.get("id")
                    prod_list.append(prod)
                    if traceback is not None:
                        # TODO graceal pass prod_list even if failed??
                        response_body["detail"] = "Job failed and traceback is " + str(traceback)
                        return response_body, status.HTTP_200_OK 
                count = 1
                for prod_item in prod_list:
                    response_body["additionalProp"+str(count)] = prod_item
                    count += 1
                return response_body, status.HTTP_200_OK 
        except Exception as ex:
            response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
            response_body["detail"] = "Failed to get job result of job with id: {}. " \
                                                         "{}. If you don't see expected results," \
                                                         " please contact administrator " \
                                                         "of DPS".format(job_id, ex)
            return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR
        

@ns.route("/jobs/<string:job_id>")
class Status(Resource):
    parser = api.parser()
    parser.add_argument("wait_for_completion", default=False, required=False, type=bool,
                        help="Wait for Cancel job to finish")

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, job_id):
        """
        Shows the status of the job
        :return:
        """
        response_body = dict()

        existing_job = db.session \
            .query(ProcessJob_db) \
            .filter_by(id=job_id) \
            .first()
        if existing_job is None:
            return _generate_error("No job with that job ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-job")
        
        # For now, leave this so it can access all deployed and undeployed processes 
        existing_process = db.session \
            .query(Process_db) \
            .filter_by(process_id=existing_job.process_id) \
            .first()
        
        if not existing_process:
            response_body = {
                "title": None,
                "description": None,
                "keywords": [],
            }
        else:
            response_body = {
                "title": existing_process.title,
                "description": existing_process.description,
                "keywords": existing_process.keywords.split(",") if existing_process.keywords is not None else [], 
            }
        response_body.update({
            "id": job_id,
            "processID": existing_job.process_id,
            # TODO graceal should this be hard coded in if the example options are process, wps, openeo?
            "type": None,
            "request": None,
            "status": None,
            "message": None,
            "created": existing_job.submitted_time.isoformat(),
            "started": None,
            "finished": None,
            "updated": None,
            "progress": None,
            "links": [
                {
                    "href": "/"+ns.name+"/jobs/"+str(job_id),
                    "rel": "self",
                    "type": "application/json",
                    "hreflang": HREF_LANG,
                    "title": "Job Status"
                }
            ]
        })
        
        # Dont update if status is already finished
        # Also if I could get more information from hysds about the job like time to complete, etc. 
        # that would be useful for the client, right now can copy the way that jobs list is doing it 
        if existing_job.status in OGC_FINISHED_STATUSES:
            response_body["status"] = existing_job.status
            # response_body["finished"] = existing_job.completed_time.isoformat()
            return response_body, status.HTTP_200_OK 
        else:
            try:
                # Request to HySDS to check the current status if last checked the job hadnt finished 
                response = hysds.mozart_job_status(job_id=job_id)
                current_status = response.get("status")
                # If the current job status is still the INITIAL_JOB_STATUS and the mozart status is None
                # but the job was submitted less than 10 seconds ago, then 
                # status probably just hasn't updated in mozart yet 
                if existing_job.status == INITIAL_JOB_STATUS and current_status is None and datetime.now() < existing_job.submitted_time + timedelta(seconds=10): 
                    current_status = "job-queued"
                current_status = ogc.hysds_to_ogc_status(current_status)
                response_body["status"] = current_status
                # Only update the current status in the database if it is complete 
                if current_status in OGC_FINISHED_STATUSES:
                    existing_job.status = current_status
                    db.session.commit()
                return response_body, status.HTTP_200_OK 
            except: 
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["detail"] = "Failed to get job status of job with id: {}. " \
                                              "Please check back a little later for " \
                                              "job execution status. If still not found," \
                                              " please contact administrator " \
                                              "of DPS".format(job_id)
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR 
    
    @api.doc(security="ApiKeyAuth")
    @login_required() 
    def delete(self, job_id):
        """
        This will cancel a running job or delete a queued job
        :return:
        """
        response_body = dict()
        # Since this can take a long time, we dont wait by default.
        wait_for_completion = request.args.get("wait_for_completion", False)

        existing_job = db.session \
            .query(ProcessJob_db) \
            .filter_by(id=job_id) \
            .first()
        if existing_job is None:
            return _generate_error("No job with that job ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-job")

        try:
            # check if job is non-running
            current_status = hysds.mozart_job_status(job_id).get("status")
            logging.info("current job status: {}".format(current_status))

            if current_status is None:
                return _generate_error("No job with that job ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-job")
            
            # This is for the case when user did not wait for a previous dismissal of a job but it was successful
            elif current_status == hysds.STATUS_JOB_REVOKED and existing_job.status != "dismissed":
                existing_job.status = "dismissed"
                db.session.commit()

            # Revoke if job started
            elif current_status == hysds.STATUS_JOB_STARTED:
                logging.info("Submitting Revoke job for Job {}".format(job_id))
                purge_id, res = hysds.revoke_mozart_job(job_id=job_id, wait_for_completion=wait_for_completion)
                logging.info("Revoke Job Submission Response: {} {}".format(purge_id, res))
                response = ogc.status_response(job_id=job_id, job_status=hysds.STATUS_JOB_QUEUED)

            # Purge if job queued
            elif current_status == hysds.STATUS_JOB_QUEUED:
                logging.info("Submitting Purge job for Job {}".format(job_id))
                purge_id, res = hysds.delete_mozart_job(job_id=job_id, wait_for_completion=wait_for_completion)
                logging.info("Purge Job Submission Response: {} {}".format(purge_id, res))
                response = ogc.status_response(job_id=job_id, job_status=hysds.STATUS_JOB_QUEUED)
            # For all other statuses, we cannot cancel
            else:
                return _generate_error("Not allowed to cancel job with status {}".format(current_status), status.HTTP_400_BAD_REQUEST)

            response_body["id"] = job_id
            response_body["type"] = "process"
            if not wait_for_completion:
                response_body["detail"] = response.decode("utf-8")
                response_body["status"] = "dismissed"
                return response_body, status.HTTP_202_ACCEPTED
            else:
                cancel_job_status = res.get("status")
                response = ogc.status_response(job_id=job_id, job_status=res.get("status"))
                if not cancel_job_status == hysds.STATUS_JOB_COMPLETED:
                    return _generate_error(response.decode("utf-8"), status.HTTP_500_INTERNAL_SERVER_ERROR)
                else:
                    response_body["status"] = "dismissed"
                    response_body["detail"] = response.decode("utf-8")
                    existing_job.status = "dismissed"
                    db.session.commit()
                    return response_body, status.HTTP_202_ACCEPTED 
        except Exception as ex:
            return _generate_error("Failed to dismiss job {}. Please try again or contact DPS administrator. {}".format(job_id, ex), status.HTTP_500_INTERNAL_SERVER_ERROR)
        
@ns.route("/jobs")
class Jobs(Resource):
    parser = api.parser()
    parser.add_argument("page_size", required=False, type=str, help="Job Listing Pagination Size")
    parser.add_argument("offset", required=False, type=str, help="Job Listing Pagination Offset")
    parser.add_argument("job_type", type=str, help="Job type + version, e.g. topsapp:v1.0", required=False)
    parser.add_argument("tag", type=str, help="User-defined job tag", required=False)
    parser.add_argument("queue", type=str, help="Submitted job queue", required=False)
    parser.add_argument("priority", type=int, help="Job priority, 0-9", required=False)
    parser.add_argument("start_time", type=str, help="Start time of @timestamp field", required=False)
    parser.add_argument("end_time", type=str, help="Start time of @timestamp field", required=False)
    parser.add_argument("get_job_details", type=bool, help="Return full details if True. "
                                                           "List of job id's if false. Default True.", required=False)
    parser.add_argument("status", type=str, help="Job status, e.g. job-started, job-completed, job-failed, etc.",
                        required=False)
    parser.add_argument("username", required=False, type=str, help="Username of job submitter")

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self):
        """
        Returns a list of jobs for a given user

        :param get_job_details: Boolean that returns job details if set to True or just job ID's if set to False. Default is True.
        :param page_size: Page size for pagination
        :param offset: Offset for pagination
        :param status: Job status
        :param end_time: End time
        :param start_time: Start time
        :param min_duration: Minimum duration in seconds
        :param max_duration: Maximum duration in seconds
        :param priority: Job priority
        :param queue: Queue
        :param tag: User tag
        :param process_id: Process ID
        :param username: Username
        :param limit: Limit of jobs to send back
        :return: List of jobs for a given user that matches query params provided
        """

        user = get_authorized_user()
        params = dict(request.args)
        response_body = dict()
        # change process id to job_type and send that so HySDS understands 
        if request.args.get("process_id"):
            existing_process = db.session \
                .query(Process_db) \
                .filter_by(process_id=request.args.get("process_id"), status=DEPLOYED_PROCESS_STATUS) \
                .first()
            if existing_process is not None:
                params["job_type"]="job-"+existing_process.process_name_hysds
            else:
                response_body["jobs"] = []
                return response_body, status.HTTP_200_OK
            
        # If status is provided, make sure it is HySDS-compliant
        if params.get("status") is not None:
            params["status"] = ogc.get_hysds_status_from_ogc(params["status"])
        response_body, status = hysds.get_mozart_jobs_from_query_params(params, user)
        
        jobs_list = response_body["jobs"]
        # Filter based on start and end times if min/ max duration was passed as a parameter 
        if (request.args.get("min_duration") or request.args.get("max_duration")):
            jobs_in_duration_range = []
            try:
                min_duration = float(request.args.get("min_duration")) if request.args.get("min_duration") else None
                max_duration = float(request.args.get("max_duration")) if request.args.get("max_duration") else None  
            except:
                response_body["status"] = status.HTTP_500_INTERNAL_SERVER_ERROR
                response_body["detail"] = "Min/ max duration must be able to be converted to integers or floats"
                return response_body, status.HTTP_500_INTERNAL_SERVER_ERROR

            for job in jobs_list:
                try:
                    time_start = job[next(iter(job))]["job"]["job_info"]["time_start"]
                    time_end = job[next(iter(job))]["job"]["job_info"]["time_end"]
                    if time_start and time_end:
                        fmt = "%Y-%m-%dT%H:%M:%S.%f"
                        # Remove the Z and format 
                        start_dt = datetime.strptime(time_start[:-1], fmt)
                        end_dt = datetime.strptime(time_end[:-1], fmt)

                        duration = (end_dt - start_dt).total_seconds()
                        
                        if ((min_duration is None or duration >= min_duration) and
                            (max_duration is None or duration <= max_duration)):
                            jobs_in_duration_range.append(job)
                except Exception as ex:
                    print(ex)
                    print("Unable to determine if job falls in min/max duration range because not in correct format")
            response_body["jobs"] = jobs_in_duration_range
                
        
        # Apply the limit if it was passed as a param
        if response_body["jobs"] and request.args.get("limit"):
            limit = request.args.get("limit")
            if limit.isdigit():
                limit = int(limit)
                response_body["jobs"] = response_body["jobs"][:limit]

        links = []
        jobs_with_required_fields = []
        # Need to get the CWLs to return as links with the jobs 
        for job in response_body["jobs"]:
            try:
                job_with_required_fields = job
                job_with_required_fields["id"] = next(iter(job))
                # TODO graceal should this be hard coded in if the example options are process, wps, openeo?
                job_with_required_fields["type"] = "process"
                hysds_status = job[next(iter(job))]["status"]
                ogc_status = ogc.hysds_to_ogc_status(hysds_status)
                job_with_required_fields["status"] = ogc_status
                links.append({
                        "href": "/"+ns.name+"/job/"+job_with_required_fields["id"],
                        "rel": "self",
                        "type": "application/json",
                        "hreflang": HREF_LANG,
                        "title": "Job"
                    })
                jobs_with_required_fields.append(job_with_required_fields)
            except: 
                print("Error getting job type to get CWLs")
        response_body["links"] = links
        response_body["jobs"] = jobs_with_required_fields
        return response_body, status
    
@ns.route("/jobs/<string:job_id>/metrics")
class Metrics(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, job_id):
        response_body = dict()
        docker_metrics = None

        existing_job = db.session \
            .query(ProcessJob_db) \
            .filter_by(id=job_id) \
            .first()
        if existing_job is None:
            return _generate_error("No job with that job ID found", status.HTTP_404_NOT_FOUND, "ogcapi-processes-1/1.0/no-such-job")

        try:
            logging.info("Finding result of job with id {}".format(job_id))
            logging.info("Retrieved Mozart job id: {}".format(job_id))
            try:
                mozart_response = hysds.get_mozart_job(job_id)
            except Exception as ex:
                return _generate_error("Failed to get job information found for {}. Reason: {}".format(job_id, ex), status.HTTP_500_INTERNAL_SERVER_ERROR)

            # get all the relevant metrics information
            job_info = mozart_response.get("job").get("job_info")
            dir_size = job_info.get("metrics").get("job_dir_size")
            job_facts = job_info.get("facts")
            architecture = job_facts.get("architecture")
            os = job_facts.get("operatingsystem")
            memorysize = job_facts.get("memorysize")
            instance_typ = job_facts.get("ec2_instance_type")
            time_start = job_info.get("cmd_start")
            time_end = job_info.get("cmd_end")
            time_duration = job_info.get("cmd_duration")

            if job_info.get("metrics").get("usage_stats"):
                docker_metrics = job_info.get("metrics").get("usage_stats")[0].get("cgroups")
                if docker_metrics is not None:
                    cpu_stats = docker_metrics.get("cpu_stats").get("cpu_usage").get("total_usage")
                    memory_stats = docker_metrics.get("memory_stats")
                    cache_stat = memory_stats.get("cache")
                    mem_usage = memory_stats.get("usage").get("usage")
                    max_mem_usage = memory_stats.get("usage").get("max_usage")
                    swap_usage = memory_stats.get("stats").get("swap")

                    # total bytes transferred during all the I/O operations performed by the container
                    io_stats = docker_metrics.get("blkio_stats").get("io_service_bytes_recursive")
                    for io in io_stats:
                        op = io.get("op")
                        if op == "Read":
                            read_io_stats = io.get("value", 0)
                        elif op == "Write":
                            write_io_stats = io.get("value", 0)
                        elif op == "Sync":
                            sync_io_stats = io.get("value", 0)
                        elif op == "Async":
                            async_io_stats = io.get("value", 0)
                        elif op == "Total":
                            total_io_stats = io.get("value", 0)

            # Create the JSON
            response_body["machine_type"] = instance_typ
            response_body["architecture"] = architecture
            response_body["machine_memory_size"] = memorysize
            response_body["directory_size"] = dir_size
            response_body["operating_system"] = os
            response_body["job_start_time"] = time_start
            response_body["job_end_time"] = time_end
            response_body["job_duration_seconds"] = time_duration

            if docker_metrics:
                response_body["cpu_usage"] = cpu_stats
                response_body["cache_usage"] = cache_stat
                response_body["mem_usage"] = mem_usage
                response_body["max_mem_usage"] = max_mem_usage
                response_body["swap_usage"] = swap_usage
                response_body["read_io_stats"] = read_io_stats
                response_body["write_io_stats"] = write_io_stats
                response_body["sync_io_stats"] = sync_io_stats
                response_body["async_io_stats"] = async_io_stats
                response_body["total_io_stats"] = total_io_stats

            return response_body, status.HTTP_200_OK
        except Exception as ex:
            print("Metrics Exception: {}".format(ex))
            print(ex)
            return _generate_error("Failed to get job metrics. {}. Please contact administrator of DPS for clarification if needed".format(ex), status.HTTP_500_INTERNAL_SERVER_ERROR)