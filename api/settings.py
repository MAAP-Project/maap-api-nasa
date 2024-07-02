import os

def str2bool(v):
  return v.lower() in ("y", "yes", "true", "t", "1")


MAAP_API_URL = os.getenv('MAAP_API_URL', "http://localhost:5000/api")
PROJECT_QUEUE_PREFIX = os.getenv('PROJECT_QUEUE_PREFIX', "maap")
API_HOST_URL = os.getenv('API_HOST_URL', 'http://0.0.0.0:5000/')

# Flask settings
FLASK_SERVER_NAME = os.getenv('FLASK_SERVER_NAME', 'localhost:5000')
FLASK_DEBUG = str2bool(os.getenv('FLASK_DEBUG', 'True'))  # Do not use debug mode in production

# Flask-Restplus settings
RESTPLUS_SWAGGER_UI_DOC_EXPANSION = os.getenv('RESTPLUS_SWAGGER_UI_DOC_EXPANSION', 'list')
RESTPLUS_VALIDATE = str2bool(os.getenv('RESTPLUS_VALIDATE', 'True'))
RESTPLUS_MASK_SWAGGER = str2bool(os.getenv('RESTPLUS_MASK_SWAGGER', 'False'))
RESTPLUS_ERROR_404_HELP = str2bool(os.getenv('RESTPLUS_ERROR_404_HELP', 'False'))

CMR_TOKEN_SERVICE_URL = os.getenv('CMR_TOKEN_SERVICE_URL', 'https://cmr.earthdata.nasa.gov/legacy-services/rest/tokens')

# MAAP DEV
CMR_URL = os.getenv('CMR_URL', 'https://cmr.maap-project.org')
CMR_API_TOKEN = os.getenv('CMR_API_TOKEN', '')
CMR_CLIENT_ID = os.getenv('CMR_CLIENT_ID','')
###
# Inherited from sister, currently not used on MAAP
# TODO: Remove references in code
CMR_PROVIDER = os.getenv('CMR_PROVIDER', 'MAAP')
UMM_C_VERSION = os.getenv('UMM_C_VERSION', '1.9')
UMM_G_VERSION = os.getenv('UMM_G_VERSION', '1.6')
# END Sister inherited section
###
MAAP_WMTS_XML = os.getenv('MAAP_WMTS_XML', '/maap-api-nasa/api/maap.wmts.xml')
MAAP_EDL_CREDS = os.getenv('MAAP_EDL_CREDS','')

# GIT settings
GIT_REPO_URL = os.getenv('GIT_REPO_URL','https://gitlab-ci-token:$TOKEN@repo.dit.maap-project.org/root/register-job.git')
GIT_API_URL = os.getenv('GIT_API_URL', 'https://repo.dit.maap-project.org/api/v4/projects')
REGISTER_JOB_REPO_ID = os.getenv('REGISTER_JOB_REPO_ID', '')  # Enter project ID for register job repo

# GTILAB Settings
GITLAB_TOKEN = os.getenv('GITLAB_TOKEN', 'foobar')
GITLAB_API_TOKEN = os.getenv('GITLAB_API_TOKEN','')  # New setting inherited from sister, remove comment after API is stable

MAAP_ENVIRONMENT_FILE = os.getenv('MAAP_ENVIRONMENT_FILE', 'https://raw.githubusercontent.com/MAAP-Project/maap-jupyter-ide/develop/maap_environments.json')

REPO_NAME = os.getenv('REPO_NAME', 'register-job')
REPO_PATH = os.getenv('REPO_PATH', '/home/ubuntu/repo')
VERSION = os.getenv('VERSION', 'master')
SUPPORTED_EXTENSIONS = os.getenv('SUPPORTED_EXTENSIONS', 'py,java,sh').split(',')

# Docker container URL
CONTAINER_URL = os.getenv('CONTAINER_URL', 'registry.dit.maap-project.org/root/dps_plot:master')

# HySDS Settings
HYSDS_VERSION = os.getenv('HYSDS_VERSION', "v4.0")
MOZART_URL = os.getenv('MOZART_URL', 'https://[MOZART_IP]/mozart/api/v0.2')
MOZART_V1_URL = os.getenv('MOZART_V1_URL', 'https://[MOZART_IP]/mozart/api/v0.1')  # new from sister
GRQ_URL = os.getenv('GRQ_URL', 'http://[GRQ_IP]:8878/api/v0.1')  # new from sister
DEFAULT_QUEUE = os.getenv('DEFAULT_QUEUE', 'test-job_worker-large')
LW_QUEUE = os.getenv('LW_QUEUE', 'system-jobs-queue')
HYSDS_LW_VERSION = os.getenv('HYSDS_LW_VERSION', 'v1.2.2')
GRQ_REST_URL = os.getenv('GRQ_REST_URL', 'http://[GRQ_IP]/api/v0.1')
S3_CODE_BUCKET = os.getenv('S3_CODE_BUCKET', 's3://[S3_BUCKET_NAME]')
DPS_MACHINE_TOKEN = os.getenv('DPS_MACHINE_TOKEN', '')

# FASTBROWSE API
TILER_ENDPOINT = os.getenv('TILER_ENDPOINT', 'https://d852m4cmf5.execute-api.us-east-1.amazonaws.com')

# 3D Tiles API
DATA_SYSTEM_SERVICES_API_BASE = os.getenv('DATA_SYSTEM_SERVICES_API_BASE', 'https://llxbmdibvf.execute-api.us-east-1.amazonaws.com/test')
DATA_SYSTEM_FILES_PATH = os.getenv('DATA_SYSTEM_FILES_PATH', '/file-staging/nasa-map/')

# CAS
CAS_SECRET_KEY = os.getenv('CAS_SECRET_KEY', '')
CAS_SERVER_NAME = os.getenv('CAS_SERVER_NAME', 'https://auth.dit.maap-project.org/cas')
CAS_AFTER_LOGIN = os.getenv('CAS_AFTER_LOGIN', 'api.members_self')
CAS_PROXY_DECRYPTION_TOKEN = os.getenv('CAS_PROXY_DECRYPTION_TOKEN', '')

# Query Service
QS_STATE_MACHINE_ARN = os.getenv('QS_STATE_MACHINE_ARN', 'arn:aws:states:us-east-1:532321095167:stateMachine:maap-api-query-service-dev-RunQuery')
QS_RESULT_BUCKET = os.getenv('QS_RESULT_BUCKET', 'maap-api-query-service-dev-query-results')

# AWS
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
WORKSPACE_BUCKET = os.getenv('WORKSPACE_BUCKET', '')
WORKSPACE_BUCKET_ARN = os.getenv('WORKSPACE_BUCKET_ARN', '')
WORKSPACE_MOUNT_PRIVATE = os.getenv('WORKSPACE_MOUNT_PRIVATE', 'my-private-bucket')
WORKSPACE_MOUNT_PUBLIC = os.getenv('WORKSPACE_MOUNT_PUBLIC', 'my-public-bucket')
WORKSPACE_MOUNT_SHARED = os.getenv('WORKSPACE_MOUNT_SHARED', 'shared-buckets')
WORKSPACE_MOUNT_TRIAGE = os.getenv('WORKSPACE_MOUNT_TRIAGE', 'triaged-jobs')
WORKSPACE_MOUNT_SUCCESSFUL_JOBS = os.getenv('WORKSPACE_MOUNT_SUCCESSFUL_JOBS', 'dps_output')
AWS_SHARED_WORKSPACE_BUCKET_PATH = os.getenv('AWS_SHARED_WORKSPACE_BUCKET_PATH', 'shared')
AWS_TRIAGE_WORKSPACE_BUCKET_PATH = os.getenv('AWS_TRIAGE_WORKSPACE_BUCKET_PATH', 'dataset/triaged_job')
AWS_REQUESTER_PAYS_BUCKET_ARN = os.getenv('AWS_REQUESTER_PAYS_BUCKET_ARN', 'arn:aws:iam::???:role/???')

# DB
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://maapuser:mysecretpassword@db/maap')

# SMTP
SMTP_HOSTNAME = os.getenv('SMTP_HOSTNAME', 'my_smtp_hostname')
SMTP_PORT = int(os.getenv('SMTP_PORT', '9999'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', 'my_smtp_username')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'my_smtp_password')
SMTP_DEBUG_LEVEL = int(os.getenv('SMTP_DEBUG_LEVEL', 1))

# EMAIL ADDRESSES
EMAIL_NO_REPLY = os.getenv('EMAIL_NO_REPLY', "")
EMAIL_SUPPORT = os.getenv('EMAIL_SUPPORT', "")
EMAIL_ADMIN = os.getenv('EMAIL_ADMIN', "")
EMAIL_JPL_ADMINS = os.getenv('EMAIL_JPL_ADMINS', "")  # Use a comma to delimit emails, if more than one

# PORTAL PATHS
PORTAL_ADMIN_DASHBOARD_PATH = os.getenv('PORTAL_ADMIN_DASHBOARD_PATH', '')

CLIENT_SETTINGS = {
    "maap_endpoint": {
        "search_granule_url": "cmr/granules",
        "search_collection_url": "cmr/collections",
        "algorithm_register": "mas/algorithm",
        "algorithm_build": "dps/algorithm/build",
        "mas_algo": "mas/algorithm",
        "dps_job": "dps/job",
        "wmts": "wmts",
        "member": "members/self",
        "member_dps_token": "members/dps/userImpersonationToken",
        "requester_pays": "members/self/awsAccess/requesterPaysBucket",
        "edc_credentials": "members/self/awsAccess/edcCredentials/{endpoint_uri}",
        "s3_signed_url": "members/self/presignedUrlS3/{bucket}/{key}",
        "workspace_bucket_credentials": "members/self/awsAccess/workspaceBucket"
    },
    "service": {
        "maap_token": "some-token",
        "tiler_endpoint": "https://8e9mu91qr6.execute-api.us-east-1.amazonaws.com/production",
    },
    "search": {
        "indexed_attributes" : [
            "site_name,Site Name,string",
            "data_format,Data Format,string",
            "track_number,Track Number,float",
            "polarization,Polarization,string",
            "dataset_status,Dataset Status,string",
            "geolocated,Geolocated,boolean",
            "spat_res,Spatial Resolution,float",
            "samp_freq,Sampling Frequency,float",
            "acq_mode,Acquisition Mode,string",
            "band_ctr_freq,Band Center Frequency,float",
            "freq_band_name,Frequency Band Name,string",
            "swath_width,Swath Width,float",
            "field_view,Field of View,float",
            "laser_foot_diam,Laser Footprint Diameter,float",
            "pass_number,Pass Number,int",
            "revisit_time,Revisit Time,float",
            "flt_number,Flight Number,int",
            "number_plots,Number of Plots,int",
            "plot_area,Plot Area,float",
            "subplot_size,Subplot Size,float",
            "tree_ht_meas_status,Tree Height Measurement Status,boolean",
            "br_ht_meas_status,Breast Height Measurement Status,boolean",
            "br_ht,Breast Height,float",
            "beam,Beam,int",
            "intensity_status,intensity Status,boolean",
            "ret_dens,Return Density,float",
            "ret_per_pulse,Returns Per Pulse,string",
            "min_diam_meas,Minimum Diameter Measured,float",
            "allometric_model_appl,Allometric Model Applied,string",
            "stem_mapped_status,Stem Mapped Status,boolean",
            "br_ht_modeled_status,Breast Height Modeled Status,boolean",
            "flt_alt,Flight Altitude,float",
            "gnd_elev,Ground Elevation,float",
            "hdg,Heading,float",
            "swath_slant_rg_st_ang,Swath Slant Range Start Angle,float",
            "azm_rg_px_spacing,Azimuth Range Pixel Spacing,float",
            "slant_rg_px_spacing,Slant Range Pixel Spacing,float",
            "acq_type,Acquisition Type,string",
            "orbit_dir,Orbit Direction,string",
            "modis_pft,MODIS PFT,string",
            "wwf_ecorgn,WWF Ecoregion,string",
            "band_ctr_wavelength,Band Center Wavelength,float",
            "swath_slant_rg_end_ang,Swath Slant Range End Angle,float"
        ]
    }
}
