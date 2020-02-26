import unittest
from api.maapapp import app
from api.maap_database import db
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.member_cmr_collection import MemberCmrCollection
from api.models.member_cmr_granule import MemberCmrGranule
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

    def test_create_member_cmr_collection(self):
        with app.app_context():
            guest = Member.query.first()

            collection = MemberCmrCollection(member_id=guest.id, collection_id="testid", collection_short_name="testname")
            db.session.add(collection)
            db.session.commit()

            new_collection = MemberCmrCollection.query.first()
            session_member = new_collection.member

            self.assertTrue(new_collection is not None)
            self.assertTrue(session_member is not None)

    def test_create_member_cmr_granule(self):
        with app.app_context():
            coll = MemberCmrCollection.query.first()

            granule = MemberCmrGranule(collection_id=coll.id, granule_ur="testgranur")
            db.session.add(granule)
            db.session.commit()

            new_granule = MemberCmrGranule.query.first()
            session_member = new_granule.collection.member
            ref_collection = new_granule.collection

            self.assertTrue(new_granule is not None)
            self.assertTrue(ref_collection is not None)
            self.assertTrue(session_member is not None)


