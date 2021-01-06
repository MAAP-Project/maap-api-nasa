from git import Repo
import os
import shutil
from string import Template
import time
import api.settings as settings


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
    commit_message = 'Registering algorithm: {}'.format(algorithm_name)
    repo.index.add(file_list)
    repo.index.commit(commit_message)
    origin = repo.remote('origin')
    origin.push()
    # head = repo.commits()[0]
    # commit_hash = head.id
    # commit_time = time.strftime("%a, %d %b %Y %H:%M", head.committed_date)
    # commit_message = head.message
    # print("Commit Hash: {} made at {} for {}".format(commit_hash, commit_time, commit_message))
    # return commit_hash
    return


def clean_up_git_repo(repo, repo_name):
    files_list = os.listdir(os.path.join(settings.REPO_PATH, repo_name, "docker"))
    for file in files_list:
        if file != "Dockerfile":
            print("Removing file : {}".format(file))
            os.remove('{}/{}/docker/{}'.format(settings.REPO_PATH, repo_name, file))
            repo.index.remove(['{}/{}/docker/{}'.format(settings.REPO_PATH, repo_name, file)])
    return repo
