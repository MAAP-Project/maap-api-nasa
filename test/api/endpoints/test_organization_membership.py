import json
import datetime
import unittest
from unittest.mock import patch, MagicMock

from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.role import Role
from api.models.organization import Organization
from api.models.organization_membership import OrganizationMembership
from api import constants


class TestOrganizationMembershipUpdate(unittest.TestCase):
    """PUT /api/organizations/<org_id>/membership/<username> — surgical update of
    a single membership's job-limit override / maintainer flag."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with app.app_context():
            initialize_sql(db.engine)
            for role_id, name in [(Role.ROLE_GUEST, 'GUEST'),
                                  (Role.ROLE_MEMBER, 'MEMBER'),
                                  (Role.ROLE_ADMIN, 'ADMIN')]:
                if not db.session.query(Role).get(role_id):
                    db.session.add(Role(id=role_id, role_name=name))
            db.session.commit()

    def setUp(self):
        with app.app_context():
            self._clear()
            self.admin = Member(username='admin1', email='admin1@nasa.gov',
                                first_name='Ada', last_name='Min',
                                role_id=Role.ROLE_ADMIN, status=constants.STATUS_ACTIVE,
                                creation_date=datetime.datetime.utcnow())
            self.target = Member(username='joeuser', email='joe@example.org',
                                 first_name='Joe', last_name='User',
                                 role_id=Role.ROLE_GUEST, status=constants.STATUS_ACTIVE,
                                 creation_date=datetime.datetime.utcnow())
            db.session.add_all([self.admin, self.target])
            db.session.commit()
            self.org = Organization(name='GEDI', parent_org_id=None,
                                    default_job_limit_count=2, default_job_limit_hours=1,
                                    creation_date=datetime.datetime.utcnow())
            db.session.add(self.org)
            db.session.commit()
            self.org_id = self.org.id
            # Target starts as a member inheriting the org default (null override).
            db.session.add(OrganizationMembership(org_id=self.org_id, member_id=self.target.id,
                                                  org_maintainer=False, job_limit_count=None,
                                                  job_limit_hours=None,
                                                  creation_date=datetime.datetime.utcnow()))
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            self._clear()

    @staticmethod
    def _clear():
        db.session.query(OrganizationMembership).delete()
        db.session.query(Member).delete()
        db.session.query(Organization).delete()
        db.session.commit()

    def _session(self, username):
        m = db.session.query(Member).filter_by(username=username).first()
        return MagicMock(member=m)

    def _put(self, payload, username='joeuser', acting='admin1'):
        with app.app_context():
            with patch('api.auth.security.validate_proxy', return_value=self._session(acting)):
                return self.client.put(
                    '/api/organizations/{}/membership/{}'.format(self.org_id, username),
                    headers={'proxy-ticket': 'test-ticket'},
                    data=json.dumps(payload),
                    content_type='application/json')

    def _membership(self):
        with app.app_context():
            t = db.session.query(Member).filter_by(username='joeuser').first()
            return db.session.query(OrganizationMembership).filter_by(
                member_id=t.id, org_id=self.org_id).first()

    def test_admin_sets_job_limit_override(self):
        resp = self._put({'job_limit_count': 5, 'job_limit_hours': 24})
        self.assertEqual(resp.status_code, 200)
        m = self._membership()
        self.assertEqual(m.job_limit_count, 5)
        self.assertEqual(m.job_limit_hours, 24)

    def test_null_reverts_to_org_default(self):
        self._put({'job_limit_count': 5, 'job_limit_hours': 24})
        resp = self._put({'job_limit_count': None, 'job_limit_hours': None})
        self.assertEqual(resp.status_code, 200)
        m = self._membership()
        self.assertIsNone(m.job_limit_count)
        self.assertIsNone(m.job_limit_hours)

    def test_absent_keys_are_left_untouched(self):
        self._put({'job_limit_count': 5, 'job_limit_hours': 24})
        # Only maintainer sent — job limit must remain.
        resp = self._put({'org_maintainer': True})
        self.assertEqual(resp.status_code, 200)
        m = self._membership()
        self.assertEqual(m.job_limit_count, 5)
        self.assertEqual(m.job_limit_hours, 24)
        self.assertTrue(m.org_maintainer)

    def test_missing_membership_is_rejected(self):
        resp = self._put({'job_limit_count': 5}, username='ghostuser')
        # Non-2xx (err_response returns a 400-style body).
        self.assertNotEqual(resp.status_code, 200)

    def test_non_admin_non_maintainer_forbidden(self):
        # A plain member acting on the target's membership is not authorized.
        resp = self._put({'job_limit_count': 5}, acting='joeuser')
        self.assertEqual(resp.status_code, 403)


if __name__ == '__main__':
    unittest.main()
