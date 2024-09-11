import json
import logging
from collections import namedtuple
from datetime import datetime

import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from api.maap_database import db
from api.models import job_queue
from api.models.job_queue import JobQueue
from api.models.organization import Organization
from api.models.organization_job_queue import OrganizationJobQueue
import api.utils.hysds_util as hysds
from api.schemas.job_queue_schema import JobQueueSchema
from api import settings

log = logging.getLogger(__name__)


def get_user_queues(user_id):
    try:
        user_queues = []
        query = """select jq.id, jq.queue_name, jq.is_default, jq.time_limit_minutes from organization_membership m
                        inner join public.organization_job_queue ojq on m.org_id = ojq.org_id
                        inner join public.job_queue jq on jq.id = ojq.job_queue_id
                    where m.member_id = {}
                    union
                    select id, queue_name, is_default, time_limit_minutes
                    from job_queue
                    where guest_tier = true""".format(user_id)
        queue_list = db.session.execute(sqlalchemy.text(query))

        Record = namedtuple('Record', queue_list.keys())
        queue_records = [Record(*r) for r in queue_list.fetchall()]

        for r in queue_records:
            user_queues.append(JobQueue(id=r.id, queue_name=r.queue_name, is_default=r.is_default, time_limit_minutes=r.time_limit_minutes))

        return user_queues

    except SQLAlchemyError as ex:
        raise ex


def get_all_queues():
    try:
        result = []

        queues = db.session.query(
            JobQueue.id,
            JobQueue.queue_name,
            JobQueue.queue_description,
            JobQueue.guest_tier,
            JobQueue.creation_date
        ).order_by(JobQueue.queue_name).all()

        orgs_query = db.session.query(
            Organization, OrganizationJobQueue,
        ).filter(
            Organization.id == OrganizationJobQueue.org_id
        ).order_by(Organization.name).all()

        hysds_queues = hysds.get_mozart_queues()

        for q in queues:
            queue = {
                'id': q.id,
                'queue_name': q.queue_name,
                'queue_description': q.queue_description,
                'guest_tier': q.guest_tier,
                'status': 'Online' if q.queue_name in hysds_queues else 'Offline',
                'orgs': [],
                'creation_date': q.creation_date.strftime('%m/%d/%Y'),
            }

            for o in orgs_query:
                if o.OrganizationJobQueue.job_queue_id == q.id:
                    queue['orgs'].append({
                        'id': o.Organization.id,
                        'org_name': o.Organization.name,
                        'default_job_limit_count': o.Organization.default_job_limit_count,
                        'default_job_limit_hours': o.Organization.default_job_limit_hours
                    })

            result.append(queue)

        unassigned_queues = (hq for hq in hysds_queues if hq not in map(_queue_name, queues))
        for uq in unassigned_queues:
            result.append({
                'id': 0,
                'queue_name': uq,
                'queue_description': '',
                'guest_tier': False,
                'status': 'Unassigned',
                'orgs': [],
                'creation_date': None,
            })

        return result
    except SQLAlchemyError as ex:
        raise ex


def _queue_name(q):
    return q.queue_name


def create_queue(queue_name, queue_description, guest_tier, orgs):
    try:
        new_queue = JobQueue(queue_name=queue_name, queue_description=queue_description, guest_tier=guest_tier,
                             creation_date=datetime.utcnow())

        db.session.add(new_queue)
        db.session.commit()

        queue_orgs = []
        for queue_org in orgs:
            queue_orgs.append(OrganizationJobQueue(org_id=queue_org['org_id'], job_queue_id=new_queue.id,
                                                   creation_date=datetime.utcnow()))

        if len(queue_orgs) > 0:
            db.session.add_all(queue_orgs)
            db.session.commit()

        org_schema = JobQueueSchema()
        return json.loads(org_schema.dumps(new_queue))

    except SQLAlchemyError as ex:
        raise ex


def update_queue(queue, orgs):
    try:
        # Update queue
        db.session.commit()

        # Update org assignments
        db.session.execute(
            db.delete(OrganizationJobQueue).filter_by(job_queue_id=queue.id)
        )
        db.session.commit()

        queue_orgs = []
        for queue_org in orgs:
            queue_orgs.append(
                OrganizationJobQueue(org_id=queue_org['org_id'], job_queue_id=queue.id,
                                     creation_date=datetime.utcnow()))

        if len(queue_orgs) > 0:
            db.session.add_all(queue_orgs)
            db.session.commit()

        queue_schema = JobQueueSchema()
        return json.loads(queue_schema.dumps(queue))

    except SQLAlchemyError as ex:
        raise ex


def delete_queue(queue_id):
    try:
        # Clear orgs
        db.session.execute(
            db.delete(OrganizationJobQueue).filter_by(job_queue_id=queue_id)
        )
        db.session.commit()

        db.session.query(JobQueue).filter_by(id=queue_id).delete()
        db.session.commit()
    except SQLAlchemyError as ex:
        raise ex


def get_default_queue():
    try:
        default_queue = db.session \
            .query(JobQueue) \
            .filter_by(is_default=True) \
            .first()
        return default_queue

    except SQLAlchemyError as ex:
        raise ex


def validate_or_get_queue(queue: str, job_type: str, user_id: int):
    f"""
    Validates if the queue name provided is valid and exists if not raises HTTP 400
    If no queue name is provided, it will default to the default job queue.
    :param queue: Queue name
    :param job_type: Job type
    :param user_id: User id to look up available queues
    :return: queue
    :raises ValueError: If the queue name provided is not valid
    """
    valid_queues = get_user_queues(user_id)

    if queue is None or queue == "":
        if job_type is None:
            default_queue = next(q for q in valid_queues if q.is_default)
            return default_queue
        recommended_queue = hysds.get_recommended_queue(job_type)
        queue = next(q for q in valid_queues if q.queue_name == recommended_queue)

    valid_queue_names = list(map(lambda q: q.queue_name, valid_queues))
    if queue not in valid_queue_names:
        raise ValueError(f"User does not have access to {queue}. Valid queues: {valid_queue_names}")

    return next(q for q in valid_queues if q.queue_name == queue)

def contains_time_limit(queue: job_queue):
    return queue is not None and queue.time_limit_minutes is not None and queue.time_limit_minutes > 0
