import json
import logging
from collections import namedtuple
from datetime import datetime

import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app as app
from api.maap_database import db
from api.models.organization import Organization
from api.models.organization_s3_access import OrganizationS3Access
from api.schemas.organization_s3_access_schema import OrganizationS3AccessSchema

log = logging.getLogger(__name__)


def get_all_s3_access():
    try:
        result = []

        entries = db.session.query(
            OrganizationS3Access.id,
            OrganizationS3Access.org_id,
            OrganizationS3Access.bucket_name,
            OrganizationS3Access.bucket_prefix,
            OrganizationS3Access.creation_date,
            Organization.name.label('org_name')
        ).join(
            Organization, Organization.id == OrganizationS3Access.org_id
        ).order_by(Organization.name, OrganizationS3Access.bucket_name).all()

        for e in entries:
            result.append({
                'id': e.id,
                'org_id': e.org_id,
                'org_name': e.org_name,
                'bucket_name': e.bucket_name,
                'bucket_prefix': e.bucket_prefix,
                'creation_date': e.creation_date.strftime('%m/%d/%Y') if e.creation_date else None,
            })

        return result
    except SQLAlchemyError as ex:
        raise ex


def get_user_s3_access(user_id):
    try:
        query = """select osa.id, osa.bucket_name, osa.bucket_prefix
                    from organization_membership m
                    inner join organization_s3_access osa on m.org_id = osa.org_id
                    where m.member_id = {}""".format(user_id)
        rows = db.session.execute(sqlalchemy.text(query))

        Record = namedtuple('Record', rows.keys())
        records = [Record(*r) for r in rows.fetchall()]

        result = []
        for r in records:
            result.append({
                'bucket_name': r.bucket_name,
                'bucket_prefix': r.bucket_prefix,
            })

        return result
    except SQLAlchemyError as ex:
        raise ex


def create_s3_access(org_id, bucket_name, bucket_prefix):
    try:
        new_entry = OrganizationS3Access(
            org_id=org_id,
            bucket_name=bucket_name,
            bucket_prefix=bucket_prefix,
            creation_date=datetime.utcnow()
        )

        try:
            db.session.add(new_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to create S3 access entry for org {org_id}: {e}")
            raise

        schema = OrganizationS3AccessSchema()
        return json.loads(schema.dumps(new_entry))

    except SQLAlchemyError as ex:
        raise ex


def update_s3_access(access, org_id, bucket_name, bucket_prefix):
    try:
        if org_id is not None:
            access.org_id = org_id
        if bucket_name is not None:
            access.bucket_name = bucket_name
        if bucket_prefix is not None:
            access.bucket_prefix = bucket_prefix

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to update S3 access entry {access.id}: {e}")
            raise

        schema = OrganizationS3AccessSchema()
        return json.loads(schema.dumps(access))

    except SQLAlchemyError as ex:
        raise ex


def delete_s3_access(access_id):
    try:
        try:
            db.session.query(OrganizationS3Access).filter_by(id=access_id).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to delete S3 access entry {access_id}: {e}")
            raise
    except SQLAlchemyError as ex:
        raise ex
