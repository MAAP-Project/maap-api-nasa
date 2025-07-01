# NASA MAAP API Test Implementation Plan

## Overview

This document provides a comprehensive step-by-step plan to implement the tests outlined in TESTING.md using Docker for all testing environments. The plan leverages the existing Docker infrastructure and extends it for comprehensive test coverage.

## Current State Analysis

### Existing Infrastructure
- **Docker Setup**: Multi-stage Dockerfile with Poetry dependency management
- **Database**: PostgreSQL 14.5 with health checks
- **Current Tests**: Limited tests for members, email utilities, and WMTS endpoints
- **Test Framework**: Python unittest (can be extended with pytest)

### Gaps Identified
- No Docker-based test execution
- Limited test coverage for core functionality
- No mocking framework for external services
- No CI/CD integration for tests
- Lack of integration test scenarios

## Implementation Plan

### Phase 1: Test Infrastructure Setup (Days 1-2) ✅ COMPLETED

#### 1.1 Create Test-Specific Docker Configuration ✅

**Create `docker/Dockerfile.test`**
```dockerfile
FROM python:3.9 as test-builder

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="${PATH}:/root/.local/bin" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /maap-api-nasa

COPY pyproject.toml poetry.lock ./
RUN touch README.md

# Install with dev dependencies for testing
RUN poetry install --with dev --no-root && rm -rf $POETRY_CACHE_DIR

FROM python:3.9-slim as test-runtime

ENV VIRTUAL_ENV=/maap-api-nasa/.venv \
    PATH="/maap-api-nasa/.venv/bin:$PATH" \
    PYTHONPATH="/maap-api-nasa:$PYTHONPATH"

COPY --from=test-builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3-psycopg2 \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

COPY api /maap-api-nasa/api
COPY test /maap-api-nasa/test
COPY logging.conf /maap-api-nasa/logging.conf

WORKDIR /maap-api-nasa

# Set test environment variables
ENV FLASK_ENV=testing \
    MOCK_RESPONSES=true \
    DATABASE_URL=postgresql://testuser:testpass@test-db:5432/maap_test
```

**Create `docker/docker-compose-test.yml`**
```yaml
version: '3.8'
services:
  test:
    container_name: 'maap-api-test'
    build:
      context: ../
      dockerfile: docker/Dockerfile.test
      target: test-runtime
    depends_on:
      test-db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://testuser:testpass@test-db:5432/maap_test
      - MOCK_RESPONSES=true
      - FLASK_ENV=testing
    volumes:
      - ../test:/maap-api-nasa/test
      - ./test-results:/maap-api-nasa/test-results
    command: pytest -v --tb=short --junitxml=test-results/results.xml --cov=api --cov-report=html:test-results/coverage
    networks:
      - test-network

  test-db:
    image: postgres:14.5
    container_name: 'maap-test-db'
    environment:
      POSTGRES_DB: maap_test
      POSTGRES_USER: testuser
      POSTGRES_PASSWORD: testpass
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - test-db-data:/var/lib/postgresql/data
    networks:
      - test-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -d postgresql://testuser:testpass@test-db/maap_test"]
      interval: 5s
      timeout: 5s
      retries: 20

volumes:
  test-db-data:

networks:
  test-network:
    driver: bridge
```

#### 1.2 Update pyproject.toml for Test Dependencies ✅

**Add to `[tool.poetry.group.dev.dependencies]`**
```toml
pytest = "^7.4.0"
pytest-cov = "^4.1.0"
pytest-mock = "^3.11.1"
responses = "^0.23.0"
requests-mock = "^1.11.0"
faker = "^19.0.0"
factory-boy = "^3.3.0"
freezegun = "^1.2.2"
```

#### 1.3 Create Test Configuration Files ✅

**Create `test/conftest.py`**
```python
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
```

**Phase 1 Implementation Summary:**
- ✅ Created `docker/Dockerfile.test` with multi-stage build for test environment
- ✅ Created `docker/docker-compose-test.yml` with PostgreSQL test database and health checks
- ✅ Updated `pyproject.toml` with comprehensive test dependencies (pytest, coverage, mocking tools)
- ✅ Created `test/conftest.py` with pytest fixtures for app context and database setup
- ✅ Created executable `scripts/run-tests.sh` for streamlined test execution
- ✅ Configured test environment variables and isolated test database connection

**Commit:** `0895a8b` - "Add Phase 1 test infrastructure setup"

### Phase 2: Core Test Implementation (Days 3-7)

#### 2.1 Authentication & Authorization Tests

**Create `test/api/auth/test_cas_auth.py`**
```python
import pytest
import responses
from api.auth.cas_auth import validate, validate_proxy
from api.models.member import Member
from api.models.member_session import MemberSession

class TestCASAuthentication:
    def test_user_can_authenticate_with_valid_cas_credentials(self, test_client, mock_cas_token):
        """Test: User can authenticate with valid CAS credentials"""
        # Given a user with valid CAS credentials
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://cas.example.com/validate', 
                    body='yes\ntestuser\n', status=200)
            
            # When they attempt to authenticate
            result = validate("http://example.com", mock_cas_token)
            
            # Then they should receive a valid session token
            assert result is not None
            assert result.member.username == "testuser"

    def test_user_authentication_fails_with_invalid_credentials(self, test_client):
        """Test: User authentication fails with invalid credentials"""
        # Given a user with invalid CAS credentials
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, 'https://cas.example.com/validate', 
                    body='no\n', status=200)
            
            # When they attempt to authenticate
            result = validate("http://example.com", "invalid-token")
            
            # Then authentication should fail
            assert result is None

    def test_protected_endpoints_reject_unauthenticated_requests(self, test_client):
        """Test: Protected endpoints reject unauthenticated requests"""
        # Given an unauthenticated user
        # When they attempt to access a protected endpoint
        response = test_client.get('/api/members/self')
        
        # Then they should receive a 401 Unauthorized response
        assert response.status_code == 401

    def test_proxy_ticket_decryption_works_correctly(self):
        """Test: Proxy ticket decryption works correctly"""
        # Implementation for proxy ticket decryption test
        # Based on existing test_proxy_decryption in test_members.py
        pass
```

#### 2.2 Member Management Tests

**Create `test/api/endpoints/test_member_management.py`**
```python
import pytest
from api.models.member import Member
from api.models.member_session import MemberSession
from api.models.member_algorithm import MemberAlgorithm

class TestMemberManagement:
    def test_new_member_can_be_created_successfully(self, test_client, sample_member_data):
        """Test: New member can be created successfully"""
        # Given valid member information
        member = Member(**sample_member_data)
        
        # When a new member is created
        test_client.application.app_context().push()
        from api.maap_database import db
        db.session.add(member)
        db.session.commit()
        
        # Then the member should be saved to the database
        saved_member = db.session.query(Member).filter_by(username="testuser").first()
        assert saved_member is not None
        assert saved_member.email == "test@example.com"

    def test_member_information_can_be_updated(self, test_client, sample_member_data):
        """Test: Member information can be updated"""
        # Given an existing member
        member = Member(**sample_member_data)
        test_client.application.app_context().push()
        from api.maap_database import db
        db.session.add(member)
        db.session.commit()
        
        # When their organization is updated
        member.organization = "ESA"
        db.session.commit()
        
        # Then the change should be persisted to the database
        updated_member = db.session.query(Member).filter_by(username="testuser").first()
        assert updated_member.organization == "ESA"

    def test_member_session_can_be_created_and_linked(self, test_client, sample_member_data):
        """Test: Member session can be created and linked"""
        # Given an existing member
        member = Member(**sample_member_data)
        test_client.application.app_context().push()
        from api.maap_database import db
        db.session.add(member)
        db.session.commit()
        
        # When a new session is created for that member
        session = MemberSession(member_id=member.id, session_key="test-session-key")
        db.session.add(session)
        db.session.commit()
        
        # Then the session should be linked to the member
        saved_session = db.session.query(MemberSession).filter_by(session_key="test-session-key").first()
        assert saved_session is not None
        assert saved_session.member.username == "testuser"

    def test_member_algorithms_can_be_associated_with_members(self, test_client, sample_member_data):
        """Test: Member algorithms can be associated with members"""
        # Given an existing member
        member = Member(**sample_member_data)
        test_client.application.app_context().push()
        from api.maap_database import db
        db.session.add(member)
        db.session.commit()
        
        # When an algorithm is registered to that member
        algorithm = MemberAlgorithm(
            member_id=member.id,
            algorithm_key="test-algo-key",
            is_public=False
        )
        db.session.add(algorithm)
        db.session.commit()
        
        # Then the algorithm should be linked to the member
        saved_algo = db.session.query(MemberAlgorithm).filter_by(algorithm_key="test-algo-key").first()
        assert saved_algo is not None
        assert saved_algo.member.username == "testuser"
        assert saved_algo.is_public == False
```

#### 2.3 Job Management Tests

**Create `test/api/endpoints/test_job_management.py`**
```python
import pytest
import responses
from unittest.mock import patch

class TestJobManagement:
    @responses.activate
    def test_job_can_be_submitted_successfully(self, test_client):
        """Test: Job can be submitted successfully"""
        # Mock HySDS job submission
        responses.add(responses.POST, 'http://mozart.example.com/api/v0.1/job/submit',
                     json={'job_id': 'test-job-123', 'status': 'queued'}, status=200)
        
        # Given a valid job submission request
        job_data = {
            'algorithm': 'test-algorithm',
            'parameters': {'param1': 'value1'}
        }
        
        # When the job is submitted
        response = test_client.post('/api/job/submit', json=job_data,
                                  headers={'Authorization': 'Bearer test-token'})
        
        # Then it should be queued in HySDS
        assert response.status_code == 200
        data = response.get_json()
        assert 'job_id' in data
        assert data['job_id'] == 'test-job-123'

    def test_job_submission_fails_with_invalid_parameters(self, test_client):
        """Test: Job submission fails with invalid parameters"""
        # Given a job submission with missing required parameters
        job_data = {}  # Missing required fields
        
        # When the job is submitted
        response = test_client.post('/api/job/submit', json=job_data,
                                  headers={'Authorization': 'Bearer test-token'})
        
        # Then submission should fail with validation error
        assert response.status_code == 400

    @responses.activate
    def test_job_status_can_be_queried(self, test_client):
        """Test: Job status can be queried"""
        # Mock HySDS job status response
        responses.add(responses.GET, 'http://mozart.example.com/api/v0.1/job/test-job-123',
                     json={'job_id': 'test-job-123', 'status': 'running'}, status=200)
        
        # Given a submitted job with valid job ID
        # When job status is requested
        response = test_client.get('/api/job/test-job-123/status',
                                 headers={'Authorization': 'Bearer test-token'})
        
        # Then current job status should be returned
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'running'

    def test_user_can_only_access_their_own_jobs(self, test_client):
        """Test: User can only access their own jobs"""
        # Implementation for job access control testing
        pass
```

### Phase 3: API Integration Tests (Days 8-10)

#### 3.1 CMR Integration Tests

**Create `test/api/endpoints/test_cmr_integration.py`**
```python
import pytest
import responses

class TestCMRIntegration:
    @responses.activate
    def test_cmr_collections_can_be_searched(self, test_client):
        """Test: CMR collections can be searched"""
        # Mock CMR collection search response
        responses.add(responses.GET, 'https://cmr.earthdata.nasa.gov/search/collections',
                     json={'feed': {'entry': [{'id': 'test-collection-1'}]}}, status=200)
        
        # Given valid search parameters
        # When collections are searched via CMR
        response = test_client.get('/api/cmr/collections?keyword=test')
        
        # Then relevant collections should be returned
        assert response.status_code == 200
        data = response.get_json()
        assert 'collections' in data

    @responses.activate
    def test_cmr_granules_can_be_searched(self, test_client):
        """Test: CMR granules can be searched"""
        # Mock CMR granule search response
        responses.add(responses.GET, 'https://cmr.earthdata.nasa.gov/search/granules',
                     json={'feed': {'entry': [{'id': 'test-granule-1'}]}}, status=200)
        
        # Given a valid collection and search parameters
        # When granules are searched
        response = test_client.get('/api/cmr/granules?collection_concept_id=C123')
        
        # Then matching granules should be returned
        assert response.status_code == 200

    def test_shapefile_upload_works_for_spatial_search(self, test_client):
        """Test: Shapefile upload works for spatial search"""
        # Implementation for shapefile upload testing
        pass
```

#### 3.2 WMTS/WMS Tests

**Create `test/api/endpoints/test_wmts_integration.py`**
```python
import pytest
import responses

class TestWMTSIntegration:
    @responses.activate
    def test_wmts_tiles_can_be_generated(self, test_client):
        """Test: WMTS tiles can be generated"""
        # Mock Titiler tile response
        responses.add(responses.GET, 'http://titiler.example.com/cog/tiles/1/0/0',
                     body=b'fake-tile-data', status=200,
                     headers={'Content-Type': 'image/png'})
        
        # Given a valid collection and tile coordinates
        # When a tile is requested
        response = test_client.get('/api/wmts/tiles/1/0/0?collection=test-collection')
        
        # Then a valid map tile should be returned
        assert response.status_code == 200
        assert response.headers['Content-Type'] == 'image/png'

    def test_wmts_capabilities_document_is_valid(self, test_client):
        """Test: WMTS capabilities document is valid"""
        # Given a WMTS capabilities request
        # When capabilities are requested
        response = test_client.get('/api/wmts/capabilities')
        
        # Then a valid XML capabilities document should be returned
        assert response.status_code == 200
        assert 'xml' in response.headers['Content-Type']

    def test_mosaic_urls_are_generated_correctly(self, test_client):
        """Test: Mosaic URLs are generated correctly"""
        # Implementation for mosaic URL generation testing
        pass
```

### Phase 4: Advanced Testing (Days 11-13)

#### 4.1 End-to-End Integration Tests

**Create `test/integration/test_end_to_end_workflows.py`**
```python
import pytest

class TestEndToEndWorkflows:
    def test_end_to_end_job_workflow(self, test_client):
        """Test: End-to-end job workflow"""
        # Given an authenticated user with a registered algorithm
        # When they submit a job, monitor status, and retrieve results
        # Then the complete workflow should work without errors
        pass

    def test_authentication_to_job_submission_workflow(self, test_client):
        """Test: Authentication to job submission workflow"""
        # Given a new user
        # When they authenticate, register an algorithm, and submit a job
        # Then the complete onboarding workflow should work
        pass

    def test_cmr_search_to_wmts_visualization_workflow(self, test_client):
        """Test: CMR search to WMTS visualization workflow"""
        # Given search criteria
        # When user searches CMR, selects granules, and views tiles
        # Then complete data discovery to visualization should work
        pass
```

#### 4.2 Security & Performance Tests

**Create `test/security/test_security.py`**
```python
import pytest

class TestSecurity:
    def test_sql_injection_attempts_are_blocked(self, test_client):
        """Test: SQL injection attempts are blocked"""
        # Given malicious SQL in request parameters
        malicious_payload = "'; DROP TABLE members; --"
        
        # When requests are processed
        response = test_client.get(f'/api/members?username={malicious_payload}')
        
        # Then SQL injection should be prevented
        assert response.status_code in [400, 404]  # Not 500 (server error)

    def test_sensitive_information_is_not_logged(self, test_client):
        """Test: Sensitive information is not logged"""
        # Implementation for log security testing
        pass

    def test_cross_origin_requests_are_handled_correctly(self, test_client):
        """Test: Cross-origin requests are handled correctly"""
        # Given requests from different origins
        response = test_client.get('/api/collections', 
                                 headers={'Origin': 'https://external.example.com'})
        
        # Then appropriate CORS headers should be returned
        assert 'Access-Control-Allow-Origin' in response.headers
```

### Phase 5: CI/CD Integration (Days 14-15)

#### 5.1 GitHub Actions Workflow

**Create `.github/workflows/test.yml`**
```yaml
name: Test Suite

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Build and run tests
      run: |
        cd docker
        docker-compose -f docker-compose-test.yml build
        docker-compose -f docker-compose-test.yml run --rm test
    
    - name: Upload test results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: test-results
        path: docker/test-results/
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        file: docker/test-results/coverage.xml
```

#### 5.2 Test Execution Scripts

**Create `scripts/run-tests.sh`**
```bash
#!/bin/bash
set -e

echo "Starting MAAP API Test Suite..."

# Navigate to docker directory
cd "$(dirname "$0")/../docker"

# Build test images
echo "Building test images..."
docker-compose -f docker-compose-test.yml build

# Run tests with coverage
echo "Running tests..."
docker-compose -f docker-compose-test.yml run --rm test

# Display results
echo "Test execution completed. Results available in docker/test-results/"

# Cleanup
docker-compose -f docker-compose-test.yml down -v
```

## Test Execution Commands

### Local Development
```bash
# Build and run all tests
./scripts/run-tests.sh

# Run specific test categories
docker-compose -f docker/docker-compose-test.yml run --rm test pytest test/api/endpoints/

# Run tests with coverage
docker-compose -f docker/docker-compose-test.yml run --rm test pytest --cov=api --cov-report=html

# Run tests in watch mode
docker-compose -f docker/docker-compose-test.yml run --rm test pytest -f
```

### Debugging Tests
```bash
# Run tests with detailed output
docker-compose -f docker/docker-compose-test.yml run --rm test pytest -vvv -s

# Run specific test
docker-compose -f docker/docker-compose-test.yml run --rm test pytest test/api/endpoints/test_members.py::TestMemberManagement::test_new_member_can_be_created_successfully

# Run with debugger
docker-compose -f docker/docker-compose-test.yml run --rm test pytest --pdb
```

## Benefits of Docker-Based Testing

1. **Environment Consistency**: Tests run in identical environment across all machines
2. **Isolation**: Complete separation from development environment
3. **Reproducibility**: Same test results regardless of host system
4. **CI/CD Ready**: Easy integration with automated pipelines
5. **Service Dependencies**: Clean management of database and external services
6. **Scalability**: Easy to run tests in parallel containers
7. **Version Control**: Test environment configuration is version controlled
8. **Fast Setup**: New developers can run tests immediately after checkout

## Implementation Priorities

### High Priority (Must Have)
- Authentication & Authorization Tests
- Member Management Tests
- Job Management Core Tests
- Database Model Tests
- Docker Test Infrastructure

### Medium Priority (Should Have)
- CMR Integration Tests
- WMTS/WMS Tests
- Algorithm Registration Tests
- Basic Security Tests
- CI/CD Integration

### Low Priority (Nice to Have)
- Performance Tests
- Advanced Security Tests
- Complex Integration Scenarios
- Load Testing
- Monitoring Integration

## Success Metrics

- **Test Coverage**: Achieve >80% code coverage for core functionality
- **Test Execution Time**: All tests complete within 10 minutes
- **Test Reliability**: <5% flaky test rate
- **CI/CD Integration**: Automated test execution on all PRs
- **Developer Experience**: New developers can run tests within 5 minutes of checkout

## Maintenance Guidelines

1. **Regular Updates**: Keep test dependencies and Docker images updated
2. **Test Data Management**: Regularly review and update test fixtures
3. **Mock Maintenance**: Keep external service mocks aligned with real APIs
4. **Performance Monitoring**: Monitor test execution times and optimize slow tests
5. **Documentation**: Keep test documentation current with implementation changes

This comprehensive plan provides a robust foundation for implementing test-driven development with Docker-based testing for the NASA MAAP API project.