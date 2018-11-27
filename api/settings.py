# Flask settings
FLASK_SERVER_NAME = 'localhost:5000'
FLASK_DEBUG = True  # Do not use debug mode in production

# Flask-Restplus settings
RESTPLUS_SWAGGER_UI_DOC_EXPANSION = 'list'
RESTPLUS_VALIDATE = True
RESTPLUS_MASK_SWAGGER = False
RESTPLUS_ERROR_404_HELP = False

# CMR settings
CMR_URL = 'https://cmr.uat.earthdata.nasa.gov'
CMR_API_TOKEN = '4C40153D-6CC6-D01A-58E2-D8F3CAFB5472'
CMR_CLIENT_ID = 'maap-api-cmr'

# GIT settings
GIT_REPO_URL = "https://github.com/NamrataM/maap-test.git"
REPO_NAME = "maap-test"
REPO_PATH = "/Path/to/clone/git_repo"
VERSION = "master"

# Docker container URL
CONTAINER_URL = "http://docker.io/user/test_slc_extractor"

# HySDS Mozart
MOZART_URL = "https://[MOZART_IP]/mozart/api/v0.1"
DEFAULT_QUEUE = "factotum-job_worker-small"