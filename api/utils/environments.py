from enum import Enum


class Environments(Enum):
    DIT = 'DIT'
    UAT = 'UAT'
    OPS = 'OPS'


def get_environment(base_url):

    env = Environments.OPS

    if "0.0.0.0" in base_url or "127.0.0.1" in base_url or "LOCALHOST" in base_url.upper():
        env = Environments.DIT
    elif Environments.DIT.value in base_url.upper():
        env = Environments.DIT
    elif Environments.UAT.value in base_url.upper():
        env = Environments.UAT
    elif Environments.OPS.value in base_url.upper():
        env = Environments.OPS

    return env
