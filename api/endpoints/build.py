import json
import logging
import uuid
import traceback
import base64
import re
import datetime

import gitlab
from flask import request, current_app
from flask_restx import Resource
from flask_api import status

from api.restplus import api
from api.auth.security import get_authorized_user, login_required, authenticate_third_party
from api.maap_database import db
from api.models.build import Build
from api.models.role import Role
import api.settings as settings

log = logging.getLogger(__name__)

ns = api.namespace("build", description="Build operations")

# Constants following OGC pattern
BUILD_FINISHED_STATUSES = ["successful", "failed", "dismissed", "canceled"]
BUILD_SUCCESS = "successful"
INITIAL_BUILD_STATUS = "accepted"
HREF_LANG = "en"
ERROR_TYPE_PREFIX = "http://www.opengis.net/def/exceptions/"


def _validate_algorithm_name(algorithm_name):
    """
    Validates algorithm name format.
    - Can contain lowercase letters, digits, hyphens (-), and underscores (_)
    - Must be between 2 and 255 characters long
    """
    current_app.logger.debug(f"Validating algorithm name: {algorithm_name}")
    
    if not algorithm_name:
        current_app.logger.debug("Validation failed: algorithm_name is empty or None")
        raise ValueError("algorithm_name is required")
    
    if len(algorithm_name) < 2 or len(algorithm_name) > 255:
        current_app.logger.debug(f"Validation failed: algorithm_name length {len(algorithm_name)} is outside allowed range (2-255)")
        raise ValueError("algorithm_name must be between 2 and 255 characters long")
    
    # Check if contains only allowed characters (lowercase letters, digits, hyphens, underscores)
    if not re.match(r'^[a-z0-9_-]+$', algorithm_name):
        current_app.logger.debug(f"Validation failed: algorithm_name contains invalid characters")
        raise ValueError("algorithm_name can only contain lowercase letters, digits, hyphens (-), and underscores (_)")
    
    current_app.logger.debug(f"Algorithm name validation successful: {algorithm_name}")
    return algorithm_name


def _validate_algorithm_version(algorithm_version):
    """
    Validates algorithm version format.
    - Must be valid ASCII characters
    - Can contain lowercase and uppercase letters, digits, underscores (_), periods (.), and dashes (-)
    - Can be up to 128 characters long
    - Must conform to the regex pattern: [a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}
    """
    current_app.logger.debug(f"Validating algorithm version: {algorithm_version}")
    
    if not algorithm_version:
        current_app.logger.debug("Validation failed: algorithm_version is empty or None")
        raise ValueError("algorithm_version is required")
    
    if len(algorithm_version) > 128:
        current_app.logger.debug(f"Validation failed: algorithm_version length {len(algorithm_version)} exceeds 128 character limit")
        raise ValueError("algorithm_version can be up to 128 characters long")
    
    # Check if contains only ASCII characters
    try:
        algorithm_version.encode('ascii')
        current_app.logger.debug("Algorithm version ASCII validation passed")
    except UnicodeEncodeError:
        current_app.logger.debug("Validation failed: algorithm_version contains non-ASCII characters")
        raise ValueError("algorithm_version must contain only valid ASCII characters")
    
    # Check if matches the required pattern: starts with letter/digit/underscore, 
    # followed by letters/digits/underscores/periods/dashes
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$', algorithm_version):
        current_app.logger.debug(f"Validation failed: algorithm_version does not match required pattern")
        raise ValueError("algorithm_version must start with a letter, digit, or underscore and can only contain letters, digits, underscores (_), periods (.), and dashes (-)")
    
    current_app.logger.debug(f"Algorithm version validation successful: {algorithm_version}")
    return algorithm_version


def _generate_error(detail, error_status, error_type=None):
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


def _validate_build_payload(payload):
    current_app.logger.debug(f"Validating build payload with keys: {list(payload.keys()) if payload else 'None'}")
    
    # Required variables
    if payload.get("code_repository") is None:
        current_app.logger.debug("Validation failed: code_repository is missing from payload")
        raise ValueError("code_repository is required")
    
    current_app.logger.debug(f"Code repository: {payload.get('code_repository')}")
    
    # Image name - derive from algorithm_name if not provided
    algorithm_name = payload.get("algorithm_name")
    current_app.logger.debug(f"Algorithm name from payload: {algorithm_name}")
    # Validate algorithm name format
    _validate_algorithm_name(algorithm_name)
    
    # Image tag - derive from algorithm_version if not provided
    algorithm_version = payload.get("algorithm_version")
    current_app.logger.debug(f"Algorithm version from payload: {algorithm_version}")
    # Validate algorithm version format
    _validate_algorithm_version(algorithm_version)
    
    current_app.logger.debug("Build payload validation completed successfully")


def _trigger_build_pipeline(payload, namespace):
    """Triggers a GitLab pipeline for the build request."""
    current_app.logger.debug(f"Triggering build pipeline for namespace: {namespace}")
    current_app.logger.debug(f"GitLab URL: {settings.GITLAB_URL}")
    current_app.logger.debug(f"Project ID: {settings.GITLAB_BUILD_APP_PACK_PROJECT_ID}")
    current_app.logger.debug(f"Pipeline ref: {settings.GITLAB_BUILD_APP_PACK_PIPELINE_REF}")
    
    try:
        current_app.logger.debug("Initializing GitLab client")
        gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_TOKEN)
        
        current_app.logger.debug("Retrieving GitLab project")
        project = gl.projects.get(settings.GITLAB_BUILD_APP_PACK_PROJECT_ID)
        current_app.logger.debug(f"Project retrieved: {project.name}")
        
        # Extract and validate required variables from payload
        variables = []
        current_app.logger.debug("Processing pipeline variables")
        
        # Required variables
        repository_url = payload.get("code_repository")
        current_app.logger.debug(f"Repository URL: {repository_url}")
        variables.append({"key": "REPOSITORY_URL", "value": repository_url})
        
        # Build command
        build_cmd = payload.get("build_command")
        if build_cmd:
            current_app.logger.debug(f"Build command provided: {build_cmd}")
            variables.append({"key": "BUILD_CMD", "value": build_cmd})
        else:
            current_app.logger.debug("No build command provided")
        
        # Base image with fallback
        base_image = payload.get("base_image")
        if base_image:
            current_app.logger.debug(f"Base image: {base_image}")
            variables.append({"key": "BASE_IMAGE_NAME", "value": base_image})
        else:
            current_app.logger.debug("No base image specified, using pipeline default")
        
        algorithm_name = payload.get("algorithm_name")
        image_name = f"{namespace}/{algorithm_name}"
        current_app.logger.debug(f"Generated image name: {image_name}")
        variables.append({"key": "IMAGE_NAME", "value": image_name})
        
        algorithm_version = payload.get("algorithm_version")
        current_app.logger.debug(f"Algorithm version: {algorithm_version}")
        variables.append({"key": "IMAGE_TAG", "value": algorithm_version})
        variables.append({"key": "BRANCH_REF", "value": algorithm_version})
        
        # Base64 encode the algorithm configuration
        current_app.logger.debug("Encoding algorithm configuration to base64")
        algo_config_json = json.dumps(payload)
        current_app.logger.debug(f"Algorithm config JSON length: {len(algo_config_json)} characters")
        algo_config_b64 = base64.b64encode(algo_config_json.encode()).decode()
        current_app.logger.debug(f"Base64 encoded config length: {len(algo_config_b64)} characters")
        variables.append({"key": "ALGO_CONFIG_JSON_B64", "value": algo_config_b64})
        
        current_app.logger.info(f"GitLab CI variables: {[{k['key']: k['value'][:50] + '...' if len(k['value']) > 50 else k['value'] for k in variables}]}")
        
        pipeline = project.pipelines.create({
            "ref": settings.GITLAB_BUILD_APP_PACK_PIPELINE_REF,
            "variables": variables
        })
        
        current_app.logger.info(f"Successfully triggered GitLab pipeline ID: {pipeline.id}")
        current_app.logger.debug(f"Pipeline web URL: {pipeline.web_url}")
        current_app.logger.debug(f"Pipeline status: {pipeline.status}")
        current_app.logger.debug(f"Pipeline ref: {pipeline.ref}")
        
        return pipeline
        
    except gitlab.exceptions.GitlabAuthenticationError as e:
        current_app.logger.error(f"GitLab authentication failed: {e}")
        raise RuntimeError("Failed to authenticate with build service.")
    except gitlab.exceptions.GitlabGetError as e:
        current_app.logger.error(f"GitLab project retrieval failed: {e}")
        raise RuntimeError("Failed to access build project. The build service may be misconfigured.")
    except gitlab.exceptions.GitlabCreateError as e:
        current_app.logger.error(f"GitLab pipeline creation failed: {e}")
        raise RuntimeError("Failed to create build pipeline. Please check your build configuration.")
    except Exception as e:
        current_app.logger.error(f"Unexpected error in GitLab pipeline trigger: {type(e).__name__}: {e}")
        current_app.logger.debug(f"Full exception traceback: {traceback.format_exc()}")
        raise RuntimeError("Failed to start build pipeline. The build service may be down.")


def _create_and_commit_build(build_id, pipeline, repository_url, branch_ref, user):
    """Creates a new build record in the database."""
    current_app.logger.debug(f"Creating build record with ID: {build_id}")
    current_app.logger.debug(f"User ID: {user.id}, Username: {user.username}")
    current_app.logger.debug(f"Repository URL: {repository_url}")
    current_app.logger.debug(f"Branch ref: {branch_ref}")
    current_app.logger.debug(f"Pipeline ID: {pipeline.id if pipeline else None}")
    current_app.logger.debug(f"Pipeline URL: {pipeline.web_url if pipeline else None}")
    current_app.logger.debug(f"Initial status: {INITIAL_BUILD_STATUS}")
    
    build = Build(
        build_id=build_id,
        status=INITIAL_BUILD_STATUS,
        requester=user.id,
        repository_url=repository_url, 
        branch_ref=branch_ref,
        pipeline_id=pipeline.id if pipeline else None,
        pipeline_url=pipeline.web_url if pipeline else None
    )
    
    current_app.logger.debug("Adding build to database session")
    db.session.add(build)
    
    try:
        current_app.logger.debug("Committing build record to database")
        db.session.commit()
        current_app.logger.info(f"Successfully created build record {build_id} for user {user.username}")
    except Exception as e:
        current_app.logger.error(f"Failed to commit build record to database: {e}")
        db.session.rollback()
        raise
        
    return build


def _update_build_status(build, req_data=None, query_pipeline=False):
    """Updates the status of the build if applicable"""
    current_app.logger.debug(f"Updating build status for build_id: {build.build_id if build else 'None'}")
    current_app.logger.debug(f"Query pipeline flag: {query_pipeline}")
    current_app.logger.debug(f"Request data provided: {req_data is not None}")
    
    status_code = status.HTTP_200_OK

    if build is None:
        current_app.logger.debug("Build not found - returning 404")
        return _generate_error("No build with that build ID found", status.HTTP_404_NOT_FOUND)

    current_status = build.status
    pipeline_url = build.pipeline_url
    
    current_app.logger.debug(f"Current build status: {current_status}")
    current_app.logger.debug(f"Current pipeline URL: {pipeline_url}")

    response_body = {
        "build_id": build.build_id,
        "links": {
            "href": f"/{ns.name}/{build.build_id}",
            "rel": "self",
            "type": "application/json",
            "hreflang": HREF_LANG,
            "title": "Build Status"
        }
    }
    
    # Only query pipeline if status is not finished
    if build.status not in BUILD_FINISHED_STATUSES:
        current_app.logger.debug(f"Build status {build.status} is not finished, checking for updates")
        
        if query_pipeline:
            current_app.logger.debug(f"Querying GitLab pipeline {build.pipeline_id} directly")
            try:
                gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_TOKEN)
                project = gl.projects.get(settings.GITLAB_BUILD_APP_PACK_PROJECT_ID)
                pipeline = project.pipelines.get(build.pipeline_id)
                updated_status = pipeline.status
                pipeline_url = pipeline.web_url
                current_app.logger.debug(f"Retrieved pipeline status from GitLab: {updated_status}")
            except Exception as e:
                current_app.logger.error(f"Failed to query GitLab pipeline {build.pipeline_id}: {e}")
                current_app.logger.debug(f"Pipeline query error traceback: {traceback.format_exc()}")
                updated_status = build.status  # Fallback to current status on error
                current_app.logger.debug("Falling back to current build status due to GitLab query error")
        else:
            current_app.logger.debug("Extracting status from webhook payload")
            try:
                updated_status = req_data["object_attributes"]["status"]
                current_app.logger.debug(f"Extracted status from webhook: {updated_status}")
            except (TypeError, KeyError) as e:
                current_app.logger.debug(f"Failed to extract status from payload: {e}")
                current_app.logger.debug(f"Payload structure: {req_data}")
                return _generate_error('Payload from 3rd party should have status at ["object_attributes"]["status"]', status.HTTP_400_BAD_REQUEST)
        
        # Map GitLab status to our status
        status_mapping = {
            "success": "successful",
            "failed": "failed",
            "canceled": "canceled",
            "skipped": "dismissed"
        }
        
        mapped_status = status_mapping.get(updated_status, updated_status)
        current_app.logger.debug(f"Status mapping: {updated_status} -> {mapped_status}")
        current_status = mapped_status

        if current_status != build.status:
            log.debug(f"Build changed status to {current_status} from {build.status}")
            old_status = build.status
            build.status = current_status
            build.updated = datetime.now(datetime.timezone.utc)
            
            try:
                log.debug(f"Updating build status in database from {old_status} to {current_status}")
                db.session.commit()
                log.info(f"Build {build.build_id} status updated from {old_status} to {current_status}")
                response_body.update({"updated": build.updated.isoformat()})
            except Exception as e:
                log.error(f"Failed to update build status in database: {e}")
                db.session.rollback()
                raise
        else:
            log.debug(f"Build status {current_status} is not final, no database update needed")
    else:
        current_app.logger.debug(f"Build already in finished status: {build.status}")

    response_body.update({"status": current_status})
    if pipeline_url:
        current_app.logger.debug(f"Adding pipeline link to response: {pipeline_url}")
        response_body.update({
                "pipelineLink": {
                    "href": pipeline_url,
                    "rel": "monitor",
                    "type": "text/html",
                    "hreflang": HREF_LANG,
                    "title": "Link to build pipeline"
                }
            })
    
    current_app.logger.debug(f"Returning response with status code: {status_code}")
    return response_body, status_code


@ns.route("")
class BuildList(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self):
        """
        Get all builds for the current user
        """
        current_app.logger.debug("GET /build - Retrieving builds for current user")
        user = get_authorized_user()
        current_app.logger.debug(f"Authorized user: {user.id} ({user.username})")
        
        # Query builds for the current user
        current_app.logger.debug(f"Querying builds for user ID: {user.id}")
        builds = db.session.query(Build).filter_by(requester=user.id).order_by(Build.created.desc()).all()
        
        current_app.logger.debug(f"Found {len(builds)} builds for user")
        
        build_list = []
        for i, build in enumerate(builds):
            current_app.logger.debug(f"Processing build {i+1}/{len(builds)}: {build.build_id}")
            build_info = {
                "build_id": build.build_id,
                "status": build.status,
                "created": build.created.isoformat(),
                "updated": build.updated.isoformat() if build.updated else None,
                "repository_url": build.repository_url,
                "branch_ref": build.branch_ref,
                "links": [
                    {
                        "href": f"/{ns.name}/{build.build_id}",
                        "rel": "self",
                        "type": "application/json",
                        "hreflang": HREF_LANG,
                        "title": "Build status link"
                    }
                ]
            }
            
            # Add pipeline link if available
            if build.pipeline_url:
                current_app.logger.debug(f"Adding pipeline link for build {build.build_id}")
                build_info["pipelineLink"] = {
                    "href": build.pipeline_url,
                    "rel": "monitor", 
                    "type": "text/html",
                    "hreflang": HREF_LANG,
                    "title": "Link to build pipeline"
                }
            else:
                current_app.logger.debug(f"No pipeline URL for build {build.build_id}")
            
            build_list.append(build_info)
        
        current_app.logger.debug(f"Returning {len(build_list)} builds")
        return {"builds": build_list}, status.HTTP_200_OK

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def post(self):
        """
        Create a new build request and trigger pipeline. 
        Example request
        {
            "algorithm_description": "This application is designed to process Synthetic Aperture Radar (SAR) data from Sentinel-1 GRD (Ground Range Detected) products using a Digital Elevation Model (DEM) obtained from Copernicus.",
            "algorithm_name": "sardem-sarsen",
            "algorithm_version": "mlucas/nasa_ogc",
            "keywords": "ogc, sar",
            "code_repository": "https://github.com/MAAP-Project/sardem-sarsen.git",
            "citation": "https://github.com/MAAP-Project/sardem-sarsen.git",
            "author": "arthurduf",
            "contributor": "arthurduf",
            "license": "https://github.com/MAAP-Project/sardem-sarsen/blob/main/LICENSE",
            "release_notes": "None",
            "run_command": "sardem-sarsen/sardem-sarsen.sh",
            "build_command": "sardem-sarsen/build.sh"
            "ram_min": 5,
            "cores_min": 1,
            "outdir_max": 20,
            "inputs": [
                {
                "name": "bbox",
                "doc": "Bounding box as 'LEFT BOTTOM RIGHT TOP'",
                "label": "bounding box",
                "type": "string"
                },
                {
                "name": "stac_catalog_folder",
                "doc": "STAC catalog folder",
                "label": "catalog folder",
                "type": "Directory"
                },
                {
                "name": "stac_asset_name",
                "doc": "STAC asset name",
                "label": "asset name",
                "type": "string?"
                }
            ],
            "outputs": [
                {
                "name": "out",
                "type": "Directory"
                }
            ]
        }
        """
        current_app.logger.debug("POST /build - Creating new build request")
        req_data = request.get_json()
        current_app.logger.debug(f"Request payload keys: {list(req_data.keys()) if req_data else 'None'}")
        
        try:
            current_app.logger.debug("Validating build payload")
            _validate_build_payload(req_data)
            
            user = get_authorized_user()
            current_app.logger.debug(f"Authorized user for build: {user.id} ({user.username})")
            
            build_id = str(uuid.uuid4())
            current_app.logger.debug(f"Generated build ID: {build_id}")
            
            # Trigger GitLab pipeline (validation happens inside)
            current_app.logger.debug("Triggering GitLab pipeline")
            pipeline = _trigger_build_pipeline(req_data, namespace=user.username)
            
            # Create build record
            repository_url = req_data.get("code_repository")
            branch_ref = req_data.get("algorithm_version")
            current_app.logger.debug("Creating build database record")
            build = _create_and_commit_build(build_id, pipeline, repository_url, branch_ref, user)

        except ValueError as e:
            current_app.logger.warning(f"Build request validation failed: {e}")
            return _generate_error(str(e), status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            current_app.logger.error(f"Build request runtime error: {e}")
            return _generate_error(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            current_app.logger.error(f"Unexpected error during build POST: {type(e).__name__}: {e}")
            current_app.logger.debug(f"Full exception traceback: {traceback.format_exc()}")
            return _generate_error("An unexpected error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        current_app.logger.debug(f"Build request successful, preparing response")
        response_body = {
            "build_id": build.build_id,
            "status": build.status,
            "created": build.created.isoformat(),
            "links": [
                {
                "href": f"/{ns.name}/{build.build_id}",
                "rel": "self",
                "type": "application/json",
                "hreflang": HREF_LANG,
                "title": "Build status link"
            }]
        }
        
        if pipeline:
            current_app.logger.debug(f"Adding pipeline link to response: {pipeline.web_url}")
            response_body["pipelineLink"] = {
                "href": pipeline.web_url,
                "rel": "monitor",
                "type": "text/html",
                "hreflang": HREF_LANG,
                "title": "Link to build pipeline"
            }
        
        current_app.logger.info(f"Build request completed successfully: {build_id}")
        return response_body, status.HTTP_202_ACCEPTED


@ns.route("/<string:build_id>")
class BuildStatus(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, build_id):
        """
        Query the current status of a build
        """
        current_app.logger.debug(f"GET /build/{build_id} - Querying build status")
        build = db.session.query(Build).filter_by(build_id=build_id).first()
        
        if not build:
            current_app.logger.debug(f"Build not found: {build_id}")
            return _generate_error("No build with that build ID found", status.HTTP_404_NOT_FOUND)
        
        current_app.logger.debug(f"Found build {build_id}, checking permissions")
        
        # Check if user has permission to view this build
        user = get_authorized_user()
        current_app.logger.debug(f"User {user.id} requesting build {build_id} (owner: {build.requester})")
        
        if build.requester != user.id:
            current_app.logger.debug("User is not the build owner, checking admin privileges")
            # Check user is not admin
            if not hasattr(user, 'role_id'):
                current_app.logger.debug("User has no role_id, access denied")
                return _generate_error("Access denied", status.HTTP_403_FORBIDDEN)
            if user.role_id != Role.ROLE_NAME_ADMIN:
                current_app.logger.debug(f"User role {user.role_id} is not admin, access denied")
                return _generate_error("Access denied", status.HTTP_403_FORBIDDEN)
            current_app.logger.debug("User has admin privileges, allowing access")
        else:
            current_app.logger.debug("User is the build owner, allowing access")
        
        current_app.logger.debug("Updating build status with pipeline query")
        response_body, status_code = _update_build_status(build, req_data=None, query_pipeline=True)
        current_app.logger.debug(f"Returning build status with code: {status_code}")
        return response_body, status_code


@ns.route("/webhook")
class BuildWebhook(Resource):

    @api.doc(security="ApiKeyAuth")
    @authenticate_third_party()
    def post(self):
        """
        Called by authenticated 3rd parties to update the status of a build via webhooks
        """
        current_app.logger.debug("POST /build/webhook - Received webhook")
        
        try:
            req_data_string = request.data.decode("utf-8")
            current_app.logger.debug(f"Webhook payload length: {len(req_data_string)} characters")
            
            if not req_data_string:
                current_app.logger.debug("Empty webhook payload received")
                return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
            
            req_data = json.loads(req_data_string)
            current_app.logger.debug(f"Parsed webhook JSON with keys: {list(req_data.keys())}")
            
            # Check if this is a pipeline event
            event_type = req_data.get("object_kind")
            current_app.logger.debug(f"Webhook event type: {event_type}")
            
            if event_type != "pipeline":
                current_app.logger.debug(f"Ignoring non-pipeline event: {event_type}")
                return {"message": "Event type not handled"}, status.HTTP_200_OK
            
            pipeline_id = req_data["object_attributes"]["id"]
            current_app.logger.debug(f"Pipeline ID from webhook: {pipeline_id}")
            
            # Log pipeline status if available
            if "object_attributes" in req_data and "status" in req_data["object_attributes"]:
                webhook_status = req_data["object_attributes"]["status"]
                current_app.logger.debug(f"Pipeline status from webhook: {webhook_status}")
                
        except (KeyError, TypeError) as e:
            current_app.logger.debug(f"Failed to parse webhook payload: {e}")
            current_app.logger.debug(f"Webhook payload structure: {req_data if 'req_data' in locals() else 'Failed to parse JSON'}")
            return _generate_error('Expected request body to include pipeline_id at ["object_attributes"]["id"]', status.HTTP_400_BAD_REQUEST)
        except json.JSONDecodeError as e:
            current_app.logger.error(f"Invalid JSON in webhook payload: {e}")
            return _generate_error("Invalid JSON in request body", status.HTTP_400_BAD_REQUEST)
        
        # Find build by pipeline ID
        current_app.logger.debug(f"Looking up build for pipeline ID: {pipeline_id}")
        build = db.session.query(Build).filter_by(
            pipeline_id=pipeline_id
        ).first()
        
        if build:
            current_app.logger.debug(f"Found build {build.build_id} for pipeline {pipeline_id}")
        else:
            current_app.logger.debug(f"No build found for pipeline {pipeline_id}")
        
        current_app.logger.debug("Processing webhook status update")
        response_body, status_code = _update_build_status(build, req_data, query_pipeline=False)
        current_app.logger.debug(f"Webhook processing complete, returning status: {status_code}")
        return response_body, status_code