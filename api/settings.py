# Auth
APP_AUTH_KEY = "thisisthesecretkey"

# Flask settings
FLASK_SERVER_NAME = 'http://52.90.119.181:5000'
FLASK_DEBUG = True  # Do not use debug mode in production

# Flask-Restplus settings
RESTPLUS_SWAGGER_UI_DOC_EXPANSION = 'list'
RESTPLUS_VALIDATE = True
RESTPLUS_MASK_SWAGGER = False
RESTPLUS_ERROR_404_HELP = False

# CMR settings

# # NASA UAT
# CMR_URL = 'https://cmr.uat.earthdata.nasa.gov'
# CMR_API_TOKEN = '4C40153D-6CC6-D01A-58E2-D8F3CAFB5472'
# CMR_CLIENT_ID = 'maap-api-cmr'

CMR_TOKEN_SERVICE_URL = 'https://cmr.earthdata.nasa.gov/legacy-services/rest/tokens'

# MAAP DEV
CMR_URL = 'https://maap-project.org'
CMR_API_TOKEN = ''
CMR_CLIENT_ID = ''

# GIT settings
GIT_REPO_URL = "https://gitlab-ci-token:$TOKEN@repo.nasa.maap.xyz/root/register-job.git"

REPO_NAME = "register-job"
REPO_PATH = "/home/ubuntu/repo"
VERSION = "master"
SUPPORTED_EXTENSIONS = ["py", "java", "sh"]

# Docker container URL
CONTAINER_URL = "registry.nasa.maap.xyz/root/dps_plot:master"

# HySDS Mozart
MOZART_URL = "https://[MOZART_IP]/mozart/api/v0.2"
DEFAULT_QUEUE = "test-job_worker-large"

# FASTBROWSE API
TILER_ENDPOINT = 'https://8e9mu91qr6.execute-api.us-east-1.amazonaws.com/production'

