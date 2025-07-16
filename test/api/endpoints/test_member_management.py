import unittest
import datetime
from unittest.mock import patch
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.member_algorithm import MemberAlgorithm
from api.models.role import Role


class TestMemberManagement(unittest.TestCase):
    """Test suite for member management functionality."""

    def setUp(self):
        """Set up test environment before each test."""
        with app.app_context():
            initialize_sql(db.engine)
            # Clear any existing test data
            db.session.query(MemberAlgorithm).delete()
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()
            
            # Create required roles
            self._create_roles()

    def tearDown(self):
        """Clean up after each test."""
        with app.app_context():
            db.session.query(MemberAlgorithm).delete()
            db.session.query(MemberSession).delete()
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()

    def _create_roles(self):
        """Create required role records for testing."""
        roles = [
            Role(id=Role.ROLE_GUEST, role_name='guest'),
            Role(id=Role.ROLE_MEMBER, role_name='member'),
            Role(id=Role.ROLE_ADMIN, role_name='admin')
        ]
        for role in roles:
            db.session.add(role)
        db.session.commit()

    def _create_sample_member(self, **kwargs):
        """Create a sample member with default values, allowing overrides."""
        defaults = {
            'username': 'testuser',
            'email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'organization': 'NASA',
            'role_id': Role.ROLE_MEMBER,
            'public_ssh_key': 'ssh-rsa AAAAB3NzaC1yc2ETEST...',
            'creation_date': datetime.datetime.utcnow()
        }
        defaults.update(kwargs)
        return Member(**defaults)

    def test_new_member_can_be_created_successfully(self):
        """Test: New member can be created successfully"""
        with app.app_context():
            # Given valid member information
            member = self._create_sample_member()
            
            # When a new member is created
            db.session.add(member)
            db.session.commit()
            
            # Then the member should be saved to the database
            saved_member = db.session.query(Member).filter_by(username='testuser').first()
            self.assertIsNotNone(saved_member)
            self.assertEqual(saved_member.email, 'test@example.com')
            self.assertEqual(saved_member.first_name, 'Test')
            self.assertEqual(saved_member.last_name, 'User')
            self.assertEqual(saved_member.organization, 'NASA')
            self.assertEqual(saved_member.role_id, Role.ROLE_MEMBER)

    def test_member_information_can_be_updated(self):
        """Test: Member information can be updated"""
        with app.app_context():
            # Given an existing member
            member = self._create_sample_member()
            db.session.add(member)
            db.session.commit()
            
            # When their organization is updated
            member.organization = 'ESA'
            member.public_ssh_key = 'ssh-rsa UPDATED_KEY...'
            db.session.commit()
            
            # Then the changes should be persisted to the database
            updated_member = db.session.query(Member).filter_by(username='testuser').first()
            self.assertEqual(updated_member.organization, 'ESA')
            self.assertEqual(updated_member.public_ssh_key, 'ssh-rsa UPDATED_KEY...')

    def test_member_session_can_be_created_and_linked(self):
        """Test: Member session can be created and linked"""
        with app.app_context():
            # Given an existing member
            member = self._create_sample_member()
            db.session.add(member)
            db.session.commit()
            
            # When a new session is created for that member
            session = MemberSession(
                member_id=member.id,
                session_key='test-session-key-12345',
                creation_date=datetime.datetime.utcnow()
            )
            db.session.add(session)
            db.session.commit()
            
            # Then the session should be linked to the member
            saved_session = db.session.query(MemberSession).filter_by(
                session_key='test-session-key-12345'
            ).first()
            self.assertIsNotNone(saved_session)
            self.assertEqual(saved_session.member.username, 'testuser')
            self.assertEqual(saved_session.member_id, member.id)

    def test_member_algorithms_can_be_associated_with_members(self):
        """Test: Member algorithms can be associated with members"""
        with app.app_context():
            # Given an existing member
            member = self._create_sample_member()
            db.session.add(member)
            db.session.commit()
            
            # When an algorithm is registered to that member
            algorithm = MemberAlgorithm(
                member_id=member.id,
                algorithm_key='test-algo-key-12345',
                is_public=False,
                creation_date=datetime.datetime.utcnow()
            )
            db.session.add(algorithm)
            db.session.commit()
            
            # Then the algorithm should be linked to the member
            saved_algo = db.session.query(MemberAlgorithm).filter_by(
                algorithm_key='test-algo-key-12345'
            ).first()
            self.assertIsNotNone(saved_algo)
            self.assertEqual(saved_algo.member.username, 'testuser')
            self.assertEqual(saved_algo.member_id, member.id)
            self.assertFalse(saved_algo.is_public)

    def test_member_can_have_multiple_sessions(self):
        """Test: Member can have multiple active sessions"""
        with app.app_context():
            # Given an existing member
            member = self._create_sample_member()
            db.session.add(member)
            db.session.commit()
            
            # When multiple sessions are created for that member
            session1 = MemberSession(
                member_id=member.id,
                session_key='session-key-1',
                creation_date=datetime.datetime.utcnow()
            )
            session2 = MemberSession(
                member_id=member.id,
                session_key='session-key-2',
                creation_date=datetime.datetime.utcnow()
            )
            db.session.add(session1)
            db.session.add(session2)
            db.session.commit()
            
            # Then both sessions should be linked to the member
            member_sessions = db.session.query(MemberSession).filter_by(
                member_id=member.id
            ).all()
            self.assertEqual(len(member_sessions), 2)
            session_keys = [s.session_key for s in member_sessions]
            self.assertIn('session-key-1', session_keys)
            self.assertIn('session-key-2', session_keys)

    def test_member_can_have_multiple_algorithms(self):
        """Test: Member can have multiple registered algorithms"""
        with app.app_context():
            # Given an existing member
            member = self._create_sample_member()
            db.session.add(member)
            db.session.commit()
            
            # When multiple algorithms are registered to that member
            algo1 = MemberAlgorithm(
                member_id=member.id,
                algorithm_key='public-algorithm',
                is_public=True,
                creation_date=datetime.datetime.utcnow()
            )
            algo2 = MemberAlgorithm(
                member_id=member.id,
                algorithm_key='private-algorithm',
                is_public=False,
                creation_date=datetime.datetime.utcnow()
            )
            db.session.add(algo1)
            db.session.add(algo2)
            db.session.commit()
            
            # Then both algorithms should be linked to the member
            member_algorithms = db.session.query(MemberAlgorithm).filter_by(
                member_id=member.id
            ).all()
            self.assertEqual(len(member_algorithms), 2)
            
            # And they should have different visibility settings
            public_algo = next(a for a in member_algorithms if a.is_public)
            private_algo = next(a for a in member_algorithms if not a.is_public)
            self.assertEqual(public_algo.algorithm_key, 'public-algorithm')
            self.assertEqual(private_algo.algorithm_key, 'private-algorithm')

    def test_member_unique_constraints_are_enforced(self):
        """Test: Member unique constraints (username, email) are enforced"""
        with app.app_context():
            # Given an existing member
            member1 = self._create_sample_member()
            db.session.add(member1)
            db.session.commit()
            
            # When attempting to create another member with same username
            member2 = self._create_sample_member(
                username='testuser',  # Same username
                email='different@example.com'
            )
            db.session.add(member2)
            
            # Then a database integrity error should occur
            with self.assertRaises(Exception):  # IntegrityError
                db.session.commit()
            
            db.session.rollback()
            
            # When attempting to create another member with same email
            member3 = self._create_sample_member(
                username='differentuser',
                email='test@example.com'  # Same email
            )
            db.session.add(member3)
            
            # Then a database integrity error should occur
            with self.assertRaises(Exception):  # IntegrityError
                db.session.commit()

    def test_member_role_methods_work_correctly(self):
        """Test: Member role checking methods work correctly"""
        with app.app_context():
            # Given members with different roles
            guest_member = self._create_sample_member(
                username='guest',
                email='guest@example.com',
                role_id=Role.ROLE_GUEST
            )
            regular_member = self._create_sample_member(
                username='member',
                email='member@example.com',
                role_id=Role.ROLE_MEMBER
            )
            admin_member = self._create_sample_member(
                username='admin',
                email='admin@example.com',
                role_id=Role.ROLE_ADMIN
            )
            
            db.session.add_all([guest_member, regular_member, admin_member])
            db.session.commit()
            
            # Then role checking methods should return correct values
            self.assertTrue(guest_member.is_guest())
            self.assertFalse(guest_member.is_member())
            self.assertFalse(guest_member.is_admin())
            
            self.assertFalse(regular_member.is_guest())
            self.assertTrue(regular_member.is_member())
            self.assertFalse(regular_member.is_admin())
            
            self.assertFalse(admin_member.is_guest())
            self.assertFalse(admin_member.is_member())
            self.assertTrue(admin_member.is_admin())

    def test_member_display_name_is_generated_correctly(self):
        """Test: Member display name is generated correctly"""
        with app.app_context():
            # Given a member with first and last name
            member = self._create_sample_member(
                first_name='John',
                last_name='Doe'
            )
            db.session.add(member)
            db.session.commit()
            
            # When getting display name
            display_name = member.get_display_name()
            
            # Then it should combine first and last name
            self.assertEqual(display_name, 'John Doe')

    def test_member_with_gitlab_integration_data(self):
        """Test: Member can store GitLab integration data"""
        with app.app_context():
            # Given a member with GitLab data
            member = self._create_sample_member(
                gitlab_id='12345',
                gitlab_username='testuser_gitlab',
                gitlab_token='gitlab_access_token_123'
            )
            db.session.add(member)
            db.session.commit()
            
            # Then GitLab data should be stored correctly
            saved_member = db.session.query(Member).filter_by(username='testuser').first()
            self.assertEqual(saved_member.gitlab_id, '12345')
            self.assertEqual(saved_member.gitlab_username, 'testuser_gitlab')
            self.assertEqual(saved_member.gitlab_token, 'gitlab_access_token_123')

    def test_member_with_urs_token_integration(self):
        """Test: Member can store URS (Earthdata Login) token"""
        with app.app_context():
            # Given a member with URS token
            member = self._create_sample_member(
                urs_token='urs_token_earthdata_12345'
            )
            db.session.add(member)
            db.session.commit()
            
            # Then URS token should be stored correctly
            saved_member = db.session.query(Member).filter_by(username='testuser').first()
            self.assertEqual(saved_member.urs_token, 'urs_token_earthdata_12345')

    def test_member_ssh_key_metadata_is_tracked(self):
        """Test: Member SSH key metadata is properly tracked"""
        with app.app_context():
            # Given a member with SSH key metadata
            ssh_modified_date = datetime.datetime.utcnow()
            member = self._create_sample_member(
                public_ssh_key='ssh-rsa AAAAB3NzaC1yc2ETEST...',
                public_ssh_key_name='my-laptop-key',
                public_ssh_key_modified_date=ssh_modified_date
            )
            db.session.add(member)
            db.session.commit()
            
            # Then SSH key metadata should be stored correctly
            saved_member = db.session.query(Member).filter_by(username='testuser').first()
            self.assertEqual(saved_member.public_ssh_key_name, 'my-laptop-key')
            self.assertEqual(saved_member.public_ssh_key_modified_date, ssh_modified_date)


if __name__ == '__main__':
    unittest.main()