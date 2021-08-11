MAAP_API_URL = "https://api.ops.maap-project.org/api"
PROJECT_QUEUE_PREFIX = "maap"

# Auth
APP_AUTH_KEY = "thisisthesecretkey"

# Flask settings
FLASK_SERVER_NAME = 'https://api.ops.maap-project.org'

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
MAAP_WMTS_XML = "/maap-api-nasa/api/maap.wmts.xml"

# GIT settings
GIT_REPO_URL = "https://oauth2:$TOKEN@repo.ops.maap-project.org/root/register-job.git"
MAAP_ENVIRONMENT_FILE = "https://raw.githubusercontent.com/MAAP-Project/maap-jupyter-ide/develop/maap_environments.json"

# GTILAB Settings
GITLAB_TOKEN = 'foobar'

REPO_NAME = "register-job"
REPO_PATH = "/var/www/maap-api-nasa/repo"
VERSION = "master"
SUPPORTED_EXTENSIONS = ["py", "java", "sh"]

# Docker container URL
CONTAINER_URL = "repo.ops.maap-project.org/root/dps_plot:master"

# HySDS Mozart
MOZART_URL = ""
DEFAULT_QUEUE = ""
LW_QUEUE = ""
HYSDS_LW_VERSION = ""
GRQ_REST_URL = ""
S3_CODE_BUCKET = ""

# FASTBROWSE API
TILER_ENDPOINT = ''

# CAS
CAS_SECRET_KEY = ''
CAS_SERVER_NAME = 'https://auth.nasa.maap.xyz/cas'
CAS_AFTER_LOGIN = 'api.members_self'
CAS_PROXY_DECRYPTION_TOKEN = ''
MAAP_EDL_CREDS = ''

# Query Service
QS_STATE_MACHINE_ARN = ''
QS_RESULT_BUCKET = ''

# AWS
AWS_REGION = 'us-east-1'
WORKSPACE_MOUNT_PRIVATE = 'my-private-bucket'
WORKSPACE_MOUNT_PUBLIC = 'my-public-bucket'
WORKSPACE_MOUNT_SHARED = 'shared-buckets'
AWS_SHARED_WORKSPACE_BUCKET_PATH = 'shared'

# DB
DATABASE_URL=''
