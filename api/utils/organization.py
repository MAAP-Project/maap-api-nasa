import logging
from collections import namedtuple
from datetime import datetime
import json
import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from api.maap_database import db
from api.models.job_queue import JobQueue
from api.models.member import Member
from api.models.organization import Organization
from api.models.organization_job_queue import OrganizationJobQueue
from api.models.organization_membership import OrganizationMembership
from api.schemas.organization_schema import OrganizationSchema

log = logging.getLogger(__name__)


def get_organizations():
    try:
        result = []
        otree = db.session.execute(sqlalchemy.text('select * from org_tree order by row_number'))

        queues_query = db.session.query(
            JobQueue, OrganizationJobQueue,
        ).filter(
            JobQueue.id == OrganizationJobQueue.job_queue_id
        ).order_by(JobQueue.queue_name).all()

        membership_query = db.session.query(
            Member, OrganizationMembership,
        ).filter(
            Member.id == OrganizationMembership.member_id
        ).order_by(Member.first_name).all()

        Record = namedtuple('Record', otree.keys())
        org_tree_records = [Record(*r) for r in otree.fetchall()]
        for r in org_tree_records:
            org = {
                'id': r.id,
                'parent_org_id': r.parent_org_id,
                'name': r.name,
                'depth': r.depth,
                'member_count': r.member_count,
                'default_job_limit_count': r.default_job_limit_count,
                'default_job_limit_hours': r.default_job_limit_hours,
                'job_queues': [],
                'members': [],
                'creation_date': r.creation_date.strftime('%m/%d/%Y'),
            }

            for q in queues_query:
                if q.OrganizationJobQueue.org_id == r.id:
                    org['job_queues'].append({
                        'id': q.JobQueue.id,
                        'queue_name': q.JobQueue.queue_name,
                        'queue_description': q.JobQueue.queue_description
                    })

            for m in membership_query:
                if m.OrganizationMembership.org_id == r.id:
                    org['members'].append({
                        'id': m.Member.id,
                        'first_name': m.Member.first_name,
                        'last_name': m.Member.last_name,
                        'username': m.Member.username,
                        'email': m.Member.email,
                        'maintainer': m.OrganizationMembership.org_maintainer
                    })

            result.append(org)

        return result
    except SQLAlchemyError as ex:
        raise ex

def get_member_organizations(member_id):
    result = []

    user_orgs = db.session \
        .query(Organization, OrganizationMembership) \
        .filter(Organization.id == OrganizationMembership.org_id) \
        .order_by(Organization.name).all()

    for user_org in user_orgs:
        if user_org.OrganizationMembership.member_id == member_id:
            result.append({
                'id': user_org.Organization.id,
                'name': user_org.Organization.name
            })

    return result

def get_organization(org_id):
    try:
        org = db.session \
            .query(Organization) \
            .filter_by(id=org_id) \
            .first()
        return org

    except SQLAlchemyError as ex:
        raise ex

def create_organization(name, parent_org_id, default_job_limit_count, default_job_limit_hours, members):

    try:
        new_org = Organization(name=name, parent_org_id=parent_org_id, default_job_limit_count=default_job_limit_count,
                               default_job_limit_hours=default_job_limit_hours, creation_date=datetime.utcnow())

        db.session.add(new_org)
        db.session.commit()

        org_members = []
        for org_member in members:
            org_members.append(OrganizationMembership(member_id=org_member['member_id'], org_id=new_org.id,
                                                      org_maintainer=org_member['maintainer'],
                                                      creation_date=datetime.utcnow()))

        if len(org_members) > 0:
            db.session.add_all(org_members)
            db.session.commit()

        org_schema = OrganizationSchema()
        return json.loads(org_schema.dumps(new_org))

    except SQLAlchemyError as ex:
        raise ex

def update_organization(org, members):

    try:
        # Update org
        db.session.commit()

        # Update membership
        db.session.execute(
            db.delete(OrganizationMembership).filter_by(org_id=org.id)
        )
        db.session.commit()

        org_members = []
        for org_member in members:
            org_members.append(OrganizationMembership(
                member_id=org_member['member_id'],
                org_id=org.id,
                org_maintainer=org_member['maintainer'],
                creation_date=datetime.utcnow()))

        if len(org_members) > 0:
            db.session.add_all(org_members)
            db.session.commit()

        org_schema = OrganizationSchema()
        return json.loads(org_schema.dumps(org))

    except SQLAlchemyError as ex:
        raise ex

def delete_organization(org_id):
    try:

        # Clear membership
        db.session.execute(
            db.delete(OrganizationMembership).filter_by(org_id=org_id)
        )
        db.session.commit()

        # Clear job queues
        db.session.execute(
            db.delete(OrganizationJobQueue).filter_by(org_id=org_id)
        )
        db.session.commit()

        db.session.query(Organization).filter_by(id=org_id).delete()
        db.session.commit()

    except SQLAlchemyError as ex:
        raise ex
