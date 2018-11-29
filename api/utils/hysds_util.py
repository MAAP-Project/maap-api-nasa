import json
import os
import re
import uuid
import requests
import api.settings as settings


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
            param_spec = dict()
            param_spec["name"] = key
            param_spec["from"] = "value"
            param_spec["value"] = param[key]
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
    job_spec["disk_usage"] = "10GB"
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["recommended-queues"] = [settings.DEFAULT_QUEUE]
    params = list()
    for param in algorithm_params:
        for key in param:
            param_spec = dict()
            param_spec["name"] = key
            param_spec["destination"] = "positional"
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


def create_config_file(docker_container_url):
    """
    Creates the contents of config.txt file
    Contains the base docker image URL for the job container
    :param docker_container_url:
    :return:
    """
    return docker_container_url


def get_job_submission_json(algorithm, algorithm_params):
    """
    Creates the parameters for the job submission payload
    This JSON is sent back by the CI, on successful container build
    :param algorithm:
    :param algorithm_params:
    :return:
    """
    submission_payload = dict()
    submission_payload["id"] = str(uuid.uuid4())
    job_payload = dict()
    job_payload["job_type"] = "job-{}:{}".format(algorithm, settings.VERSION)

    job_params = dict()
    for param in algorithm_params:
        for key in param:
            job_params[key] = param[key]

    job_payload["params"] = job_params
    submission_payload["job_payload"] = job_payload

    return json.dumps(submission_payload), submission_payload["id"]



def mozart_submit_job(job_type, params = {}):
    """
    Submit a job to Mozart
    :param job_type:
    :param params:
    :return:
    """
    job_payload = dict()
    job_payload["type"] = job_type
    job_payload["queue"] = settings.DEFAULT_QUEUE
    job_payload["priority"] = 0
    job_payload["tags"] = json.dumps(["maap-api_submit"])
    job_payload["params"] = json.dumps(params)

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
