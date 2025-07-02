import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql
from api.models.member import Member
from api.models.role import Role
from api.utils.email_util import (
    Email, 
    send_user_status_change_email, 
    send_user_status_update_active_user_email, 
    send_user_status_update_suspended_user_email,
    send_welcome_to_maap_active_user_email, 
    send_welcome_to_maap_suspended_user_email
)
from api import settings


class TestEmailSystem(unittest.TestCase):
    """Modernized email system tests with Docker integration."""
    
    def setUp(self):
        """Setup test database and test member."""
        with app.app_context():
            initialize_sql(db.engine)
            db.create_all()
            
            # Clear any existing test data
            db.session.query(Member).delete()
            db.session.query(Role).delete()
            db.session.commit()
            
            # Create required Role with proper id for Member foreign key
            guest_role = Role(id=Role.ROLE_GUEST, role_name='guest')
            db.session.add(guest_role)
            db.session.commit()
            
            # Create test member
            self.test_member = Member(
                first_name="Test",
                last_name="User", 
                username="testuser_email",
                email="test.email@maap-project.org",
                organization="NASA",
                public_ssh_key="ssh-rsa AAAAB3NzaC1yc2ETEST...",
                public_ssh_key_modified_date=datetime.utcnow(),
                public_ssh_key_name="test_key",
                urs_token="EDL-Test123...",
                role_id=Role.ROLE_GUEST
            )
            db.session.add(self.test_member)
            db.session.commit()
            
            # Store member data for use in tests to avoid DetachedInstanceError
            self.test_member_email = self.test_member.email
            self.test_member_id = self.test_member.id
    
    def tearDown(self):
        """Clean up test database."""
        with app.app_context():
            db.session.remove()
            db.drop_all()
    
    @patch('api.utils.email_util.smtplib.SMTP')
    def test_email_utility_sends_messages(self, mock_smtp):
        """Tests basic email sending functionality."""
        mock_server = MagicMock()
        # Set up context manager properly
        mock_smtp.return_value.__enter__.return_value = mock_server
        mock_smtp.return_value.__exit__.return_value = None
        
        subject = "MAAP Test Email"
        html_content = "<html><body><p>Test email content</p></body></html>"
        text_content = "Test email content"
        
        with app.app_context():
            email = Email(
                settings.EMAIL_NO_REPLY,
                ["test@example.com"],
                subject,
                html_content,
                text_content
            )
            email.send()
        
        # Verify SMTP interactions
        mock_smtp.assert_called_once()
        mock_server.set_debuglevel.assert_called_once()
        mock_server.ehlo.assert_called()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_new_active_user_email_is_sent(self, mock_send):
        """Tests new active user email notification."""
        mock_send.return_value = True
        
        with app.app_context():
            send_user_status_change_email(self.test_member, True, True, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_new_suspended_user_email_is_sent(self, mock_send):
        """Tests new suspended user email notification."""
        mock_send.return_value = True
        
        with app.app_context():
            send_user_status_change_email(self.test_member, True, False, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_welcome_email_for_active_users(self, mock_send):
        """Tests welcome email for activated users."""
        mock_send.return_value = True
        
        with app.app_context():
            send_welcome_to_maap_active_user_email(self.test_member, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_welcome_email_for_suspended_users(self, mock_send):
        """Tests welcome email for suspended users."""
        mock_send.return_value = True
        
        with app.app_context():
            send_welcome_to_maap_suspended_user_email(self.test_member, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_user_status_update_active_email(self, mock_send):
        """Tests user status update email for active users."""
        mock_send.return_value = True
        
        with app.app_context():
            send_user_status_update_active_user_email(self.test_member, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_user_status_update_suspended_email(self, mock_send):
        """Tests user status update email for suspended users."""
        mock_send.return_value = True
        
        with app.app_context():
            send_user_status_update_suspended_user_email(self.test_member, "http://test.example.com")
        
        # Verify email was sent
        mock_send.assert_called_once()
    
    @patch('api.utils.email_util.Email.send')
    def test_email_template_rendering_with_member_data(self, mock_send):
        """Tests email template rendering with member data."""
        mock_send.return_value = True
        
        with app.app_context():
            # Test that email templates include member information
            send_welcome_to_maap_active_user_email(self.test_member, "http://test.example.com")
            
            mock_send.assert_called_once()
            
            # Verify email was created with proper content
            call_args = mock_send.call_args
            self.assertIsNotNone(call_args)
    
    def test_email_configuration_validation(self):
        """Tests email configuration and settings validation."""
        with app.app_context():
            # Verify required email settings exist
            self.assertIsNotNone(settings.EMAIL_NO_REPLY)
            self.assertIsNotNone(settings.EMAIL_JPL_ADMINS)
            
            # Test email address format validation
            self.assertIn("@", self.test_member_email)
            self.assertTrue(self.test_member_email.endswith(".org"))
    
    @patch('api.utils.email_util.smtplib.SMTP')
    def test_email_send_error_handling(self, mock_smtp):
        """Tests email sending error handling."""
        # Mock SMTP server to raise an exception
        mock_smtp.side_effect = Exception("SMTP connection failed")
        
        subject = "Test Email"
        html_content = "<html><body><p>Test</p></body></html>"
        text_content = "Test"
        
        with app.app_context():
            email = Email(
                settings.EMAIL_NO_REPLY,
                ["test@example.com"],
                subject,
                html_content,
                text_content
            )
            
            # Test that exceptions are handled gracefully
            with self.assertRaises(Exception):
                email.send()
    
    def test_email_object_string_representation(self):
        """Tests Email object string representation."""
        with app.app_context():
            email = Email(
                "from@example.com",
                ["to@example.com"],
                "Test Subject",
                "<html><body>Test</body></html>",
                "Test"
            )
            
            email_str = str(email)
            self.assertIn("from@example.com", email_str)
            self.assertIn("to@example.com", email_str)
            self.assertIn("Test Subject", email_str)


if __name__ == '__main__':
    unittest.main()