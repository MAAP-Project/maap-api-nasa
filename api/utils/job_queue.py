import logging
from collections import namedtuple
import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from api.maap_database import db

log = logging.getLogger(__name__)


def get_user_queues(user_id):

    try:
        user_queues = []
        query = """select jq.queue_name from organization_membership m
                        inner join public.organization_job_queue ojq on m.org_id = ojq.org_id
                        inner join public.job_queue jq on jq.id = ojq.job_queue_id
                    where m.member_id = {}
                    union
                    select queue_name
                    from job_queue
                    where guest_tier = true""".format(user_id)
        queue_list = db.session.execute(sqlalchemy.text(query))

        Record = namedtuple('Record', queue_list.keys())
        queue_records = [Record(*r) for r in queue_list.fetchall()]

        for r in queue_records:
            user_queues.append(r.queue_name)

        return user_queues

    except SQLAlchemyError as ex:
        raise ex
    except:
        raise Exception("Couldn't get list of available queues")
