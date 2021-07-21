MAAP_API_URL = "https://api.maap.xyz/api"
PROJECT_QUEUE_PREFIX = "maap"
API_HOST_URL = 'http://0.0.0.0:5000/'
# API_HOST_URL = 'https://api.maap-project.org/api'

# Flask settings
FLASK_SERVER_NAME = 'localhost:5000'
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
CMR_URL = 'https://cmr.maap-project.org'
CMR_API_TOKEN = ''
CMR_CLIENT_ID = ''
MAAP_WMTS_XML = '/maap-api-nasa/api/maap.wmts.xml'

# GIT settings
GIT_REPO_URL = 'https://gitlab-ci-token:$TOKEN@repo.nasa.maap.xyz/root/register-job.git'

# GTILAB Settings
GITLAB_TOKEN = 'foobar'
MAAP_ENVIRONMENT_FILE = 'https://raw.githubusercontent.com/MAAP-Project/maap-jupyter-ide/develop/maap_environments.json'

REPO_NAME = 'register-job'
REPO_PATH = '/home/ubuntu/repo'
VERSION = 'master'
SUPPORTED_EXTENSIONS = ['py', 'java', 'sh']

# Docker container URL
CONTAINER_URL = 'registry.nasa.maap.xyz/root/dps_plot:master'

# HySDS Mozart
MOZART_URL = 'https://[MOZART_IP]/mozart/api/v0.2'
DEFAULT_QUEUE = 'test-job_worker-large'
LW_QUEUE = 'system-jobs-queue'
HYSDS_LW_VERSION = 'v0.0.5'
GRQ_REST_URL = 'http://[GRQ_IP]/api/v0.1'
S3_CODE_BUCKET = 's3://[S3_BUCKET_NAME]'

# Dynamic Tiler API - OLD API
#
# Uncomment the `TILER_ENDPOINT` line below if testing api.maap-project.org at this time.
# api.maap-project.org is using an older version of the Dynamic Tiler API.
# TILER_ENDPOINT = 'https://8e9mu91qr6.execute-api.us-east-1.amazonaws.com/production'

# Dynamic Tiler API - NEW API
# The updated WMTS code (api/endpoints/wmts.py) should work with the newer version of the tiler API is deployed at the URL below.
TILER_ENDPOINT = 'https://d852m4cmf5.execute-api.us-east-1.amazonaws.com'

# 3D Tiles API
_3DTILES_API_ENDPOINT = 'https://llxbmdibvf.execute-api.us-east-1.amazonaws.com/test'
DATA_SYSTEM_FILES_PATH = '/file-staging/nasa-map/'

# CAS
CAS_SECRET_KEY = '9c0d611c-04c5-4f36-b91c-8374b4410590'
CAS_SERVER_NAME = 'https://auth.nasa.maap.xyz/cas'
CAS_AFTER_LOGIN = 'api.members_self'
CAS_PROXY_DECRYPTION_TOKEN = ''

# Query Service
QS_STATE_MACHINE_ARN = 'arn:aws:states:us-east-1:532321095167:stateMachine:maap-api-query-service-dev-RunQuery'
QS_RESULT_BUCKET = 'maap-api-query-service-dev-query-results'

# AWS
AWS_REGION = 'us-east-1'
WORKSPACE_MOUNT_PRIVATE = 'my-private-bucket'
WORKSPACE_MOUNT_PUBLIC = 'my-public-bucket'
WORKSPACE_MOUNT_SHARED = 'shared-buckets'
AWS_SHARED_WORKSPACE_BUCKET_PATH = 'shared'

# DB
DATABASE_URL='postgresql://localhost/maap_dev'

# OGC API - Features
OGCAPI_FEATURES_ENDPOINT = "https://8k07ljl96e.execute-api.us-east-1.amazonaws.com"
