import unittest

from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.utils.email_util import Email, send_new_active_user_email, send_new_suspended_user_email, \
    send_user_status_update_active_user_email, send_user_status_update_suspended_user_email, \
    send_welcome_to_maap_active_user_email, send_welcome_to_maap_suspended_user_email
from api import settings
from datetime import datetime


class EmailCase(unittest.TestCase):

    # Setup
    def setUp(self):

        self.test_email = "maap.test_email@jpl.nasa.gov"
        self.base_url = "http://0.0.0.0/"

        with app.app_context():

            initialize_sql(db.engine)

            member = db.session.query(Member).filter(Member.email == self.test_email)

            if member.count() == 1:
                self.member = member[0]
            else:
                self.member = Member(
                    first_name="Jesse",
                    last_name="Doe",
                    username="jessedoe2",
                    email=self.test_email,
                    organization="NASA",
                    public_ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCzN22QMC8fL4UjwuizV2o52P5mPXBUAnIziUIW77flHBc186aXR13VfaquOqsWKGx51bM8H4PC7yMdoEgKFq2DCx2FeY6BosW3QmnHDc7+Ov3+jDJh8OefBWpaolfGMzgH/te2SswVr2zv1/SSHSLN8L3PQBM6ul/UM4EA0VvXuHz7g+5t5FWDSMjz7LEvafhaxa85r5iV9kICta7F09QAVWr/tugRnQs004fTL/wwak4SICaKh5fXrxU+UyxXfz2QDpKXvvDz1JU7yb4UT6CRz86L3tTK+nWXg7rwSok+H1CchYYEP4/WJTVACJ4iPUQN0RNPCwPekDdpR7kjJnOh brian.p.satorius@jpl.nasa.gov, IMCE Infrastructure Development sd",
                    public_ssh_key_modified_date=datetime.utcnow(),
                    public_ssh_key_name="id_rsa_satorius",
                    urs_token="EDL-Of35fb098..."
                )

                db.session.add(self.member)
                db.session.commit()

    # Tests
    def test_email_utility(self):

        subj = "MAAP Email Test"
        html = """
        <html>
          <body>
            <p>
                <b>MAAP Email Test</b>
                <br>
                This is a test email.
            </p>
          </body>
        </html>
        """

        text = """
        MAAP Email Test

        This is a test email.
        """

        email = Email(settings.EMAIL_NO_REPLY, settings.EMAIL_JPL_ADMINS.split(","), subj, html, text)
        email.send()

    def test_send_new_active_user_email(self):
        send_new_active_user_email(self.member, self.base_url)

    def test_send_new_suspended_user_email(self):
        send_new_suspended_user_email(self.member, self.base_url)

    def test_send_user_status_update_active_user_email(self):
        send_user_status_update_active_user_email(self.member, self.base_url)

    def test_send_user_status_update_suspended_user_email(self):
        send_user_status_update_suspended_user_email(self.member, self.base_url)

    def test_send_welcome_to_maap_active_user_email(self):
        send_welcome_to_maap_active_user_email(self.member, self.base_url)

    def test_send_welcome_to_maap_suspended_user_email(self):
        send_welcome_to_maap_suspended_user_email(self.member, self.base_url)
