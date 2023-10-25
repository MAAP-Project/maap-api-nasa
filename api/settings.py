MAAP_API_URL = "https://api.dit.maap-project.org/api"
PROJECT_QUEUE_PREFIX = "maap"
API_HOST_URL = 'http://0.0.0.0:5000/'

# Flask settings
FLASK_SERVER_NAME = 'localhost:5000'
FLASK_DEBUG = True  # Do not use debug mode in production

# Flask-Restplus settings
RESTPLUS_SWAGGER_UI_DOC_EXPANSION = 'list'
RESTPLUS_VALIDATE = True
RESTPLUS_MASK_SWAGGER = False
RESTPLUS_ERROR_404_HELP = False

CMR_TOKEN_SERVICE_URL = 'https://cmr.earthdata.nasa.gov/legacy-services/rest/tokens'

# MAAP DEV
CMR_URL = 'https://cmr.maap-project.org'
CMR_API_TOKEN = ''
CMR_CLIENT_ID = ''
###
# Inherited from sister, currently not used on MAAP
# TODO: Remove references in code
CMR_PROVIDER = 'MAAP'
UMM_C_VERSION = '1.9'
UMM_G_VERSION = '1.6'
# END Sister inherited section
###
MAAP_WMTS_XML = '/maap-api-nasa/api/maap.wmts.xml'
MAAP_EDL_CREDS = ''

# GIT settings
GIT_REPO_URL = 'https://gitlab-ci-token:$TOKEN@repo.dit.maap-project.org/root/register-job.git'
GIT_API_URL = 'https://repo.dit.maap-project.org/api/v4/projects'
REGISTER_JOB_REPO_ID = ''  # Enter project ID for register job repo

# GTILAB Settings
GITLAB_TOKEN = 'foobar'
GITLAB_API_TOKEN = ''  # New setting inherited from sister, remove comment after API is stable

MAAP_ENVIRONMENT_FILE = 'https://raw.githubusercontent.com/MAAP-Project/maap-jupyter-ide/develop/maap_environments.json'

REPO_NAME = 'register-job'
REPO_PATH = '/home/ubuntu/repo'
VERSION = 'master'
SUPPORTED_EXTENSIONS = ['py', 'java', 'sh']

# Docker container URL
CONTAINER_URL = 'registry.dit.maap-project.org/root/dps_plot:master'

# HySDS Settings
HYSDS_VERSION = "v4.0"
MOZART_URL = 'https://[MOZART_IP]/mozart/api/v0.2'
MOZART_V1_URL = 'https://[MOZART_IP]/mozart/api/v0.1'  # new from sister
GRQ_URL = 'http://[GRQ_IP]:8878/api/v0.1'  # new from sister
DEFAULT_QUEUE = 'test-job_worker-large'
LW_QUEUE = 'system-jobs-queue'
HYSDS_LW_VERSION = 'v0.0.5'
GRQ_REST_URL = 'http://[GRQ_IP]/api/v0.1'
S3_CODE_BUCKET = 's3://[S3_BUCKET_NAME]'
DPS_MACHINE_TOKEN = ''

# FASTBROWSE API
TILER_ENDPOINT = 'https://d852m4cmf5.execute-api.us-east-1.amazonaws.com'

# 3D Tiles API
DATA_SYSTEM_SERVICES_API_BASE = 'https://llxbmdibvf.execute-api.us-east-1.amazonaws.com/test'
DATA_SYSTEM_FILES_PATH = '/file-staging/nasa-map/'

# CAS
CAS_SECRET_KEY = ''
CAS_SERVER_NAME = 'https://auth.dit.maap-project.org/cas'
CAS_AFTER_LOGIN = 'api.members_self'
CAS_PROXY_DECRYPTION_TOKEN = ''

# Query Service
QS_STATE_MACHINE_ARN = 'arn:aws:states:us-east-1:532321095167:stateMachine:maap-api-query-service-dev-RunQuery'
QS_RESULT_BUCKET = 'maap-api-query-service-dev-query-results'

# AWS
AWS_REGION = 'us-east-1'
WORKSPACE_BUCKET = ''
WORKSPACE_BUCKET_ARN = ''
WORKSPACE_MOUNT_PRIVATE = 'my-private-bucket'
WORKSPACE_MOUNT_PUBLIC = 'my-public-bucket'
WORKSPACE_MOUNT_SHARED = 'shared-buckets'
AWS_SHARED_WORKSPACE_BUCKET_PATH = 'shared'
AWS_REQUESTER_PAYS_BUCKET_ARN = 'arn:aws:iam::???:role/???'

# DB
DATABASE_URL = 'postgresql://maapuser:mysecretpassword@db/maap'

# SMTP
SMTP_HOSTNAME = 'my_smtp_hostname'
SMTP_PORT = 9999
SMTP_USERNAME = 'my_smtp_username'
SMTP_PASSWORD = 'my_smtp_password'
SMTP_DEBUG_LEVEL = 1

# EMAIL ADDRESSES
EMAIL_NO_REPLY = ""
EMAIL_SUPPORT = ""
EMAIL_ADMIN = ""
EMAIL_JPL_ADMINS = ""  # Use a comma to delimit emails, if more than one

# PORTAL PATHS
PORTAL_ADMIN_DASHBOARD_PATH = ''
