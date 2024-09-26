import json
import logging
import os
import re
import requests
import api.settings as settings
import time
import copy

import api.utils.job_queue
from api.models import job_queue

log = logging.getLogger(__name__)

STATUS_JOB_STARTED = "job-started"
STATUS_JOB_COMPLETED = "job-completed"
STATUS_JOB_QUEUED = "job-queued"
STATUS_JOB_FAILED = "job-failed"
STATUS_JOB_DEDUPED = "job-deduped"
STATUS_JOB_REVOKED = "job-revoked"
STATUS_JOB_OFFLINE = "job-offline"


def get_mozart_job_info(job_id):
    params = dict()
    params["id"] = job_id
    session = requests.Session()
    session.verify = False
    mozart_response = session.get("{}/job/info".format(settings.MOZART_URL), params=params).json()
    mozart_response = add_product_path(mozart_response)
    mozart_response = remove_double_tag(mozart_response)
    return mozart_response

def remove_double_tag(mozart_response):
    """
    Remove duplicates from the tags field 
    :param mozart_response:
    :return: updated mozart_response with duplicate tags removed 
    """
    try:
        tags = mozart_response["result"]["tags"]
        if isinstance(tags, list):
            tags = list(set(tags))
            mozart_response["result"]["tags"] = tags
    except: 
        # Okay if you just cannot access tags, don't need to remove duplicates in this case 
        pass
    return mozart_response

def add_product_path(mozart_response):
    """
    Adds the product folder path as a key value pair into the mozart_response object 
    :param mozart_response:
    :return: updated mozart_response with product_folder_path added  
    """
    try:
        products_staged = mozart_response["result"]["job"]["job_info"]["metrics"]["products_staged"]
        if (len(products_staged) > 1):
            logging.info("Length of products_staged is more than 1. We are only looking at the first element for the product file path")
        # All urls should have the same file path within them 
        product_url = mozart_response["result"]["job"]["job_info"]["metrics"]["products_staged"][0]["urls"][0]
        jobs_output_folder_names = [settings.WORKSPACE_MOUNT_TRIAGE, settings.AWS_TRIAGE_WORKSPACE_BUCKET_PATH, settings.WORKSPACE_MOUNT_SUCCESSFUL_JOBS]
        product_path = None
        for jobs_output_folder_name in jobs_output_folder_names:
            index_folder_name = product_url.find("/"+jobs_output_folder_name+"/")
            if (index_folder_name != -1):
                product_path = product_url[index_folder_name+1:]
                # dps_output is in my private bucket which needs to be appended to its file path
                if (jobs_output_folder_name == settings.WORKSPACE_MOUNT_SUCCESSFUL_JOBS):
                    product_path = settings.WORKSPACE_MOUNT_PRIVATE + "/" + product_path
                # triaged_job needs to map instead to triaged-jobs
                elif (jobs_output_folder_name == settings.AWS_TRIAGE_WORKSPACE_BUCKET_PATH):
                    product_path = product_path.replace(settings.AWS_TRIAGE_WORKSPACE_BUCKET_PATH, settings.WORKSPACE_MOUNT_TRIAGE, 1)
                break
        if (not product_path):      
            product_path = "Product path unavailable, folder output name must be one of "+", ".join(jobs_output_folder_names)
        mozart_response["result"]["job"]["job_info"]["metrics"]["products_staged"][0]["product_folder_path"] = product_path
    except Exception as ex: 
        logging.info("Product url path unable to be found because no products")
    return mozart_response

def get_es_query_by_job_id(job_id):
    """
    ES query for specific job ID
    :param job_id:
    :return:
    """
    query = {
     "query": {
              "bool": {
                "must": [
                    {
                      "term": {
                        "_id": job_id
                      }
                    }
                  ]
                }
              }
            }
    return query


def poll_for_completion(job_id):
    poll = True
    while poll:
        sleep_time = 2
        status_response = mozart_job_status(job_id=job_id)
        logging.info("response: {}".format(json.dumps(status_response)))
        job_status = status_response.get("status")
        if job_status != "job-queued" and job_status != "job-started":
            logging.info("Purge Job Done")
            logging.info("status: {}".format(job_status))
            logging.info("response: {}".format(status_response))
            return job_id, status_response
        else:
            if job_status == "job-queued":
                sleep_time *= 2
            else:
                # if job has started then poll more frequently
                # setting it to 2 seconds
                sleep_time = 2
            time.sleep(sleep_time)


def get_algorithm_file_name(algorithm_name):
    """
    This strips any whitespaces from the algorithm name
    :param algorithm_name:
    :return:
    """
    pattern = re.compile(r"\s+")
    string_without_whitespace = pattern.sub("", algorithm_name)
    return string_without_whitespace


def write_file(path, file_name, body):
    """
    Writes contents to a file in the cloned git repo
    :param path:
    :param file_name:
    :param body:
    :return:
    """
    if not os.path.exists(path):
        print("Creating docker dir")
        os.makedirs(path)
    new_file = open(os.path.join(path, file_name), 'w')
    new_file.write(body)
    new_file.close()

def set_hysds_io_type(data_type):
    if data_type is not None:
        if data_type in ["text", "number", " datetime", "date", "boolean", "enum", "email",
                                      "textarea", "region", "passthrough", "object"]:
            return data_type
        else:
            return "text"
    else:
        return "text"


def create_hysds_io(algorithm_description, inputs, verified=False, submission_type="individual"):
    """
    Creates the contents of HySDS IO file
    :param algorithm_description:
    :param inputs:
    :param verified: indicated whether algorithm is EcoSML verified
    :param submission_type:
    :return:
    """
    hysds_io = dict()
    hysds_io["label"] = algorithm_description
    hysds_io["submission_type"] = submission_type
    params = list()

    for param_type in inputs:
        for param in inputs.get(param_type):
            param_spec = dict()
            param_spec["name"] = param.get("name")
            param_spec["from"] = "submitter"
            """ Future code to support hardcoded values
            param_spec["from"] = "value"
            param_spec["value"] = param.get("value")
            """
            param_spec["type"] = set_hysds_io_type(param.get("data_type"))
            if param.get("default") is not None:
                param_spec["default"] = param.get("default")
            params.append(param_spec)

    if verified:
        verified_param = dict()
        verified_param["name"] = "publish_to_cmr"
        verified_param["from"] = "submitter"
        verified_param["type"] = "boolean"
        verified_param["default"] = "false"
        cmr_met_param = dict()
        cmr_met_param["name"] = "cmr_collection_id"
        cmr_met_param["from"] = "submitter"
        cmr_met_param["type"] = "text"
        cmr_met_param["default"] = ""
        params.append(verified_param)
        params.append(cmr_met_param)

    hysds_io["params"] = params
    return hysds_io

def create_job_spec(run_command, inputs, disk_usage, queue_name, verified=False):
    """
    Creates the contents of the job spec file
    :param run_command:
    :param inputs:
    :param disk_usage: minimum free disk usage required to run job specified as
    "\d+(GB|MB|KB)", e.g. "100GB", "20MB", "10KB"
    :param queue_name: set the recommended queue to run the algorithm on
    :param verified: indicated whether algorithm is EcoSML verified
    :return:
    """
    job_spec = dict()
    job_spec["command"] = "/app/dps_wrapper.sh '{}'".format(run_command)
    job_spec["disk_usage"] = disk_usage
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "$HOME/verdi/etc/maap-dps.env": "/home/ops/.maap-dps.env",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["post"] = ["hysds.triage.triage"]
    job_spec["recommended-queues"] = [queue_name]
    params = list()
    for param_type in inputs:
        if param_type == "file":
            destination = "localize"
        elif param_type == "positional":
            destination = "positional"
        elif param_type == "config":
            destination = "context"
        for param in inputs.get(param_type):
            param_spec = dict()
            param_spec["name"] = param.get("name")
            param_spec["destination"] = destination
            params.append(param_spec)

    if verified:
        verified_param = dict()
        verified_param["name"] = "publish_to_cmr"
        verified_param["destination"] = "context"
        cmr_met_param = dict()
        cmr_met_param["name"] = "cmr_collection_id"
        cmr_met_param["destination"] = "context"
        params.append(verified_param)
        params.append(cmr_met_param)
    job_spec["params"] = params
    return job_spec


def write_spec_file(spec_type, algorithm, body, repo_name=settings.REPO_NAME):
    """
    Writes the spec files to file in docker directory
    :param spec_type:
    :param algorithm:
    :param body:
    :param repo_name:
    :return:
    """
    path = "{}/{}/docker/".format(settings.REPO_PATH, repo_name)
    file_name = "{}.json.{}".format(spec_type, get_algorithm_file_name(algorithm))
    # Additions to job spec schema in HySDS core v3.0
    body.update({"soft_time_limit": 86400, "time_limit": 86400})
    write_file(path, file_name, json.dumps(body))


def write_dockerfile(repo_name, dockerfile_content):
    """
    Write the docker file to the docker directory
    :param dockerfile_content:
    :return:
    """
    path = "{}/{}/docker/".format(settings.REPO_PATH, repo_name)
    write_file(path, "Dockerfile", dockerfile_content)


def create_config_file(repo_name, repo_url_w_token, repo_branch, verified=False,
                       docker_container_url=settings.CONTAINER_URL,
                       build_command=None):
    """
    Creates the contents of config.txt file
    Contains the information needed for the job container

    Example content:
    BASE_IMAGE_NAME=<registery-url>/root/jupyter_image/vanilla:1.0
    REPO_URL_WITH_TOKEN=https://<gitlab-token>@mas.maap-project.org/root/dps_plot.git
    REPO_NAME=dps_plot
    BRANCH=master
    GRQ_REST_URL=<grq-ip>/api/v0.1
    MAAP_API_URL=https:api.dit.maap-project.org/api
    MOZART_URL=<mozart-ip>/mozart/api/v0.1
    S3_CODE_BUCKET=s3://s3.amazon.aws.com/<bucket-name>

    :param repo_name:
    :param repo_url_w_token:
    :param repo_branch:
    :param verified: Indicated if algorithm is EcoSML verified
    :param docker_container_url:
    :param build_command:
    :return: config.txt content
    """
    
    config_content = "BASE_IMAGE_NAME={}\n".format(docker_container_url)
    config_content += "REPO_URL_WITH_TOKEN={}\n".format(repo_url_w_token)
    config_content += "REPO_NAME={}\n".format(repo_name)
    config_content += "BRANCH={}\n".format(repo_branch)
    config_content += "GRQ_REST_URL={}\n".format(settings.GRQ_REST_URL)
    config_content += "MAAP_API_URL={}\n".format(settings.MAAP_API_URL)
    config_content += "MOZART_URL={}\n".format(settings.MOZART_V1_URL)
    config_content += "S3_CODE_BUCKET={}\n".format(settings.S3_CODE_BUCKET)

    if build_command:
        config_content += "\nBUILD_CMD={}".format(build_command)

    return config_content


def create_dockerfile(base_docker_image_name, label, repo_url, repo_name, branch):
    """
    This will create the Dockerfile the container builder on the CI will use.
    :param base_docker_image_name:
    :param repo_url:
    :param repo_name:
    :param branch:

    sample:
    FROM ${BASE_IMAGE_NAME}

    MAINTAINER malarout "Namrata.Malarout@jpl.nasa.gov"
    LABEL description="Lightweight System Jobs"

    # provision lightweight-jobs PGE
    USER ops

    #clone in the SPDM repo
    RUN git clone ${REPO_URL_WITH_TOKEN} && \
        cd ${REPO_NAME} && \
        git checkout ${BRANCH} && \

    # set entrypoint
    WORKDIR /home/ops
    CMD ["/bin/bash", "--login"]
    :return:
    """
    dockerfile = "FROM {}\n".format(base_docker_image_name)
    dockerfile += "LABEL description={}\n".format(label)
    dockerfile += "USER ops\n"
    dockerfile += "RUN git clone {} && ".format(repo_url)
    dockerfile += "    cd {} && ".format(repo_name)
    dockerfile += "    git checkout {}".format(branch)
    dockerfile += "\n# set entrypoint\n"
    dockerfile += "WORKDIR /home/ops\n"
    dockerfile += "CMD [\"bin/bash\", \"--login\"]"

    return dockerfile


def create_code_info(repo_url, repo_name, docker_container_url=settings.CONTAINER_URL, path_to_dockerfile=None):
    """

    :param repo_url:
    :param repo_name:
    :param docker_container_url:
    :param path_to_dockerfile:
    :return:
    """
    return json.dumps({
        "repo_url": repo_url,
        "repo_name": repo_name,
        "docker_file_url": docker_container_url,
        "path_to_dockerfile": path_to_dockerfile
    })


def get_job_submission_json(algorithm, branch=settings.VERSION):
    """
    This JSON is sent back by the CI, on successful container build
    :param algorithm:
    :param branch:
    :return:
    """
    job_json = dict()
    job_json["job_type"] = "job-{}:{}".format(algorithm, branch)
    return json.dumps(job_json)


def get_algorithms():
    """
    Get the list of job specs
    :return:
    """
    headers = {'content-type': 'application/json'}

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/job_spec/list".format(settings.MOZART_URL), headers=headers, verify=False)
    except Exception as ex:
        raise ex

    algo_list = mozart_response.json().get("result")
    maap_algo_list = list()
    for algo in algo_list:
        if not algo.startswith("job-lw-") and not algo.startswith("job-lightweight"):
            maap_algo_list.append(algo)

    return maap_algo_list


def mozart_submit_job(job_type, params={}, queue="", dedup="false", identifier="maap-api_submit",
                      job_time_limit=86400):
    """
    Submit a job to Mozart
    :param job_type:
    :param params:
    :param queue:
    :param dedup:
    :param identifier:
    :param job_time_limit:
    :return:
    """

    logging.info("Received parameters for job: {}".format(json.dumps(params)))

    job_payload = dict()
    job_payload["type"] = job_type
    job_payload["queue"] = queue
    job_payload["priority"] = 0
    tags_list = ["maap-api-submit"]
    if identifier is not None:
        if type(identifier) is list:
            tags_list = identifier
        elif type(identifier) is str:
            tags_list = str(identifier).split(",")
    job_payload["tags"] = json.dumps(tags_list)

    # assign username to job
    if params.get("username") is not None:
        job_payload["username"] = params.get("username").strip()

    # remove username from algo params if provided.
    params.pop('username', None)
    job_payload["params"] = json.dumps(params)
    job_payload["enable_dedup"] = dedup
    job_payload["soft_time_limit"] = job_time_limit
    job_payload["time_limit"] = job_time_limit

    logging.info("job payload: {}".format(json.dumps(job_payload)))

    headers = {'content-type': 'application/json'}

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.post("{}/job/submit".format(settings.MOZART_URL),
                                       params=job_payload, headers=headers,
                                       verify=False).json()
    except Exception as ex:
        raise ex

    return mozart_response


def get_username_from_job_submission(params={}):
    if params.get("username") is not None:
        return params.get("username").strip()
    else:
        return None
        

def mozart_job_status(job_id):
    """
    Returns mozart's job status
    :param job_id:
    :return:
    """
    params = dict()
    params["id"] = job_id

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/job/status".format(settings.MOZART_URL), params=params)
        logging.info("Job Status::: {}".format(mozart_response.json()))
    except Exception as ex:
        raise ex

    return mozart_response.json()


def mozart_delete_job_type(job_type):
    params = dict()
    params["id"] = job_type

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/job_spec/remove".format(settings.MOZART_V1_URL), params=params)
    except Exception as ex:
        raise ex

    return mozart_response.json()


def get_job_spec(job_type):
    """
    Get the job spec of a registered algorigthm
    :param job_type:
    :return:
    """
    headers = {'content-type': 'application/json'}

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/job_spec/type?id={}".format(settings.MOZART_V1_URL, job_type), headers=headers,
                                      verify=False)
    except Exception as ex:
        raise ex

    return mozart_response.json()


def get_hysds_io(hysdsio_type):
    """
        Get the hysds-io of a registered algorigthm
        :param hysdsio_type:
        :return:
        """
    headers = {'content-type': 'application/json'}

    session = requests.Session()
    session.verify = False

    try:
        grq_response = session.get("{}/hysds_io/type?id={}".format(settings.GRQ_URL, hysdsio_type), headers=headers,
                                   verify=False)
        logging.debug(grq_response)
    except Exception as ex:
        raise ex

    return grq_response.json()


def get_recommended_queue(job_type):
    response = get_job_spec(job_type)
    recommended_queues = response.get("result", None).get("recommended-queues", None)
    recommended_queue = recommended_queues[0] if type(recommended_queues) is list else None
    return recommended_queue if recommended_queue != "" else api.utils.job_queue.get_default_queue().queue_name


def validate_job_submit(hysds_io, user_params):
    """
    Given user's input params and the hysds-io spec for the job type
    This function validates if all the input params were provided,
    if not provided then fill in the default value specified during registration
    :param hysds_io:
    :param user_params:
    :return:
    """
    # building a dictionary of key value pairs of the parameters registered
    reg_params = hysds_io.get("result").get("params")
    known_params = dict()
    for param in reg_params:
        param_info = dict()
        param_name = param.get("name")
        param_info["from"] = param.get("from")
        param_info["default"] = param.get("default", None)
        param_info["type"] = param.get("type", str)
        known_params[param_name] = param_info

    """
    Verify if user provided all the parameters
    - if not, check if default was provided on registration and set to that value
    - else throw an error saying parameter missing
    """
    validated_params = dict()
    # do not miss the username in params
    validated_params["username"] = user_params.get("username")
    for p in known_params:
        if user_params.get(p) is not None:
            validated_params[p] = user_params.get(p)
            # TODO: Check datatype of input, if provided in spec
        else:
            if known_params.get(p).get("default") is not None:
                validated_params[p] = known_params.get(p).get("default")
            else:
                raise ValueError("Parameter {} missing from inputs. Didn't find any default set for it in "
                                 "algorithm specification. Please specify it and attempt to submit.".format(p))
    return validated_params


def get_mozart_job(job_id):
    job_status = mozart_job_status(job_id).get("status")
    if job_status == "job-completed" or job_status == "job-failed":
        try:
            mozart_response = get_mozart_job_info(job_id)
            result = mozart_response.get("result")
            return result
        except Exception as ex:
            raise ex
    else:
        raise Exception("Aborting retrieving information of job because status is {}".format(job_status))


def get_mozart_queues():
    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/queue/list".format(settings.MOZART_URL)).json()
        logging.debug("Response from {}/queue/list:\n{}".format(settings.MOZART_URL, mozart_response))
        if mozart_response.get("success") is True:
            try:
                queues_list = mozart_response.get("result").get("queues")
                result = [queue for queue in queues_list if queue.startswith(settings.PROJECT_QUEUE_PREFIX)]
                return result
            except Exception as ex:
                raise ex
    except:
        raise Exception("Couldn't get list of available queues")


def get_mozart_jobs(username, 
                    end_time=None,
                    job_type=None,
                    offset=0, 
                    page_size=10,
                    priority=None,
                    queue=None,
                    start_time=None,
                    status=None,
                    tag=None
                    ):
    """
    Returns mozart's job list
    :param username: Username
    :param page_size: Page size for pagination
    :param offset: Offset for pagination
    :param status: Job status
    :param end_time: End time
    :param start_time: Start time
    :param priority: Job priority
    :param queue: Queue
    :param tag: User tag
    :param job_type: Algorithm type
    :return: Job list
    """
    params = {
        k: v
        for k, v in (
            ("end_time", end_time),
            ("job_type", job_type),
            ("offset", offset),
            ("page_size", page_size),
            ("priority", priority),
            ("queue", queue),
            ("start_time", start_time),
            ("status", status),
            ("tag", tag),
        )
        if v is not None
    }

    session = requests.Session()
    session.verify = False

    logging.debug("Job params: {}".format(params))

    try:
        param_list = ""
        for key, value in params.items():
            param_list += "&{}={}".format(key, value)

        if settings.HYSDS_VERSION == "v3.0":
            if username is not None:
                param_list += f"&username={username}"
            url = "{}/job/list?{}".format(settings.MOZART_URL, param_list[1:])
        elif settings.HYSDS_VERSION == "v4.0":
            url = "{}/job/user/{}?{}".format(settings.MOZART_URL, username, param_list[1:])
        logging.info("GET request to find jobs: {}".format(url))
        mozart_response = session.get(url)

    except Exception as ex:
        raise ex

    return mozart_response.json()


def get_jobs_info(job_list):
    """
    Returns Job infos
    :param job_list:
    :return:
    """
    jobs_info = list()
    try:
        for job_id in job_list:
            job = dict()
            mozart_response = get_mozart_job_info(job_id)
            success = mozart_response.get("success")
            if success is True:
                job[job_id] = mozart_response.get("result")
            else:
                job[job_id] = {"message": "Failed to get job info"}
            jobs_info.append(job)
    except Exception as ex:
        logging.exception(ex)
        raise ex

    return jobs_info


def delete_mozart_job_type(job_type):
    params = dict()
    params["id"] = job_type
    session = requests.Session()
    session.verify = False

    response = mozart_delete_job_type(job_type)
    status = response.get("success")
    message = response.get("message")
    if status is True:
            return status
    else:
        raise Exception("Failed to remove job spec. Error: {}".format(message))


def delete_mozart_job(job_id, wait_for_completion=False):
    """
    This function deletes a job from Mozart
    :param job_id:
    :return:
    """
    job_type = "job-lw-mozart-purge:{}".format(settings.HYSDS_LW_VERSION)
    params = {
        "query": get_es_query_by_job_id(job_id),
        "component": "mozart",
        "operation": "purge"
    }
    logging.info("Submitting job of type {} with params {}".format(job_type, json.dumps(params)))
    submit_response = mozart_submit_job(job_type=job_type, params=params, queue=settings.LW_QUEUE,
                                        identifier=[f"purge-{job_id}"])
    lw_job_id = submit_response.get("result")
    logging.info(lw_job_id)
    if not wait_for_completion:
        return lw_job_id, None
    # keep polling mozart until the purge job is finished.
    return poll_for_completion(lw_job_id)


def revoke_mozart_job(job_id, wait_for_completion=False):
    """
    This function deletes a job from Mozart
    :param wait_for_completion:
    :param job_id:
    :return: job_id, status
    """
    job_type = "job-lw-mozart-revoke:{}".format(settings.HYSDS_LW_VERSION)
    params = {
        "query": get_es_query_by_job_id(job_id),
        "component": "mozart",
        "operation": "revoke"
    }
    logging.info("Submitting job of type {} with params {}".format(job_type, json.dumps(params)))
    submit_response = mozart_submit_job(job_type=job_type, params=params, queue=settings.LW_QUEUE,
                                        identifier=[f"revoke-{job_id}"])
    lw_job_id = submit_response.get("result")
    logging.info(lw_job_id)
    if not wait_for_completion:
        return lw_job_id, None
    # keep polling mozart until the purge job is finished.
    return poll_for_completion(lw_job_id)


def set_timelimit_for_dps_sandbox(params: dict, queue: job_queue):
    """
    Sets the soft_time_limit and time_limit parameters for DPS sandbox queue
    at job submission
    :param params:
    :param queue: Job queue
    :return: params
    """
    params.update({"soft_time_limit": queue.time_limit_minutes * 60,
                   "time_limit": queue.time_limit_minutes * 60})
