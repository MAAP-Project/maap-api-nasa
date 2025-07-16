# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development Setup
```bash
# Docker-based development (recommended)
cd docker
docker-compose -f docker-compose-local.yml up

# Poetry-based development
poetry install
poetry shell
FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
```

### Database Setup (First Run)
```bash
# Create database user and database
createuser maapuser
createdatabase maap
```

### Testing
```bash
# Run specific test
python -m unittest test/api/endpoints/test_wmts_get_tile.py

# Run tests with new Titiler
python -m unittest -v test/api/endpoints/test_wmts_get_tile_new_titiler.py
python -m unittest -v test/api/endpoints/test_wmts_get_capabilities_new_titiler.py

# Run email utility tests
python3 -m unittest test/api/utils/test_email.py
```

### Makefile Commands
```bash
make run-api           # Run the API server
make start-database    # Start PostgreSQL database
make stop-database     # Stop PostgreSQL database
make test-email        # Run email utility tests
```

### Linting
```bash
pylint api/           # Lint the API code (pylint is configured in pyproject.toml)
```

## Architecture Overview

### Project Structure
- **api/**: Core API implementation
  - **endpoints/**: REST API endpoint implementations organized by domain
    - `algorithm.py`: Algorithm registration and management
    - `job.py`: Job submission and monitoring 
    - `members.py`: User management and authentication
    - `cmr.py`: CMR (Common Metadata Repository) integration
    - `wmts.py`/`wms.py`: Web mapping tile/map services
    - `organizations.py`: Organization management
    - `admin.py`: Administrative functions
  - **auth/**: Authentication and authorization
    - `cas_auth.py`: CAS (Central Authentication Service) integration
    - `security.py`: Security utilities and decorators
  - **models/**: SQLAlchemy database models
  - **schemas/**: Marshmallow serialization schemas
  - **utils/**: Utility modules for common functionality
- **test/**: Unit tests mirroring the API structure
- **docker/**: Docker configuration files
- **sql/**: Database schema and migration files

### Key Technologies
- **Flask**: Web framework with Flask-RESTX for API documentation
- **SQLAlchemy**: Database ORM with PostgreSQL backend
- **Poetry**: Dependency management
- **CAS Authentication**: Integration with Central Authentication Service
- **CMR Integration**: NASA's Common Metadata Repository
- **HySDS Integration**: JPL's Hybrid Science Data System for job processing
- **WMTS/WMS**: OGC-compliant web mapping services

### Database Models
The application uses SQLAlchemy models for:
- **Member**: User accounts and profiles
- **Organization**: User organizations and memberships  
- **MemberJob**: Job tracking and history
- **MemberAlgorithm**: User-registered algorithms
- **JobQueue**: Job queue management
- **MemberSession**: User session management

### Main Application Flow
1. **maapapp.py**: Main Flask application entry point
2. **restplus.py**: API configuration and error handling
3. **settings.py**: Environment-based configuration management
4. **maap_database.py**: Database initialization

### Authentication Architecture
- CAS-based authentication for web interface
- Token-based authentication for API access
- EDL (Earthdata Login) integration for NASA credentials
- Proxy ticket validation for service-to-service communication

### Key External Integrations
- **CMR**: NASA's metadata repository for dataset discovery
- **HySDS**: Job execution and workflow management
- **GitLab**: Code repository management for algorithm registration
- **Titiler**: Dynamic tile server for geospatial data visualization
- **AWS S3**: Storage for user workspaces and job outputs

### Configuration Management
Environment variables are centralized in `settings.py` with defaults for local development. Key configuration areas:
- Database connection settings
- External service URLs (CMR, HySDS, GitLab)
- Authentication settings (CAS, EDL)
- AWS resource configuration
- Email service settings

### Development Notes
- The application supports both Docker and local Poetry-based development
- Database migrations are handled through SQLAlchemy
- Tests are organized to mirror the API endpoint structure
- The codebase follows Flask blueprint patterns for modular organization
- Environment-specific settings are managed through environment variables with sensible defaults