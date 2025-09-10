# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development Setup
```bash
# Using Poetry (recommended)
poetry install
poetry shell
FLASK_APP=api/maapapp.py flask run --host=0.0.0.0

# Using Docker
cd docker
docker-compose -f docker-compose-local.yml up
```

### Database Setup (First Run)
```bash
# Create PostgreSQL user and database
createuser maapuser
createdatabase maap

# Start/stop database (macOS)
make start-database  # brew services start postgresql
make stop-database   # brew services stop postgresql
```

### Running Tests
```bash
# Individual test modules
python -m unittest test/api/endpoints/test_wmts_get_tile.py
python -m unittest test/api/utils/test_email.py

# For latest Titiler version
python -m unittest -v test/api/endpoints/test_wmts_get_tile_new_titiler.py
python -m unittest -v test/api/endpoints/test_wmts_get_capabilities_new_titiler.py
```

### Linting
```bash
poetry run pylint api/
```

## Architecture Overview

### Core Application Structure
- **Entry Point**: `api/maapapp.py` - Flask application with Flask-RESTX API documentation
- **Database**: PostgreSQL with SQLAlchemy ORM, connection pooling
- **Authentication**: NASA CAS (Central Authentication Service) integration
- **API Organization**: Blueprint-based with Flask-RESTX namespaces

### Key Directories
- `api/endpoints/` - REST API endpoints organized by functionality
- `api/models/` - SQLAlchemy database models (Member, Organization, Job, Algorithm, Role, Session)
- `api/schemas/` - Marshmallow serialization schemas
- `api/auth/` - CAS authentication and security modules
- `api/utils/` - Utility modules for external service integrations
- `test/` - Unit tests mirroring main code structure
- `sql/materialized_views/` - Database optimization views

### External Service Integrations
- **NASA CMR**: Common Metadata Repository for dataset metadata
- **HySDS**: Hybrid Science Data System for distributed job execution
- **AWS Services**: S3, Lambda, Step Functions for data processing
- **GitLab**: Repository management for algorithm deployment
- **Titiler**: Dynamic raster tiling service for geospatial data
- **OGC Standards**: WMTS/WMS web mapping services

### API Namespaces
- **CMR**: NASA dataset search and metadata retrieval
- **MAS**: Algorithm registration and management
- **DPS**: Job submission and execution via HySDS
- **Members**: User authentication and management
- **Organizations**: Multi-tenant organization management
- **Admin**: Administrative functions

### Database Models
- **Member**: User accounts and authentication
- **Organization**: Multi-tenancy support
- **Job/Algorithm**: Scientific computing workflow management
- **Role**: Role-based access control
- **Session**: User session management

### Configuration
- Environment-based configuration in `api/settings.py`
- Poetry dependency management (Python 3.9+)
- Docker multi-stage builds for deployment
- AWS CodeDeploy integration via `appspec.yml`

### Development Notes
- When testing locally with docker-compose, update `DATABASE_URL` in settings.py to use `localhost` instead of `db` (do not commit this change)
- Earthdata account required for API token access
- API documentation available at http://0.0.0.0:5000/api when running locally
- Geospatial processing requires pyproj, OWSLib, and shapefile libraries