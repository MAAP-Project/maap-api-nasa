import pytest
import os
from api.maapapp import app
from api.maap_database import db
from api.models import initialize_sql

@pytest.fixture(scope="session")
def test_app():
    """Create application for testing."""
    app.config['TESTING'] = True
    app.config['DATABASE_URL'] = os.getenv('DATABASE_URL', 'sqlite:///:memory:')
    app.config['MOCK_RESPONSES'] = True
    return app

@pytest.fixture(scope="function")
def test_client(test_app):
    """Create test client."""
    with test_app.test_client() as client:
        with test_app.app_context():
            initialize_sql(db.engine)
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def mock_cas_token():
    """Mock CAS authentication token."""
    return "test-cas-token-12345"

@pytest.fixture
def sample_member_data():
    """Sample member data for testing."""
    return {
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "email": "test@example.com",
        "organization": "NASA",
        "public_ssh_key": "ssh-rsa AAAAB3NzaC1yc2ETEST..."
    }