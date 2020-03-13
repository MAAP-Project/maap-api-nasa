import unittest
from api.maapapp import app
from api.maap_database import db
from api.models import DBSession
from api.models.member import Member
from datetime import datetime
from api.models.member_session import MemberSession
# from api.models.member_cmr_collection import MemberCmrCollection
# from api.models.member_cmr_granule import MemberCmrGranule
import os
from api.models import initialize_sql

MOCK_RESPONSES = False if os.environ.get('MOCK_RESPONSES') == 'false' else True


class MembersCase(unittest.TestCase):

    # Setup
    def setUp(self):
        with app.app_context():
            initialize_sql(db.engine)

    # Tests
    def test_create_member(self):
        with app.app_context():
            guest = Member(first_name="testFirst",
                           last_name="testLast",
                           username="testUsername9",
                           email="test9@test.com",
                           organization="NASA",
                           public_ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCzN22QMC8fL4UjwuizV2o52P5mPXBUAnIziUIW77flHBc186aXR13VfaquOqsWKGx51bM8H4PC7yMdoEgKFq2DCx2FeY6BosW3QmnHDc7+Ov3+jDJh8OefBWpaolfGMzgH/te2SswVr2zv1/SSHSLN8L3PQBM6ul/UM4EA0VvXuHz7g+5t5FWDSMjz7LEvafhaxa85r5iV9kICta7F09QAVWr/tugRnQs004fTL/wwak4SICaKh5fXrxU+UyxXfz2QDpKXvvDz1JU7yb4UT6CRz86L3tTK+nWXg7rwSok+H1CchYYEP4/WJTVACJ4iPUQN0RNPCwPekDdpR7kjJnOh brian.p.satorius@jpl.nasa.gov, IMCE Infrastructure Development sd",
                           public_ssh_key_modified_date=datetime.utcnow(),
                           public_ssh_key_name="id_rsa_satorius")

            db.session.add(guest)
            db.session.commit()

            members = db.session.query(Member).all()

            self.assertTrue(members is not None)

            db.session.query(Member).filter(Member.id == guest.id).\
                update({Member.organization: "ESA"})

            db.session.commit()

    def test_create_member_session(self):
        with app.app_context():
            guest = DBSession.query(Member).first()

            guest_session = MemberSession(member_id=guest.id, session_key="test_key")
            db.session.add(guest_session)
            db.session.commit()

            session = DBSession.query(MemberSession).first()
            session_member = session.member

            self.assertTrue(session is not None)
            self.assertTrue(session_member is not None)

    # def test_create_member_cmr_collection(self):
    #     with app.app_context():
    #         guest = Member.query.first()
    #
    #         collection = MemberCmrCollection(member_id=guest.id, collection_id="testid", collection_short_name="testname")
    #         db.session.add(collection)
    #         db.session.commit()
    #
    #         new_collection = MemberCmrCollection.query.first()
    #         session_member = new_collection.member
    #
    #         self.assertTrue(new_collection is not None)
    #         self.assertTrue(session_member is not None)
    #
    # def test_create_member_cmr_granule(self):
    #     with app.app_context():
    #         coll = MemberCmrCollection.query.first()
    #
    #         granule = MemberCmrGranule(collection_id=coll.id, granule_ur="testgranur")
    #         db.session.add(granule)
    #         db.session.commit()
    #
    #         new_granule = MemberCmrGranule.query.first()
    #         session_member = new_granule.collection.member
    #         ref_collection = new_granule.collection
    #
    #         self.assertTrue(new_granule is not None)
    #         self.assertTrue(ref_collection is not None)
    #         self.assertTrue(session_member is not None)


