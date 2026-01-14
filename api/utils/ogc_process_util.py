"""
Utility functions for OGC process creation and deployment.
Shared between OGC and build endpoints to avoid code duplication.
"""

import logging
import os
import re
import tempfile
import urllib.parse
from collections import namedtuple
from datetime import datetime, timezone

import gitlab
import requests
from cwl_utils.parser import load_document_by_uri, cwl_v1_2
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

def get_process_from_hysds_name(hysds_name):
    main_part, version = hysds_name.rsplit(':', 1)
    id_part, user_id = main_part.rsplit('_', 1)
    id = id_part.replace('job-', '', 1)
    user = db.session.query(Member).filter_by(id=user_id).first()
    return db.session.query(Process_db).filter_by(id=id,version=version,deployer=user.username,status=DEPLOYED_PROCESS_STATUS).first()

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


def trigger_gitlab_pipeline(cwl_link, version, metadata_id, uuid):
    """Triggers the CI/CD pipeline in GitLab to deploy a process."""
    try:
        # random process name to allow algorithms later having the same id/version if the deployer is different 
        process_name_hysds = f"{metadata_id}_{uuid}"
        gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)
        pipeline = project.pipelines.create({
            "ref": settings.GITLAB_POST_PROCESS_PIPELINE_REF,
            "variables": [{"key": "CWL_URL", "value": cwl_link}, {"key": "PROCESS_NAME_HYSDS", "value": process_name_hysds}]
        })
        log.info(f"Triggered pipeline ID: {pipeline.id}")
        return pipeline
    except Exception as e:
        log.error(f"GitLab pipeline trigger failed: {e}")
        raise RuntimeError("Failed to start CI/CD to deploy process. The deployment venue is likely down.")

def trigger_gitlab_pipeline_with_cwl_text(cwl_raw_text, metadata_id, uuid):
    """Triggers the CI/CD pipeline in GitLab to deploy a process."""
    try:
        # random process name to allow algorithms later having the same id/version if the deployer is different
        process_name_hysds = f"{metadata_id}_{uuid}"
        gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_TOKEN)
        project = gl.projects.get(settings.GITLAB_PROJECT_ID_POST_PROCESS)

        pipeline = project.pipelines.create({
            "ref": settings.GITLAB_POST_PROCESS_PIPELINE_REF,
            "variables": [{"key": "PROCESS", "value": base64.b64encode(cwl_raw_text.encode()).decode()}, {"key": "PROCESS_NAME_HYSDS", "value": process_name_hysds}]
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

def get_cwl_metadata(cwl_link, cwl_text = None):
    """
    Fetches, parses, and extracts metadata from a CWL file. This approach avoids making 
    two separate web requests for the same file.
    
    Args:
        cwl_link (str): URL to the CWL file
        cwl_raw_text (str): Raw text of CWL file 
        
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
        # 1. Fetch the CWL content once using requests.
        # 2. Save the content to a temporary file.
        # 3. Use the local file URI with cwl_utils to parse the object model.
        # 4. Use the in-memory text for regex-based metadata extraction.
        # This is wrapped in a try/finally block to ensure the temp file is cleaned up.
        if cwl_link:
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
    if workflow.steps:
        # Get the ID of the tool to run (e.g., '#main')
        tool_id_ref = workflow.steps[0].run
        # The actual ID is the part after the '#'
        tool_id = os.path.basename(tool_id_ref)

        # Find the CommandLineTool object in the parsed CWL graph
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
                        break  # Stop after finding the first ResourceRequirement

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

def create_process_deployment(cwl_link, metadata, user, cwl_text = None, ignore_existing=False):
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
    current_app.logger.debug(user)
    current_app.logger.debug(f"User ID: {user.id}")
    
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
        if cwl_link:
            pipeline = trigger_gitlab_pipeline(cwl_link, metadata.version, metadata.id, user.id)
        else:
            pipeline = trigger_gitlab_pipeline_with_cwl_text(cwl_text, metadata.id, user.id)
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