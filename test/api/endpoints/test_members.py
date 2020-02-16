import unittest
from api.maapapp import app
from api.maap_database import db
from api.models.member import Member
from api.models.member_session import MemberSession
import os

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True


class MembersCase(unittest.TestCase):

    # Setup
    def setUp(self):
        with app.app_context():
            db.create_all()

    # Tests
    def test_create_member(self):
        with app.app_context():
            guest = Member(first_name="testFirst",
                           last_name="testLast",
                           username="testUsername",
                           email="test@test.com",
                           organization="NASA")
            db.session.add(guest)
            db.session.commit()

            members = Member.query.all()

            self.assertTrue(members is not None)

    def test_create_member_session(self):
        with app.app_context():
            guest = Member.query.first()

            guest_session = MemberSession(member_id=guest.id, session_key="test_key")
            db.session.add(guest_session)
            db.session.commit()

            session = MemberSession.query.first()
            session_member = session.member

            self.assertTrue(session is not None)
            self.assertTrue(session_member is not None)


