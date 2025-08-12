import json
import logging
import uuid
import traceback
import base64
import re
from datetime import datetime

import gitlab
from flask import request
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
    if not algorithm_name:
        raise ValueError("algorithm_name is required")
    
    if len(algorithm_name) < 2 or len(algorithm_name) > 255:
        raise ValueError("algorithm_name must be between 2 and 255 characters long")
    
    # Check if contains only allowed characters (lowercase letters, digits, hyphens, underscores)
    if not re.match(r'^[a-z0-9_-]+$', algorithm_name):
        raise ValueError("algorithm_name can only contain lowercase letters, digits, hyphens (-), and underscores (_)")
    
    return algorithm_name


def _validate_algorithm_version(algorithm_version):
    """
    Validates algorithm version format.
    - Must be valid ASCII characters
    - Can contain lowercase and uppercase letters, digits, underscores (_), periods (.), and dashes (-)
    - Can be up to 128 characters long
    - Must conform to the regex pattern: [a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}
    """
    if not algorithm_version:
        raise ValueError("algorithm_version is required")
    
    if len(algorithm_version) > 128:
        raise ValueError("algorithm_version can be up to 128 characters long")
    
    # Check if contains only ASCII characters
    try:
        algorithm_version.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError("algorithm_version must contain only valid ASCII characters")
    
    # Check if matches the required pattern: starts with letter/digit/underscore, 
    # followed by letters/digits/underscores/periods/dashes
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$', algorithm_version):
        raise ValueError("algorithm_version must start with a letter, digit, or underscore and can only contain letters, digits, underscores (_), periods (.), and dashes (-)")
    
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
    # Required variables
    if payload.get("code_repository") is None:
        raise ValueError("code_repository is required")
    
    # Image name - derive from algorithm_name if not provided
    algorithm_name = payload.get("algorithm_name")
    # Validate algorithm name format
    _validate_algorithm_name(algorithm_name)
    
    # Image tag - derive from algorithm_version if not provided
    algorithm_version = payload.get("algorithm_version")
    # Validate algorithm version format
    _validate_algorithm_version(algorithm_version)


def _trigger_build_pipeline(payload, namespace):
    """Triggers a GitLab pipeline for the build request."""
    try:
        gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_BUILD_APP_PACK_PIPELINE_TOKEN)
        project = gl.projects.get(settings.GITLAB_BUILD_APP_PACK_PROJECT_ID)
        
        # Extract and validate required variables from payload
        variables = []
        
        # Required variables
        repository_url = payload.get("code_repository")
        variables.append({"key": "REPOSITORY_URL", "value": repository_url})
        
        # Build command
        build_cmd = payload.get("build_command")
        if build_cmd:
            variables.append({"key": "BUILD_CMD", "value": build_cmd})
        
        # Base image with fallback
        base_image = payload.get("base_image")
        if base_image:
            variables.append({"key": "BASE_IMAGE_NAME", "value": base_image})
        
        algorithm_name = payload.get("algorithm_name")
        image_name = f"{namespace}/{algorithm_name}"
        variables.append({"key": "IMAGE_NAME", "value": image_name})
        
        algorithm_version = payload.get("algorithm_version")
        variables.append({"key": "IMAGE_TAG", "value": algorithm_version})
        variables.append({"key": "BRANCH_REF", "value": algorithm_version})
        
        # Base64 encode the algorithm configuration
        algo_config_json = json.dumps(payload)
        algo_config_b64 = base64.b64encode(algo_config_json.encode()).decode()
        variables.append({"key": "ALGO_CONFIG_JSON_B64", "value": algo_config_b64})
        
        log.info(f"GitLab CI variables: {[{k['key']: k['value'][:50] + '...' if len(k['value']) > 50 else k['value'] for k in variables}]}")
        
        pipeline = project.pipelines.create({
            "ref": settings.GITLAB_BUILD_APP_PACK_PIPELINE_REF,
            "variables": variables
        })
        
        log.info(f"Triggered build pipeline ID: {pipeline.id}")
        return pipeline
        
    except Exception as e:
        log.error(f"GitLab pipeline trigger failed: {e}")
        raise RuntimeError("Failed to start build pipeline. The build service may be down.")


def _create_and_commit_build(build_id, pipeline, repository_url, branch_ref, user):
    """Creates a new build record in the database."""
    build = Build(
        build_id=build_id,
        status=INITIAL_BUILD_STATUS,
        requester=user.id,
        repository_url=repository_url, 
        branch_ref=branch_ref,
        pipeline_id=pipeline.id if pipeline else None,
        pipeline_url=pipeline.web_url if pipeline else None
    )
        
    db.session.add(build)
    db.session.commit()
    return build


def _update_build_status(build, req_data=None, query_pipeline=False):
    """Updates the status of the build if applicable"""
    status_code = status.HTTP_200_OK

    if build is None:
        return _generate_error("No build with that build ID found", status.HTTP_404_NOT_FOUND)

    current_status = build.status
    pipeline_url = build.pipeline_url

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
        if query_pipeline:
            try:
                gl = gitlab.Gitlab(settings.GITLAB_URL, private_token=settings.GITLAB_BUILD_APP_PACK_PIPELINE_TOKEN)
                project = gl.projects.get(settings.GITLAB_BUILD_APP_PACK_PROJECT_ID)
                pipeline = project.pipelines.get(build.pipeline_id)
                updated_status = pipeline.status
                pipeline_url = pipeline.web_url
            except Exception as e:
                log.error(f"Failed to query GitLab pipeline {build.pipeline_id}: {e}")
                updated_status = build.status  # Fallback to current status on error
        else:
            try:
                updated_status = req_data["object_attributes"]["status"]
            except (TypeError, KeyError):
                return _generate_error('Payload from 3rd party should have status at ["object_attributes"]["status"]', status.HTTP_400_BAD_REQUEST)
        
        # Map GitLab status to our status
        status_mapping = {
            "success": "successful",
            "failed": "failed",
            "canceled": "canceled",
            "skipped": "dismissed"
        }
        current_status = status_mapping.get(updated_status, updated_status)

        if current_status in BUILD_FINISHED_STATUSES:
            build.status = current_status
            build.updated = datetime.now(datetime.timezone.utc)
            db.session.commit()
            response_body.update({"updated": build.updated.isoformat()})        

    response_body.update({"status": current_status})
    if pipeline_url:
        response_body.update({
                "pipelineLink": {
                    "href": pipeline_url,
                    "rel": "monitor",
                    "type": "text/html",
                    "hreflang": HREF_LANG,
                    "title": "Link to build pipeline"
                }
            })
    
    return response_body, status_code


@ns.route("")
class BuildList(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self):
        """
        Get all builds for the current user
        """
        user = get_authorized_user()
        
        # Query builds for the current user
        builds = db.session.query(Build).filter_by(requester=user.id).order_by(Build.created.desc()).all()
        
        build_list = []
        for build in builds:
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
                build_info["pipelineLink"] = {
                    "href": build.pipeline_url,
                    "rel": "monitor", 
                    "type": "text/html",
                    "hreflang": HREF_LANG,
                    "title": "Link to build pipeline"
                }
            
            build_list.append(build_info)
        
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
        req_data = request.get_json()
        try:
            _validate_build_payload(req_data)
            user = get_authorized_user()
            build_id = str(uuid.uuid4())
            # Trigger GitLab pipeline (validation happens inside)
            pipeline = _trigger_build_pipeline(req_data, namespace=user.username)
            
            # Create build record
            repository_url = req_data.get("code_repository")
            branch_ref = req_data.get("algorithm_version")
            build = _create_and_commit_build(build_id, pipeline, repository_url, branch_ref, user)

        except ValueError as e:
            return _generate_error(str(e), status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            return _generate_error(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            log.error(f"Unexpected error during build POST: {traceback.format_exc()}")
            return _generate_error("An unexpected error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)

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
            response_body["pipelineLink"] = {
                "href": pipeline.web_url,
                "rel": "monitor",
                "type": "text/html",
                "hreflang": HREF_LANG,
                "title": "Link to build pipeline"
            }
        
        return response_body, status.HTTP_202_ACCEPTED


@ns.route("/<string:build_id>")
class BuildStatus(Resource):

    @api.doc(security="ApiKeyAuth")
    @login_required()
    def get(self, build_id):
        """
        Query the current status of a build
        """
        build = db.session.query(Build).filter_by(build_id=build_id).first()
        
        if not build:
            return _generate_error("No build with that build ID found", status.HTTP_404_NOT_FOUND)
        
        # Check if user has permission to view this build
        user = get_authorized_user()
        if build.requester != user.id:
            # Check user is not admin
            if not hasattr(user, 'role_id'):
                return _generate_error("Access denied", status.HTTP_403_FORBIDDEN)
            if user.role_id != Role.ROLE_NAME_ADMIN:
                return _generate_error("Access denied", status.HTTP_403_FORBIDDEN)
        
        response_body, status_code = _update_build_status(build, req_data=None, query_pipeline=True)
        return response_body, status_code


@ns.route("/webhook")
class BuildWebhook(Resource):

    @api.doc(security="ApiKeyAuth")
    @authenticate_third_party()
    def post(self):
        """
        Called by authenticated 3rd parties to update the status of a build via webhooks
        """
        try:
            req_data_string = request.data.decode("utf-8")
            if not req_data_string:
                return _generate_error("Body expected in request", status.HTTP_400_BAD_REQUEST)
            
            req_data = json.loads(req_data_string)
            
            # Check if this is a pipeline event
            if req_data.get("object_kind") != "pipeline":
                return {"message": "Event type not handled"}, status.HTTP_200_OK
            
            pipeline_id = req_data["object_attributes"]["id"]
        except (KeyError, TypeError):
            return _generate_error('Expected request body to include pipeline_id at ["object_attributes"]["id"]', status.HTTP_400_BAD_REQUEST)
        
        # Find build by pipeline ID
        build = db.session.query(Build).filter_by(
            pipeline_id=pipeline_id,
            execution_venue=settings.DEPLOY_PROCESS_EXECUTION_VENUE
        ).first()
        
        response_body, status_code = _update_build_status(build, req_data, query_pipeline=False)
        return response_body, status_code