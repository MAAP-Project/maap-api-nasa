import json
import os
import re
import api.settings as settings

def get_algorithm_file_name (algorithm_name):
    pattern = re.compile(r"\s+")
    string_without_whitespace = pattern.sub("", algorithm_name)
    return string_without_whitespace

def write_file(path, file_name, body):
    if not os.path.exists(path):
        print "Creating docker dir"
        os.makedirs(path)
    file = open(os.path.join(path, file_name), 'wb')
    file.write(body)
    file.close()

def create_hysds_io(algorithm_description, algorithm_params, submission_type = "individual"):

    hysds_io = dict()
    hysds_io["label"] = algorithm_description
    hysds_io["submission_type"] =submission_type
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
    job_spec["command"] =  script_command
    job_spec["disk_usage"] = "10GB"
    job_spec["imported_worker_files"] = {
        "$HOME/.netrc": "/home/ops/.netrc",
        "$HOME/.aws": "/home/ops/.aws",
        "/tmp": ["/tmp", "rw"]
    }
    job_spec["recommended-queues"] = [ "factotum-job_worker-small" ]
    params = list()
    for param in algorithm_params:
        param_spec = dict()
        param_spec["name"] = param
        param_spec["destination"] = "positional"
        params.append(param_spec)
    job_spec["params"] = params

    return job_spec

def write_spec_file(type, algorithm, body, repo_name =  settings.REPO_NAME):
    path = "{}/{}/docker/".format(settings.REPO_PATH, repo_name)
    file_name = "{}.json.{}".format(type, get_algorithm_file_name(algorithm))
    write_file(path, file_name, json.dumps(body))

def create_config_file(docker_container_url):
    return "docker_container_url = {}".format(docker_container_url)

def get_job_types(algorithm):
    if type(algorithm)is list:
        job_list = list()
        for algo in algorithm:
            job_list.append("job-{}:{}".format(get_algorithm_file_name(algo), settings.VERSION))
        return ",".join(job_list)
    else:
        return "job-{}:{}".format(algorithm, settings.VERSION)

