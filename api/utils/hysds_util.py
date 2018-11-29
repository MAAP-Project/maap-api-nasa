import json
import os
import re
import requests
import api.settings as settings


def get_algorithm_file_name(algorithm_name):
    pattern = re.compile(r"\s+")
    string_without_whitespace = pattern.sub("", algorithm_name)
    return string_without_whitespace


def write_file(path, file_name, body):
    if not os.path.exists(path):
        print("Creating docker dir")
        os.makedirs(path)
    new_file = open(os.path.join(path, file_name), 'w')
    new_file.write(body)
    new_file.close()


def create_hysds_io(algorithm_description, algorithm_params, submission_type="individual"):

    hysds_io = dict()
    hysds_io["label"] = algorithm_description
    hysds_io["submission_type"] = submission_type
    params = list()

    for param in algorithm_params:
        param_spec = dict()
        param_spec["name"] = param
        param_spec["from"] = "value"
        param_spec["value"] = algorithm_params[param]
        params.append(param_spec)
    hysds_io["params"] = params
    return hysds_io


def create_job_spec(script_command, algorithm_params):
    job_spec = dict()
    job_spec["command"] = script_command
    job_spec["disk_usage"] = "10GB"
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["recommended-queues"] = ["factotum-job_worker-small"]
    params = list()
    for param in algorithm_params:
        param_spec = dict()
        param_spec["name"] = param
        param_spec["destination"] = "positional"
        params.append(param_spec)
    job_spec["params"] = params

    return job_spec


def write_spec_file(spec_type, algorithm, body, repo_name=settings.REPO_NAME):
    path = "{}/{}/docker/".format(settings.REPO_PATH, repo_name)
    file_name = "{}.json.{}".format(spec_type, get_algorithm_file_name(algorithm))
    write_file(path, file_name, json.dumps(body))


def create_config_file(docker_container_url):
    return docker_container_url


def get_job_submission_json(algorithm, algorithm_params):
    # if type(algorithm)is list:
    #     job_list = list()
    #     for algo in algorithm:
    #         job_list.append("job-{}:{}".format(get_algorithm_file_name(algo), settings.VERSION))
    #     return ",".join(job_list)
    # else:
    #     return "job-{}:{}".format(algorithm, settings.VERSION)

    submission_paload = dict()
    submission_paload["job_type"] = "job-{}:{}".format(algorithm, settings.VERSION)
    submission_paload["params"] = algorithm_params

    return json.dumps(submission_paload)



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
