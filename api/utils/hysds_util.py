import json
import logging
import os
import re
import requests
import api.settings as settings
import time

log = logging.getLogger(__name__)


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


def create_hysds_io(algorithm_description, algorithm_params, submission_type="individual"):
    """
    Creates the contents of HySDS IO file
    :param algorithm_description:
    :param algorithm_params:
    :param submission_type:
    :return:
    """
    hysds_io = dict()
    hysds_io["label"] = algorithm_description
    hysds_io["submission_type"] = submission_type
    params = list()

    for param in algorithm_params:
        for key in param:
            if key != "download":
                param_spec = dict()
                param_spec["name"] = param[key]
                param_spec["from"] = "submitter"
                params.append(param_spec)

    hysds_io["params"] = params
    return hysds_io


def create_job_spec(script_command, algorithm_params, disk_usage, queue_name=settings.DEFAULT_QUEUE):
    """
    Creates the contents of the job spec file
    :param script_command:
    :param algorithm_params:
    :param disk_usage: minimum free disk usage required to run job specified as
    "\d+(GB|MB|KB)", e.g. "100GB", "20MB", "10KB"
    :param queue_name: set the recommended queue to run the algorithm on
    :return:
    """
    job_spec = dict()
    job_spec["command"] = "/app/dps_wrapper.sh '{}'".format(script_command)
    job_spec["disk_usage"] = disk_usage
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["recommended-queues"] = [queue_name]
    params = list()
    for param in algorithm_params:
        destination = "positional"
        if param.get("download", False):
            destination = "localize"
        for key in param:
            if key != "download":
                param_spec = dict()
                param_spec["name"] = param[key]
                param_spec["destination"] = destination
                params.append(param_spec)

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


def create_config_file(repo_name, repo_url_w_token, repo_branch, docker_container_url=settings.CONTAINER_URL):
    """
    Creates the contents of config.txt file
    Contains the information needed for the job container

    Example content:
    BASE_IMAGE_NAME=<registery-url>/root/jupyter_image/vanilla:1.0
    REPO_URL_WITH_TOKEN=https://<gitlab-token>@mas.maap-project.org/root/dps_plot.git
    REPO_NAME=dps_plot
    BRANCH=master
    GRQ_REST_URL=<grq-ip>/api/v0.1
    MAAP_API_URL=https:api.nasa.maap.xyz/api
    MOZART_URL=<mozart-ip>/mozart/api/v0.1
    S3_CODE_BUCKET=s3://s3.amazon.aws.com/<bucket-name>

    :param repo_name:
    :param repo_url_w_token:
    :param repo_branch:
    :param docker_container_url:
    :return: config.txt content
    """
    config_content = "BASE_IMAGE_NAME={}\n".format(docker_container_url)
    config_content += "REPO_URL_WITH_TOKEN={}\n".format(repo_url_w_token)
    config_content += "REPO_NAME={}\n".format(repo_name)
    config_content += "BRANCH={}\n".format(repo_branch)
    config_content += "GRQ_REST_URL={}\n".format(settings.GRQ_REST_URL)
    config_content += "MAAP_API_URL={}\n".format(settings.MAAP_API_URL)
    config_content += "MOZART_URL={}\n".format(settings.MOZART_V1_URL)
    config_content += "S3_CODE_BUCKET={}".format(settings.S3_CODE_BUCKET)

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


def mozart_submit_job(job_type, params={}, queue=settings.DEFAULT_QUEUE, dedup="false"):
    """
    Submit a job to Mozart
    :param job_type:
    :param params:
    :param queue:
    :param dedup:
    :return:
    """

    logging.info("Received parameters for job: {}".format(json.dumps(params)))

    job_payload = dict()
    job_payload["type"] = job_type
    job_payload["queue"] = queue
    job_payload["priority"] = 0
    job_payload["tags"] = json.dumps(["maap-api_submit"])
    # assign username to job
    if params.get("username") is not None:
        job_payload["username"] = params.get("username").strip()
    # remove username from algo params if provided.
    params.pop('username', None)
    job_payload["params"] = json.dumps(params)
    job_payload["enable_dedup"] = dedup

    logging.info("job payload: {}".format(json.dumps(job_payload)))

    headers = {'content-type': 'application/json'}

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.post("{}/job/submit".format(settings.MOZART_URL),
                                       params=job_payload, headers=headers,
                                       verify=False)
    except Exception as ex:
        raise ex
    return mozart_response.json()


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
        mozart_response = session.get("{}/job_spec/remove".format(settings.MOZART_URL), params=params)
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
        mozart_response = session.get("{}/job_spec/type?id={}".format(settings.MOZART_URL, job_type), headers=headers,
                                      verify=False)
    except Exception as ex:
        raise ex

    return mozart_response.json()


def get_recommended_queue(job_type):
    response = get_job_spec(job_type)
    recommended_queues = response.get("result", None).get("recommended-queues", None)
    recommended_queue = recommended_queues[0] if type(recommended_queues) is list else None
    return recommended_queue if recommended_queue != "" else settings.DEFAULT_QUEUE


def get_mozart_job_info(job_id):
    params = dict()
    params["id"] = job_id
    session = requests.Session()
    session.verify = False

    job_status = mozart_job_status(job_id).get("status")
    if job_status == "job-completed" or job_status == "job-failed":
        try:
            mozart_response = session.get("{}/job/info".format(settings.MOZART_URL), params=params).json()
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
        if mozart_response.get("success") is True:
            try:
                queues_list = mozart_response.get("result").get("queues")
                result = [queue for queue in queues_list if queue.startswith(settings.PROJECT_QUEUE_PREFIX)]
                return result
            except Exception as ex:
                raise ex
    except:
        raise Exception("Couldn't get list of available queues")


def get_mozart_jobs(username, page_size=10, offset=0):
    """
        Returns mozart's job list
        :param username:
        :return:
        """
    params = dict()
    params["page_size"] = page_size
    params["id"] = offset  # this is specifies the offset
    params["username"] = username
    params["detailed"] = True
    params["paginate"] = True

    session = requests.Session()
    session.verify = False

    try:
        param_list = ""
        for key, value in params:
            param_list += "&{}={}".format(key, value)

        url = "{}/job/list?{}".format(settings.MOZART_URL, param_list[1:])
        print("GET request to: {}".format(url))
        mozart_response = session.get(url)

    except Exception as ex:
        raise ex

    return mozart_response.json()


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


def delete_mozart_job(job_id):
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
    submit_response = mozart_submit_job(job_type=job_type, params=params, queue=settings.LW_QUEUE)
    lw_job_id = submit_response.get("result")
    logging.info(lw_job_id)

    # keep polling mozart until the purge job is finished.
    return poll_for_completion(lw_job_id)


def revoke_mozart_job(job_id):
    """
    This function deletes a job from Mozart
    :param job_id:
    :return:
    """
    job_type = "job-lw-mozart-revoke:{}".format(settings.HYSDS_LW_VERSION)
    params = {
        "query": get_es_query_by_job_id(job_id),
        "component": "mozart",
        "operation": "revoke"
    }
    logging.info("Submitting job of type {} with params {}".format(job_type, json.dumps(params)))
    submit_response = mozart_submit_job(job_type=job_type, params=params, queue = settings.LW_QUEUE)
    lw_job_id = submit_response.get("result")
    logging.info(lw_job_id)

    # keep polling mozart until the purge job is finished.
    return poll_for_completion(lw_job_id)



