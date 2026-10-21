import json
import datetime
import unittest
from unittest.mock import patch, MagicMock

from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.role import Role
from api.models.member_log import MemberLog
from api.models.member_log_change import MemberLogChange
from api.models.organization import Organization
from api.models.organization_membership import OrganizationMembership
from api.utils.member_log_util import seed_member_log_changes
from api import constants


class TestMemberReview(unittest.TestCase):
    """POST /api/members/<key>/review — consolidated admin update with audit log."""

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
            seed_member_log_changes()

    def setUp(self):
        with app.app_context():
            self._clear()
            # Acting admin + target member
            self.admin = Member(username='admin1', email='admin1@nasa.gov',
                                first_name='Ada', last_name='Min',
                                role_id=Role.ROLE_ADMIN, status=constants.STATUS_ACTIVE,
                                creation_date=datetime.datetime.utcnow())
            self.target = Member(username='joeuser', email='joe@example.org',
                                 first_name='Joe', last_name='User',
                                 role_id=Role.ROLE_GUEST, status=constants.STATUS_PENDING,
                                 creation_date=datetime.datetime.utcnow())
            db.session.add_all([self.admin, self.target])
            db.session.commit()
            self.admin_id = self.admin.id

    def tearDown(self):
        with app.app_context():
            self._clear()

    @staticmethod
    def _clear():
        db.session.query(MemberLog).delete()
        db.session.query(OrganizationMembership).delete()
        db.session.query(Member).delete()
        db.session.query(Organization).delete()
        db.session.commit()

    def _admin_session(self):
        """A mocked proxy session whose member is the admin — satisfies both
        login_required(role=ADMIN) and the endpoint's get_authorized_user()."""
        admin = db.session.query(Member).filter_by(username='admin1').first()
        return MagicMock(member=admin)

    def _member_session(self):
        member = db.session.query(Member).filter_by(username='joeuser').first()
        return MagicMock(member=member)

    def _review(self, payload, session_factory=None):
        with app.app_context():
            factory = session_factory or self._admin_session
            with patch('api.auth.security.validate_proxy', return_value=factory()):
                return self.client.post(
                    '/api/members/joeuser/review',
                    headers={'proxy-ticket': 'test-ticket'},
                    data=json.dumps(payload),
                    content_type='application/json')

    def _logs(self):
        with app.app_context():
            change = {c.id: c.change_type for c in db.session.query(MemberLogChange).all()}
            return [{
                'type': change.get(l.member_log_change_id),
                'old': l.old_value, 'new': l.new_value,
                'comment': l.comment, 'admin_id': l.admin_id,
            } for l in db.session.query(MemberLog).order_by(MemberLog.id).all()]

    # --- status ---
    def test_status_change_records_log(self):
        resp = self._review({'status': 'active', 'comment': 'Approved'})
        self.assertEqual(resp.status_code, 200)
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertEqual(m.status, constants.STATUS_ACTIVE)
        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['type'], 'Status')
        self.assertEqual(logs[0]['old'], 'pending')
        self.assertEqual(logs[0]['new'], 'active')
        self.assertEqual(logs[0]['comment'], 'Approved')
        self.assertEqual(logs[0]['admin_id'], self.admin_id)

    def test_legacy_suspended_maps_to_inactive(self):
        resp = self._review({'status': 'suspended'})
        self.assertEqual(resp.status_code, 200)
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertEqual(m.status, constants.STATUS_INACTIVE)
        self.assertEqual(self._logs()[0]['new'], 'inactive')

    # --- role: old/new are role NAMES (read from the shared role table, whose
    # exact casing is owned by whichever test class seeds it first) ---
    def test_role_change_records_role_names(self):
        with app.app_context():
            guest_name = db.session.query(Role).get(Role.ROLE_GUEST).role_name
            member_name = db.session.query(Role).get(Role.ROLE_MEMBER).role_name
        resp = self._review({'role_id': Role.ROLE_MEMBER})
        self.assertEqual(resp.status_code, 200)
        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['type'], 'Role')
        self.assertEqual(logs[0]['old'], guest_name)
        self.assertEqual(logs[0]['new'], member_name)

    # --- orgs: old/new are CSV of org names ---
    def test_org_change_records_csv(self):
        with app.app_context():
            db.session.add_all([
                Organization(id=1, name='AOS'),
                Organization(id=2, name='CUNY'),
            ])
            db.session.commit()

        resp = self._review({'organization_ids': [1, 2]})
        self.assertEqual(resp.status_code, 200)
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            org_ids = {r.org_id for r in db.session.query(OrganizationMembership)
                       .filter_by(member_id=m.id).all()}
            self.assertEqual(org_ids, {1, 2})
        logs = self._logs()
        self.assertEqual(logs[0]['type'], 'Org')
        self.assertEqual(logs[0]['old'], '')
        self.assertEqual(logs[0]['new'], 'AOS, CUNY')

    def test_multiple_changes_share_one_comment(self):
        with app.app_context():
            db.session.add(Organization(id=1, name='AOS'))
            db.session.commit()
        resp = self._review({'status': 'active', 'role_id': Role.ROLE_MEMBER,
                             'organization_ids': [1], 'comment': 'full approval'})
        self.assertEqual(resp.status_code, 200)
        logs = self._logs()
        self.assertEqual({l['type'] for l in logs}, {'Status', 'Role', 'Org'})
        self.assertTrue(all(l['comment'] == 'full approval' for l in logs))

    # --- onboarding flags: audited as Yes/No ---
    def test_onboarding_flags_recorded(self):
        resp = self._review({'invited_to_slack': True, 'added_to_mailing_list': True,
                            'comment': 'onboarded'})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertTrue(body['invited_to_slack'])
        self.assertTrue(body['added_to_mailing_list'])
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertTrue(m.invited_to_slack)
            self.assertTrue(m.added_to_mailing_list)
        logs = self._logs()
        self.assertEqual({l['type'] for l in logs}, {'Slack Invite', 'Mailing List'})
        self.assertTrue(all(l['old'] == 'No' and l['new'] == 'Yes' for l in logs))

    def test_onboarding_flag_unchanged_writes_no_log(self):
        self._review({'invited_to_slack': True})
        # setting it True again is a no-op
        self._review({'invited_to_slack': True})
        slack_logs = [l for l in self._logs() if l['type'] == 'Slack Invite']
        self.assertEqual(len(slack_logs), 1)

    # --- welcome email (admin-triggered; sent after the other changes commit) ---
    @patch('api.endpoints.members.send_welcome_email')
    def test_send_welcome_email_sends_flips_slack_and_logs(self, mock_send):
        resp = self._review({'send_welcome_email': True, 'comment': 'welcome'})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertTrue(body['welcome_email_sent'])
        self.assertIsNone(body['welcome_email_error'])
        self.assertTrue(body['invited_to_slack'])
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[0][0].username, 'joeuser')
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertTrue(m.invited_to_slack)
        logs = self._logs()
        self.assertEqual({l['type'] for l in logs}, {'Welcome Email', 'Slack Invite'})
        welcome = next(l for l in logs if l['type'] == 'Welcome Email')
        self.assertEqual(welcome['new'], 'Sent to joe@example.org')
        self.assertEqual(welcome['comment'], 'welcome')
        self.assertEqual(welcome['admin_id'], self.admin_id)

    @patch('api.endpoints.members.send_welcome_email')
    def test_send_welcome_email_already_invited_logs_email_only(self, mock_send):
        self._review({'invited_to_slack': True})
        resp = self._review({'send_welcome_email': True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([l['type'] for l in self._logs()], ['Slack Invite', 'Welcome Email'])

    @patch('api.endpoints.members.send_welcome_email', side_effect=RuntimeError('smtp down'))
    def test_send_welcome_email_failure_is_reported_not_raised(self, mock_send):
        resp = self._review({'status': 'active', 'send_welcome_email': True})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertFalse(body['welcome_email_sent'])
        self.assertIn('smtp down', body['welcome_email_error'])
        self.assertFalse(body['invited_to_slack'])
        # The status change still landed and was audited; the email was not.
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertEqual(m.status, constants.STATUS_ACTIVE)
            self.assertFalse(m.invited_to_slack)
        self.assertEqual([l['type'] for l in self._logs()], ['Status'])

    @patch('api.endpoints.members.send_welcome_email')
    def test_send_welcome_email_requires_member_email(self, mock_send):
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            m.email = None
            db.session.commit()
        resp = self._review({'status': 'active', 'send_welcome_email': True})
        self.assertEqual(resp.status_code, 400)
        mock_send.assert_not_called()
        # Rejected up front: nothing else in the request was applied.
        with app.app_context():
            m = db.session.query(Member).filter_by(username='joeuser').first()
            self.assertEqual(m.status, constants.STATUS_PENDING)
        self.assertEqual(self._logs(), [])

    @patch('api.endpoints.members.send_welcome_email')
    def test_send_welcome_email_false_is_noop(self, mock_send):
        resp = self._review({'send_welcome_email': False})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertNotIn('welcome_email_sent', body)
        mock_send.assert_not_called()
        self.assertEqual(self._logs(), [])

    def test_no_change_writes_no_log(self):
        # target is already pending/guest with no orgs
        resp = self._review({'status': 'pending', 'role_id': Role.ROLE_GUEST,
                             'organization_ids': []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._logs(), [])

    def test_requires_admin(self):
        resp = self._review({'status': 'active'}, session_factory=self._member_session)
        self.assertIn(resp.status_code, (401, 403))
        self.assertEqual(self._logs(), [])

    def test_log_endpoint_returns_history(self):
        self._review({'status': 'active', 'comment': 'approved'})
        self._review({'role_id': Role.ROLE_MEMBER, 'comment': 'promoted'})
        with app.app_context():
            with patch('api.auth.security.validate_proxy', return_value=self._admin_session()):
                resp = self.client.get('/api/members/joeuser/log',
                                       headers={'proxy-ticket': 'test-ticket'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(len(data), 2)
        # newest first
        self.assertEqual(data[0]['change_type'], 'Role')
        self.assertEqual(data[0]['admin_username'], 'admin1')
        self.assertEqual(data[1]['change_type'], 'Status')


if __name__ == '__main__':
    unittest.main()
