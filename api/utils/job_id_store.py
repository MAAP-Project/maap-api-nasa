import logging


log = logging.getLogger(__name__)

job_id_store = dict()


def add_record(local_id, mozart_id):
    """
    Add an item to the store
    :param local_id:
    :param mozart_id:
    :return:
    """
    job_id_store[local_id] = mozart_id
    print("Added record {}:{}".format(local_id, mozart_id))
    log.info("Added record {}:{}".format(local_id, mozart_id))
    return


def get_mozart_id(local_id):
    """
    Retrieve Mozart ID
    :param local_id:
    :return:
    """
    if local_id in job_id_store:
        return job_id_store[local_id]
    else:
        raise Exception("Couldn't find {} in store".format(local_id))
