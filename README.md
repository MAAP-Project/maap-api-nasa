# NASA MAAP API
The joint ESA-NASA Multi-Mission Algorithm and Analysis Platform (MAAP) focuses on developing a collaborative data system enabling collocated data, processing, and analysis tools for NASA and ESA datasets. The NASA MAAP API adheres to the joint ESA-NASA MAAP API specification currently in development. This joint architectural approach enables NASA and ESA to each run independent MAAPs, while ultimately sharing common facilities to share and integrate collocated platform services.

Development server: https://api.dit.maap-project.org/api

## I. Local development using docker
Set your FERNET_KEY environment variable to be a key, doesn't necessarily need to be valid 
```bash
cd docker
docker-compose -f docker-compose-local.yml up
```
Once you make code changes you might need to delete your maap-api-nasa docker image for these code changes to be reflected. If you are getting a network not found error, try running `docker-compose -f docker-compose-local.yml up --force-recreate`
You may also need to set `DATABASE_URL` to postgresql://maapuser:mysecretpassword@host.docker.internal/maap in settings.py
If you make changes to the settings, rebuild with `docker-compose -f docker-compose-local.yml build --no-cache`

## II. Local development using poetry and virtualenv

**Prerequisites:**
* poetry
  * https://python-poetry.org/docs/#installation 
* postgresql
  * Linux: `sudo apt-get install postgresql python-psycopy2 libpq-dev`
  * Mac OSx: `brew install postgresql`
* python3.9+

```bash
cd maap-api-nasa
poetry install
```

### First run: Configure the database.

1. Add a new user called `maapuser` (A fix for 'role <username> does not exist')
   > **_NOTE:_**  You may need to use `sudo -u postgres` before postgres commands.
   ```bash
   createuser maapuser
   ```

2. Create an empty postgres db (maap) (a fix for 'database maap does not exist'):
    ```bash
    createdatabase maap
    ```

3. OPTIONAL: PyCharm configuration, if using the PyCharm IDE:

- Script path: `./api/maapapp.py`
- Environment variables: `PYTHONUNBUFFERED=1`
- Python interpreter: `Python 3.9`
- Working directory: `./api`

#### (Obsolete?) Config Titiler endpoint and maap-api-host

In the settings.py (i.e., maap-api-nasa/api/settings.py):

```python
# settings.py
API_HOST_URL = 'http://0.0.0.0:5000/' # For local testing

# ...

# The endpoint obtained after doing Titiler deployment
TILER_ENDPOINT = 'https://XXX.execute-api.us-east-1.amazonaws.com'
# If running the tiler locally, this can be TILER_ENDPOINT = 'http://localhost:8000'
```

### Run the app:

```bash
poetry shell
FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
```

Some issues you may experience while running the above line:

* Allowing using postgres without login (A fix for 'fe_sendauth: no password supplied'):

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

### Running tests

When using docker-compose to start the app it is possible to run the tests locally if you first
update the settings.py `DATABASE_URL` value to specify `localhost` as the servername instead of `db`
(DO NOT check in this change).

```bash
python -m unittest test/api/endpoints/test_wmts_get_tile.py
```

If you are running the latest version of Titiler, use the following local test scripts:
while keeping the server in the previous step running (i.e., local maap-api-nasa). Open a new terminal

```bash
poetry env use $(poetry env info -e)

#If you are running the latest version of Titiler, then use the following test scripts:
python -m unittest -v test/api/endpoints/test_wmts_get_tile_new_titiler.py
python -m unittest -v test/api/endpoints/test_wmts_get_capabilities_new_titiler.py
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
