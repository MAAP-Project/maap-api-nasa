from git import Repo
import os
import shutil
import logging
from string import Template
import copy
import time
import api.settings as settings
import requests


def git_clone(repo_url=settings.GIT_REPO_URL, repo_name=settings.REPO_NAME):
    GITLAB_TOKEN = settings.GITLAB_TOKEN
    git_url = Template(repo_url).substitute(TOKEN=GITLAB_TOKEN)
    repo_path = os.path.join(settings.REPO_PATH, repo_name)
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    repo = Repo.clone_from(git_url, repo_path)
    return repo


def update_git_repo(repo, repo_name, algorithm_name):
    file_list = [
        '{}/{}/docker/hysds-io.json.{}'.format(settings.REPO_PATH, repo_name, algorithm_name),
        '{}/{}/docker/job-spec.json.{}'.format(settings.REPO_PATH, repo_name, algorithm_name),
        '{}/{}/config.txt'.format(settings.REPO_PATH, repo_name),
        '{}/{}/code_config.json'.format(settings.REPO_PATH, repo_name),
        '{}/{}/job-submission.json'.format(settings.REPO_PATH, repo_name)
    ]

    try:
        commit_message = 'Registering algorithm: {}'.format(algorithm_name)
        repo.index.add(file_list)
        repo.index.commit(commit_message)
        origin = repo.remote('origin')
        origin.push()
    except Exception as ex:
        raise Exception("Failed to push changes to git.")
    headcommit = repo.head.commit
    commithash = headcommit.hexsha
    return commithash


def clean_up_git_repo(repo, repo_name):
    files_list = os.listdir(os.path.join(settings.REPO_PATH, repo_name, "docker"))
    for file in files_list:
        if file != "Dockerfile":
            print("Removing file : {}".format(file))
            os.remove('{}/{}/docker/{}'.format(settings.REPO_PATH, repo_name, file))
            repo.index.remove(['{}/{}/docker/{}'.format(settings.REPO_PATH, repo_name, file)])
    return repo


def get_git_pipeline_status(project_id, commit_hash):
    """
    Gets Gitlab the commit information and pipeline details given a project id and commit hash
    :param project_id:
    :param commit_hash:
    :return:
    """
    # For Gitlab 12.0
    # auth_headers = {"Authorization": "Bearer {}".format(settings.GITLAB_API_TOKEN)}
    # For Gitlab 14.0 and up
    auth_headers = {"PRIVATE-TOKEN": "{}".format(settings.GITLAB_API_TOKEN)}
    get_commit_url = "{}/{}/repository/commits/{}".format(settings.GIT_API_URL, project_id, commit_hash)
    logging.info("Requesting for commit information: {}".format(get_commit_url))
    last_pipeline = None
    while last_pipeline is None:
        time.sleep(1)
        response = requests.get(get_commit_url, headers=auth_headers)
        response.raise_for_status()
        git_response = copy.deepcopy(response.json())
        logging.info("Response for commit information: {}".format(git_response))
        last_pipeline = response.json().get("last_pipeline")
    pipeline_id = last_pipeline.get("id")
    job_info_url = "{}/{}/pipelines/{}/jobs".format(settings.GIT_API_URL, project_id, pipeline_id)
    logging.info("Requesting for Pipeline Job information: {}".format(job_info_url))
    pipeline_job_info = requests.get(job_info_url, headers=auth_headers)
    pipeline_job_info.raise_for_status()
    logging.info("Response for Pipeline information: {}".format(pipeline_job_info.json()))
    job_web_url = pipeline_job_info.json()[0].get("web_url")
    git_response["job_web_url"] = job_web_url
    git_response["job_log_url"] = "{}/raw".format(job_web_url)
    return git_response