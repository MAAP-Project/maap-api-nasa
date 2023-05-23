from enum import Enum


class Environments(Enum):
    """Enumeration of our environments"""
    DIT = { 'cname': 'DIT', 'label': 'DIT' }
    UAT = { 'cname': 'UAT', 'label': 'UAT' }
    OLD_OPS = { 'cname': 'OPS', 'label': 'Old OPS' }
    NEW_OPS = { 'cname': '', 'label': 'New OPS' }


def get_environment(base_url):
    """
    Returns an enumeration value associated with the environment
    that the code is being executing within.
    """
    
    env = Environments.NEW_OPS

    if "0.0.0.0" in base_url or "127.0.0.1" in base_url or "LOCALHOST" in base_url.upper():
        env = Environments.DIT
    elif Environments.DIT.value['cname'] in base_url.upper():
        env = Environments.DIT
    elif Environments.UAT.value['cname'] in base_url.upper():
        env = Environments.UAT
    elif Environments.OLD_OPS.value['cname'] in base_url.upper():
        env = Environments.OLD_OPS

    return env
