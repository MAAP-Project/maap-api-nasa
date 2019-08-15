import json
import os
import re
import requests
import api.settings as settings
import datetime


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


def create_job_spec(script_command, algorithm_params):
    """
    Creates the contents of the job spec file
    :param script_command:
    :param algorithm_params:
    :return:
    """
    job_spec = dict()
    job_spec["command"] = script_command
    job_spec["disk_usage"] = "65GB"
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["recommended-queues"] = [settings.DEFAULT_QUEUE]
    params = list()
    for param in algorithm_params:
        destination = "positional"
        if param.get("download", False):
            destination = "localize"
        for key in param:
            if key != "download":
                param_spec = dict()
                param_spec["name"] = param[key]
                if param[key] == "username":
                    param_spec["destination"] = "context"
                else:
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
    write_file(path, file_name, json.dumps(body))


def create_config_file(docker_container_url=settings.CONTAINER_URL):
    """
    Creates the contents of config.txt file
    Contains the base docker image URL for the job container
    :param docker_container_url:
    :return:
    """

    return docker_container_url


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


def mozart_submit_job(job_type, params={}, dedup="false"):
    """
    Submit a job to Mozart
    :param job_type:
    :param params:
    :param dedup:
    :return:
    """

    job_payload = dict()
    job_payload["type"] = job_type
    job_payload["queue"] = settings.DEFAULT_QUEUE
    job_payload["priority"] = 0
    job_payload["tags"] = json.dumps(["maap-api_submit"])
    job_payload["params"] = json.dumps(params)
    job_payload["enable_dedup"] = dedup
    job_payload["username"] = params.get("username").strip()

    print(json.dumps(job_payload))

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


def get_mozart_job_info(job_id):
    params = dict()
    params["id"] = job_id
    session = requests.Session()
    session.verify = False

    job_status = mozart_job_status(job_id).get("status")
    if job_status == "job-completed":
        try:
            mozart_response = session.get("{}/job/info".format(settings.MOZART_URL), params=params).json()
            result = mozart_response.get("result")
            return result
        except Exception as ex:
            raise ex
    else:
        raise Exception("Aborting retrieving information of job because status is {}".format(job_status))


def get_mozart_jobs(username):
    """
        Returns mozart's job list
        :param username:
        :return:
        """
    params = dict()
    params["username"] = username

    session = requests.Session()
    session.verify = False

    try:
        mozart_response = session.get("{}/job/list".format(settings.MOZART_URL), params=params)

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
    return mozart_submit_job(job_type=job_type, params=params)

