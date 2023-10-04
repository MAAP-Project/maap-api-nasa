# NASA MAAP API
The joint ESA-NASA Multi-Mission Algorithm and Analysis Platform (MAAP) focuses on developing a collaborative data system enabling collocated data, processing, and analysis tools for NASA and ESA datasets. The NASA MAAP API adheres to the joint ESA-NASA MAAP API specification currently in development. This joint architectural approach enables NASA and ESA to each run independent MAAPs, while ultimately sharing common facilities to share and integrate collocated platform services.

Development server: https://api.dit.maap-project.org/api

## I. Local development using docker

```bash
cd docker
docker-compose up
```

## II. Local development using python virtualenv

**Prerequisites:**

* postgresql
  * Linux: `sudo apt-get install postgresql python-psycopy2 libpq-dev`
  * Mac OSx: `brew install postgresql`
* pip, python3.7 and virtualenv

```bash
python3 -m venv venv
source maap-api-nasa/bin/activate
pip3 install -r requirements.txt
```

### First run: Configure the database.

1. Add the new postgres user (A fix for 'role <username> does not exist'):

Note: You may need to use `sudo -u postgres ` before postgres commands.

```bash
# For example
# $ create user tonhai # or
# $ sudo -u postgres createuser tonhai
createuser <current_user>
```

2. create an empty postgres db (maap_dev) (a fix for 'database maap_dev does not exist'):

```bash
psql # or $ sudo -u postgres psql
(in postgres shell): create database maap_dev;
(in postgres shell): \q
```

3. OPTIONAL: PyCharm configuration, if using the PyCharm IDE:

- Script path: `./api/maapapp.py`
- Environment variables: `PYTHONUNBUFFERED=1`
- Python interpreter: `Python 3.7`
- Working directory: `./api`

#### Config Titiler endpoint and maap-api-host

In the settings.py (i.e., maap-api-nasa/api/settings.py):

```python
# settings.py
API_HOST_URL = 'http://0.0.0.0:5000/' # For local testing

# ...

# The endpoint obtained after doing Titiler deployment
TILER_ENDPOINT = 'https://XXX.execute-api.us-east-1.amazonaws.com'
# If running the tiler locally, this can be TILER_ENDPOINT = 'http://localhost:8000'
```

### You can run then app:

```bash
FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
```

### Some issues you may experience while running the above line:

#### Allowing using postgres without login (A fix for 'fe_sendauth: no password supplied'):

```bash
sudo vi /etc/postgresql/9.5/main/pg_hba.conf #(the location may be different depend on OS and postgres version)
```

```
# Reconfig as follows:
    local   all     all     trust
    host    all     all     127.0.0.1/32    trust
    host    all     all     ::1/0           trust
# Save pg_hba.conf
```

```bash
# Restart postgresql
sudo /etc/init.d/postgresql reload
sudo /etc/init.d/postgresql start
```

#### 5. Rerun:

```bash
# Run the maap-api-nasa services locally
FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
```

And run a test:

```bash
python3 -m unittest test/api/endpoints/test_wmts_get_tile.py
```

### If you are running the latest version of Titiler, use the following local test scripts:

while keeping the server in the previous step running (i.e., local maap-api-nasa). Open a new terminal

```bash
source maap-api-nasa/bin/activate # or whatever environment name you choose in the previous step

#If you are running the latest version of Titiler, then use the following test scripts:
python3 -m unittest -v test/api/endpoints/test_wmts_get_tile_new_titiler.py
python3 -m unittest -v test/api/endpoints/test_wmts_get_capabilities_new_titiler.py
```

## III. User Accounts

A valid MAAP API token must be included in the header for any API request. An [Earthdata account](https://uat.urs.earthdata.nasa.gov) is required to access the MAAP API. To obtain a token, URS credentials must be provided as shown below:

```bash
curl -X POST --header "Content-Type: application/json" -d "{ \"username\": \"urs_username\", \"password\": \"urs_password\" }" https://api.dit.maap-project.org/token
```

### Comments:

- After running the local maap-api-nasa, go to http://0.0.0.0:5000/api to see the APIs.

- Or running the your own test scripts with:

```bash
curl -X POST --header "Content-Type: application/json" -d "{ \"username\": \"urs_username\", \"password\": \"urs_password\" }" http://0.0.0.0:5000/token
```
