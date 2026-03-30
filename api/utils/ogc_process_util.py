"""
Utility functions for OGC process creation and deployment.
Shared between OGC and build endpoints to avoid code duplication.
"""

import logging
import os
import re
import urllib.parse
from collections import namedtuple
from datetime import datetime, timezone

import gitlab
import requests
import yaml
from schema_salad.exceptions import ValidationException
from cwltool.load_tool import load_tool
from cwltool.context import LoadingContext
from cwltool.workflow import default_make_tool
from cwl_utils.parser import cwl_v1_2
from flask import current_app
from flask_api import status

import api.settings as settings
from api.maap_database import db
from api.models.process import Process as Process_db
from api.models.deployment import Deployment as Deployment_db
from api.models.member import Member
import base64

log = logging.getLogger(__name__)

# Constants moved from OGC module to avoid circular imports
INITIAL_JOB_STATUS = "accepted"
DEPLOYED_PROCESS_STATUS = "deployed"
UNDEPLOYED_PROCESS_STATUS = "undeployed"
HREF_LANG = "en"
ERROR_TYPE_PREFIX = "http://www.opengis.net/def/exceptions/"


def get_hysds_process_name(id, user_id, version):
    return f"{id}_{user_id}:{version}"

def parse_hysds_name(hysds_name):
    main_part, version = hysds_name.rsplit(':', 1)
    id_part, user_id = main_part.rsplit('_', 1)
    id = id_part.replace('job-', '', 1)
    return id, version, user_id

def get_process_from_hysds_name(hysds_name):
    id, version, user_id = parse_hysds_name(hysds_name)
    user = db.session.query(Member).filter_by(id=user_id).first()
    return db.session.query(Process_db).filter_by(id=id,version=version,deployer=user.username,status=DEPLOYED_PROCESS_STATUS).first()

def get_process_name_from_hysds_name(hysds_name):
    id, version, user_id = parse_hysds_name(hysds_name)
    return f"{id}:{version}"

def generate_error(detail, error_status, error_type=None):
    """Generates a standardized error response body and status code."""
    full_error_type = f"{ERROR_TYPE_PREFIX}{error_type}" if error_type is not None else None
    response_body = {
        "type": full_error_type,
        "title": detail,
        "status": error_status,
        "detail": detail,
        "instance": ""
    }
    return response_body, error_status


def trigger_gitlab_pipeline(cwl_raw_text, metadata_id, uuid):
    """Triggers the CI/CD pipeline in GitLab to deploy a process."""
    try:
        # random process name to allow algorithms later having the same id/version if the deployer is different 
        process_name_hysds = f"{metadata_id}_{uuid}"
        gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
        pipeline_value = base64.b64encode(cwl_raw_text.encode()).decode()
        pipeline = project.pipelines.create({
            "ref": settings.GITLAB_POST_PROCESS_PIPELINE_REF,
            "variables": [{"key": "PROCESS", "value": pipeline_value}, {"key": "PROCESS_NAME_HYSDS", "value": process_name_hysds}]
        })
        log.info(f"Triggered pipeline ID: {pipeline.id}")
        return pipeline
    except Exception as e:
        log.error(f"GitLab pipeline trigger failed: {e}")
        raise RuntimeError("Failed to start CI/CD to deploy process. The deployment venue is likely down.")

def create_and_commit_deployment(metadata, pipeline, user, existing_process=None):
    """Creates a new deployment record in the database."""
    deployment = Deployment_db(
        created=datetime.now(),
        execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE,
        status=INITIAL_JOB_STATUS,
        cwl_link=metadata.cwl_link, 
        title=metadata.title,
        description=metadata.description,
        keywords=metadata.keywords,
        deployer=user.username,
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

# Define CWL_METADATA namedtuple here to avoid circular imports
CWL_METADATA = namedtuple("CWL_METADATA", [
    "id", "version", "title", "description", "keywords", "raw_text",
    "github_url", "git_commit_hash", "cwl_link", "ram_min", "cores_min",
    "base_command", "author"
])

def get_cwl_from_link(cwl_link):
    """
    Fetch the CWL contents from the CWL link
    """
    try:
        response = requests.get(cwl_link)
        response.raise_for_status()
        cwl_text = response.text

    except requests.exceptions.RequestException:
        raise ValueError("Unable to access CWL from the provided href.")
    
    return cwl_text

def get_cwl_metadata(cwl_text, cwl_link=None):
    """
    Fetches, parses, and extracts metadata from a CWL file. This approach avoids making
    two separate web requests for the same file.

    Args:
        cwl_text (str): Raw text of CWL file
        cwl_link (str, optional): URL to the CWL file

    Returns:
        CWL_METADATA: Named tuple containing extracted metadata

    Raises:
        ValueError: If CWL file is invalid or inaccessible
    """
    # Initialize default values
    ram_min = None
    cores_min = None
    base_command = None

    try:
        # Parse YAML - use a custom loader to prevent date string conversion
        class NoDatesSafeLoader(yaml.SafeLoader):
            pass

        # Remove timestamp resolver to keep dates as strings
        NoDatesSafeLoader.yaml_implicit_resolvers = {
            k: [r for r in v if r[0] != 'tag:yaml.org,2002:timestamp']
            for k, v in NoDatesSafeLoader.yaml_implicit_resolvers.items()
        }

        cwl_dict = yaml.load(cwl_text, Loader=NoDatesSafeLoader)

        # Find the Workflow document in the CWL
        # CWL files can have a $graph with multiple documents, or be a single document
        workflow_dict = None

        if '$graph' in cwl_dict:
            # Multiple documents - find the Workflow
            for doc in cwl_dict['$graph']:
                if doc.get('class') == 'Workflow':
                    workflow_dict = doc
                    break
            if not workflow_dict:
                raise ValueError("A valid Workflow object must be defined in the CWL file.")
        elif cwl_dict.get('class') == 'Workflow':
            # Single document that is a Workflow
            workflow_dict = cwl_dict
        else:
            raise ValueError("A valid Workflow object must be defined in the CWL file.")

        # Set up LoadingContext to avoid fetching external files
        loading_context = LoadingContext()
        loading_context.do_update = False  # Don't update schemas
        loading_context.disable_js_validation = False  # Keep JS validation
        loading_context.construct_tool_object = default_make_tool  # Use default tool factory

        # Validate the entire CWL document with load_tool
        # This validates the structure but we'll extract metadata from our parsed dict
        try:
            load_tool(cwl_dict, loading_context)
        except ValidationException as val_err:
            log.error(f"CWL validation failed: {val_err}")
            raise ValueError(f"CWL validation failed: {str(val_err)}")

        # Extract workflow metadata from the workflow_dict we found
        cwl_id = workflow_dict.get('id', '')
        title = workflow_dict.get('label', '')
        description = workflow_dict.get('doc', '')

        # Extract version from text (schema.org annotation)
        version_match = re.search(r"s:version:[ \t]*(\S+)", cwl_text, re.IGNORECASE)

        if not version_match or not cwl_id:
            raise ValueError("Required metadata missing: s:version and a top-level id are required.")

        fragment = urllib.parse.urlparse(cwl_id).fragment
        cwl_id = os.path.basename(fragment) if fragment else os.path.basename(cwl_id)
        process_version = version_match.group(1).strip().strip("'\"")

        if not process_version:
            raise ValueError("Required metadata missing: s:version must have a non-empty value.")

        if ":" in process_version:
            raise ValueError("Process version cannot contain a :")

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
        workflow_steps = workflow_dict.get('steps', [])
        if workflow_steps:
            # Get the first step - could be a list or dict
            if isinstance(workflow_steps, list):
                first_step = workflow_steps[0]
            else:
                first_step = list(workflow_steps.values())[0]

            # Get the tool reference from the step
            tool_ref = first_step.get('run', {})

            # If tool_ref is a dict, it's an embedded CommandLineTool
            if isinstance(tool_ref, dict):
                command_line_tool = tool_ref
            else:
                # It's a reference - we need to resolve it from the $graph or loaded tools
                # For now, we'll search in the original dict for the tool
                tool_id = os.path.basename(tool_ref.split('#')[-1]) if isinstance(tool_ref, str) else None
                command_line_tool = None

                # Check if there's a $graph with multiple documents
                if '$graph' in cwl_dict:
                    for doc in cwl_dict['$graph']:
                        if doc.get('class') == 'CommandLineTool':
                            doc_id = doc.get('id', '')
                            if tool_id and (doc_id.endswith(tool_id) or doc_id.endswith('#' + tool_id)):
                                command_line_tool = doc
                                break

            if command_line_tool:
                # Extract baseCommand
                base_command = command_line_tool.get('baseCommand')

                # Find ResourceRequirement
                requirements = command_line_tool.get('requirements', [])
                resource_reqs = requirements.get('ResourceRequirement')
                if resource_reqs:
                    ram_min = resource_reqs.get('ramMin')
                    cores_min = resource_reqs.get('coresMin')

    except yaml.YAMLError as e:
        log.error(f"Failed to parse CWL YAML: {e}")
        raise ValueError(f"CWL file is not valid YAML: {str(e)}")
    except ValidationException as e:
        log.error(f"CWL validation failed: {e}")
        raise ValueError(f"CWL validation failed: {str(e)}")
    except Exception as e:
        log.error(f"Failed to parse or validate CWL: {e}")
        raise ValueError(f"CWL file is not in the right format or is invalid: {str(e)}")

    return CWL_METADATA(
        id=cwl_id,
        version=process_version,
        title=title,
        description=description,
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

def create_process_deployment(cwl_link, user_id, cwl_text = None, ignore_existing=False):
    """
    Create a new OGC process deployment using the provided CWL link and user.
    
    This is a shared utility function that can be used by both the OGC POST endpoint
    and the build webhook to create process deployments without code duplication.
    
    Args:
        cwl_link (str): URL to the CWL file
        user_id (int): ID of the user creating the process
        ignore_existing: If true, checks for duplicate process before creating a new one
        
    Returns:
        tuple: (response_body dict, status_code int)
        
    Raises:
        ValueError: If validation fails
        RuntimeError: If deployment process fails
    """
    current_app.logger.debug(f"Creating OGC process deployment for CWL: {cwl_link}")

    # Get the user
    user = db.session.query(Member).filter_by(id=user_id).first()
    if not user:
        raise ValueError(f"User with ID {user_id} not found")
    current_app.logger.debug(user)
    current_app.logger.debug(f"User ID: {user.id}")

    if cwl_link:
        cwl_text = get_cwl_from_link(cwl_link)
    metadata = get_cwl_metadata(cwl_text, cwl_link)
    
    try:
        # Check for existing process
        existing_process = db.session.query(Process_db).filter_by(
            id=metadata.id, version=metadata.version, status=DEPLOYED_PROCESS_STATUS
        ).first()
        
        if not ignore_existing and existing_process and existing_process.deployer == user.username:
            current_app.logger.debug(f"Duplicate process found for user {user.id}")
            response_body, code = generate_error(
                "Duplicate process. Use PUT to modify existing process if you originally published it.", 
                status.HTTP_409_CONFLICT, 
                "ogcapi-processes-2/1.0/duplicated-process"
            )
            response_body["additionalProperties"] = {"processID": existing_process.process_id}
            return response_body, code
        
        # Trigger GitLab pipeline for deployment
        current_app.logger.debug(f"Triggering GitLab pipeline for deployment")
        pipeline = trigger_gitlab_pipeline(cwl_text, metadata.id, user.id)
        current_app.logger.debug(f"Pipeline created with ID: {pipeline.id}")
        
        # Create deployment record
        current_app.logger.debug(f"Creating deployment record")
        deployment = create_and_commit_deployment(metadata, pipeline, user)
        
        # Re-query to get the auto-incremented job_id
        deployment = db.session.query(Deployment_db).filter_by(
            id=metadata.id, version=metadata.version, status=INITIAL_JOB_STATUS
        ).first()
        deployment_job_id = deployment.job_id
        
        current_app.logger.info(f"Successfully created OGC process deployment: {deployment_job_id}")
        
        # Build response compatible with both OGC and build endpoints
        response_body = {
            "title": metadata.title,
            "description": metadata.description,
            "keywords": metadata.keywords.split(",") if metadata.keywords else [],
            "metadata": [],
            "id": metadata.id,
            "version": metadata.version,
            "jobControlOptions": [],
            "deploymentJobID": deployment_job_id,
            "status": deployment.status,
            "created": deployment.created if hasattr(deployment, 'created') else datetime.utcnow().isoformat(),
            "links": [{
                "href": f"/ogc/deploymentJobs/{deployment_job_id}",
                "rel": "monitor",
                "type": "application/json",
                "hreflang": "en",
                "title": "Deploying process status link"
            }],
            "processPipelineLink": {
                "href": pipeline.web_url,
                "rel": "monitor",
                "type": "text/html",
                "hreflang": "en",
                "title": "Link to process pipeline"
            }
        }
        
        return response_body, status.HTTP_202_ACCEPTED
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error in OGC process deployment: {e}")
        raise RuntimeError(f"Failed to create OGC process deployment: {e}")
    
def parse_rfc3339_datetime(dt_string):
    """Parse RFC 3339 datetime string to datetime object"""
    # Handle Z timezone indicator
    if dt_string.endswith('Z'):
        dt_string = dt_string[:-1] + '+00:00'
    
    # Try different datetime formats
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",  # With microseconds and timezone
        "%Y-%m-%dT%H:%M:%S%z",     # Without microseconds but with timezone
        "%Y-%m-%dT%H:%M:%S.%f",    # With microseconds, no timezone
        "%Y-%m-%dT%H:%M:%S",       # Basic format, no timezone
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(dt_string, fmt)
            # If no timezone info, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    
    raise ValueError(f"Unable to parse datetime: {dt_string}")

def job_intersects_datetime_range(job_start, job_end, filter_start, filter_end):
    """
    Check if a job's time range intersects with the filter datetime range.
    Returns True if there's an intersection, False otherwise.
    """
    try:
        # Handle intersection logic
        # Two ranges intersect if: start1 <= end2 and start2 <= end1
        
        # Handle half-bounded intervals
        if filter_start is None:  # "../end_time" case
            return job_start <= filter_end
        elif filter_end is None:  # "start_time/.." case  
            return filter_start <= job_end
        elif filter_start == filter_end:  # Single datetime case
            return job_start <= filter_start <= job_end
        else:  # Bounded interval case
            return filter_start <= job_end and job_start <= filter_end
            
    except Exception as e:
        print(f"Error checking job intersection: {e}")
        return False
    
def parse_datetime_parameter(datetime):
    """
    Parse the datetime parameter and return (start_time, end_time) tuple.
    Returns (None, None) if parameter is invalid.
    """
    
    try:
        # Check if it's an interval (contains '/')
        if '/' in datetime:
            start_str, end_str = datetime.split('/', 1)
            
            # Handle half-bounded intervals
            if start_str == '..':
                start_time = None
                end_time = parse_rfc3339_datetime(end_str)
            elif end_str == '..':
                start_time = parse_rfc3339_datetime(start_str)
                end_time = None
            else:
                # Bounded interval
                start_time = parse_rfc3339_datetime(start_str)
                end_time = parse_rfc3339_datetime(end_str)
            
            return start_time, end_time
        
        else:
            # Single date-time - treat as exact match or you might want to define a small window
            single_time = parse_rfc3339_datetime(datetime)
            return single_time, single_time
    
    except Exception as e:
        print(f"Error parsing datetime parameter: {e}")
        return None, None

def determineDatetimeInRange(datetime, job_start, job_end):
    filter_start, filter_end = parse_datetime_parameter(datetime)
    if filter_start is None and filter_end is None:
        print("Invalid datetime parameter format")
        return False
    
    return job_intersects_datetime_range(job_start, job_end, filter_start, filter_end)