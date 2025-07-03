# NASA MAAP API Testing Guide

This document outlines high-priority test scenarios for test-driven development of the NASA MAAP API. Tests are written in plain English and focus on critical functionality rather than comprehensive coverage.

## Core Functional Tests

### Authentication & Authorization Tests

**Test: User can authenticate with valid CAS credentials**
- Given a user with valid CAS credentials
- When they attempt to authenticate
- Then they should receive a valid session token
- And they should be able to access protected endpoints

**Test: User authentication fails with invalid credentials**
- Given a user with invalid CAS credentials
- When they attempt to authenticate
- Then authentication should fail
- And they should not receive a session token

**Test: Protected endpoints reject unauthenticated requests**
- Given an unauthenticated user
- When they attempt to access a protected endpoint
- Then they should receive a 401 Unauthorized response

**Test: Proxy ticket decryption works correctly**
- Given a valid encrypted proxy ticket from CAS
- When the system attempts to decrypt it
- Then it should successfully decrypt to a valid PGT token
- And the token should start with "PGT-"

### Member Management Tests

**Test: New member can be created successfully**
- Given valid member information (name, email, organization, SSH key)
- When a new member is created
- Then the member should be saved to the database
- And all required fields should be populated correctly

**Test: Member information can be updated**
- Given an existing member
- When their organization is updated
- Then the change should be persisted to the database
- And the member should reflect the new organization

**Test: Member session can be created and linked**
- Given an existing member
- When a new session is created for that member
- Then the session should be linked to the member
- And the session should be retrievable with member information

**Test: Member algorithms can be associated with members**
- Given an existing member
- When an algorithm is registered to that member
- Then the algorithm should be linked to the member
- And the algorithm should have correct visibility settings

### Job Management Tests

**Test: Job can be submitted successfully**
- Given a valid job submission request with algorithm and parameters
- When the job is submitted
- Then it should be queued in HySDS
- And a job ID should be returned
- And the job should be associated with the submitting user

**Test: Job submission fails with invalid parameters**
- Given a job submission with missing required parameters
- When the job is submitted
- Then submission should fail with validation error
- And no job should be created in the system

**Test: Job status can be queried**
- Given a submitted job with valid job ID
- When job status is requested
- Then current job status should be returned
- And status should match HySDS job state

**Test: Job results can be retrieved**
- Given a completed job
- When job results are requested
- Then job output files and metadata should be returned
- And results should include product URLs

**Test: User can only access their own jobs**
- Given jobs submitted by different users
- When a user queries for jobs
- Then they should only see their own jobs
- And they should not see jobs from other users

### CMR Integration Tests

**Test: CMR collections can be searched**
- Given valid search parameters
- When collections are searched via CMR
- Then relevant collections should be returned
- And results should include collection metadata

**Test: CMR granules can be searched**
- Given a valid collection and search parameters
- When granules are searched
- Then matching granules should be returned
- And results should include granule URLs and metadata

**Test: Shapefile upload works for spatial search**
- Given a valid shapefile
- When it is uploaded for spatial search
- Then the shapefile should be processed
- And spatial bounds should be extracted for search

### WMTS/WMS Mapping Tests

**Test: WMTS tiles can be generated**
- Given a valid collection and tile coordinates
- When a tile is requested
- Then a valid map tile should be returned
- And tile should contain correct geospatial data

**Test: WMTS capabilities document is valid**
- Given a WMTS capabilities request
- When capabilities are requested
- Then a valid XML capabilities document should be returned
- And document should include available layers

**Test: Mosaic URLs are generated correctly**
- Given multiple granule URLs
- When a mosaic is requested
- Then a valid Titiler mosaic URL should be generated
- And URL should include all specified granules

### Organization Management Tests

**Test: Organization can be created**
- Given valid organization details
- When an organization is created
- Then it should be saved to the database
- And it should be retrievable by ID

**Test: User can be added to organization**
- Given an existing organization and user
- When user is added to organization
- Then membership should be created
- And user should have access to organization resources

**Test: Organization job queues can be managed**
- Given an organization
- When job queues are configured for the organization
- Then members should be able to use organization queues
- And queue access should be restricted to organization members

### Algorithm Registration Tests

**Test: Algorithm can be registered successfully**
- Given valid algorithm code and metadata
- When algorithm registration is initiated
- Then algorithm should be built and containerized
- And algorithm should be available for job submission

**Test: Algorithm build status can be tracked**
- Given a registered algorithm
- When build status is queried
- Then current build progress should be returned
- And status should reflect GitLab pipeline state

**Test: Public algorithms are accessible to all users**
- Given a public algorithm
- When any authenticated user searches for algorithms
- Then the public algorithm should be included in results

**Test: Private algorithms are only visible to owner**
- Given a private algorithm
- When a different user searches for algorithms
- Then the private algorithm should not be visible
- And only the owner should see it in their algorithm list

## Unit Tests for Critical Utilities

### Email Utility Tests

**Test: Email can be sent successfully**
- Given valid email configuration
- When an email is sent
- Then email should be delivered without errors
- And both HTML and text versions should work

**Test: User status change emails are formatted correctly**
- Given a member with status change
- When status change email is triggered
- Then email should contain correct user information
- And email content should match expected template

### Security Utility Tests

**Test: Authorization headers are parsed correctly**
- Given various authorization header formats
- When headers are parsed
- Then correct token values should be extracted
- And invalid headers should be rejected

**Test: DPS token validation works**
- Given a valid DPS token
- When token is validated
- Then validation should succeed
- And token should provide correct permissions

### HySDS Integration Tests

**Test: Job submission JSON is formatted correctly**
- Given job parameters
- When submission JSON is generated
- Then JSON should match HySDS expected format
- And all required fields should be included

**Test: Job status mapping works correctly**
- Given HySDS job status
- When status is translated to WPS format
- Then correct WPS status should be returned
- And status should be user-friendly

**Test: Recommended queues are retrieved**
- Given user and job requirements
- When recommended queues are requested
- Then appropriate queues should be returned
- And queues should match user permissions

### Database Model Tests

**Test: Member model relationships work correctly**
- Given a member with sessions, jobs, and algorithms
- When relationships are queried
- Then all related objects should be accessible
- And foreign key constraints should be enforced

**Test: Organization membership model works**
- Given members and organizations
- When memberships are created
- Then many-to-many relationships should work correctly
- And cascade deletes should work appropriately

## Integration Tests

**Test: End-to-end job workflow**
- Given an authenticated user with a registered algorithm
- When they submit a job, monitor status, and retrieve results
- Then the complete workflow should work without errors
- And results should be accessible in user workspace

**Test: Authentication to job submission workflow**
- Given a new user
- When they authenticate, register an algorithm, and submit a job
- Then the complete onboarding workflow should work
- And user should be able to access all features

**Test: CMR search to WMTS visualization workflow**
- Given search criteria
- When user searches CMR, selects granules, and views tiles
- Then complete data discovery to visualization should work
- And tiles should display correct geographic data

## Error Handling Tests

**Test: Database connection failures are handled gracefully**
- Given a database connection issue
- When API requests are made
- Then appropriate error responses should be returned
- And system should not crash

**Test: External service failures are handled**
- Given CMR or HySDS service unavailability
- When dependent operations are attempted
- Then appropriate error messages should be returned
- And system should remain stable

**Test: Invalid input validation works**
- Given various invalid inputs to API endpoints
- When requests are made
- Then appropriate validation errors should be returned
- And invalid data should not be processed

## Performance Tests

**Test: API responds within acceptable time limits**
- Given normal load conditions
- When API requests are made
- Then responses should return within 5 seconds
- And system should handle concurrent requests

**Test: Large file uploads work correctly**
- Given large shapefile uploads
- When files are uploaded
- Then uploads should complete successfully
- And system should not timeout or crash

## Security Tests

**Test: SQL injection attempts are blocked**
- Given malicious SQL in request parameters
- When requests are processed
- Then SQL injection should be prevented
- And database should remain secure

**Test: Sensitive information is not logged**
- Given requests containing tokens or credentials
- When operations are performed
- Then sensitive data should not appear in logs
- And credentials should be properly masked

**Test: Cross-origin requests are handled correctly**
- Given requests from different origins
- When CORS-enabled endpoints are accessed
- Then appropriate CORS headers should be returned
- And legitimate cross-origin requests should work

## Running Tests

### Prerequisites
- Local development environment set up (see CLAUDE.md)
- Test database configured
- Required environment variables set

### Test Execution
```bash
# Run all tests
python -m unittest discover test/

# Run specific test modules
python -m unittest test.api.endpoints.test_members
python -m unittest test.api.utils.test_email

# Run individual test methods
python -m unittest test.api.endpoints.test_members.MembersCase.test_create_member
```

### Test Data Management
- Tests should create their own test data
- Database should be cleaned between test runs
- Use transaction rollback for test isolation
- Mock external services when possible

### Test Environment Configuration
- Set `MOCK_RESPONSES=true` to mock external API calls
- Use separate test database to avoid data conflicts
- Configure test-specific environment variables
- Ensure tests can run independently

## Notes

- Focus on testing business logic and critical paths
- Keep tests simple and maintainable
- Use descriptive test names that explain the scenario
- Group related tests together
- Test both success and failure scenarios
- Mock external dependencies to ensure test reliability
- Prioritize tests for security-critical functionality
- Test error conditions and edge cases
- Ensure tests can run in CI/CD environment