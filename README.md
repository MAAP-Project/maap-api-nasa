# NASA MAAP API
The joint ESA-NASA Multi-Mission Algorithm and Analysis Platform (MAAP) focuses on developing a collaborative data system enabling collocated data, processing, and analysis tools for NASA and ESA datasets. The NASA MAAP API adheres to the joint ESA-NASA MAAP API specification currently in development. This joint architectural approach enables NASA and ESA to each run independent MAAPs, while ultimately sharing common facilities to share and integrate collocated platform services.

Development server: https://api.dit.maap-project.org/api

## I. Getting Started

To run the MAAP API locally using PyCharm, create a Python Configuration with the following settings:

- Script path: `./api/maapapp.py`
- Environment variables: `PYTHONUNBUFFERED=1`
- Python interpreter: `Python 3.7`
- Working directory: `./api`

### Comments:

- Working directory is maap-api-nasa
- export PYTHONUNBUFFERED=1

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

## VI. Deployment

The MAAP API is written in [Flask](http://flask.pocoo.org/), and commonly deployed using [WSGI Middlewares](http://flask.pocoo.org/docs/1.0/quickstart/#hooking-in-wsgi-middlewares). This deployment guide targets Ubuntu 18.04 running Apache2 in AWS with [Let's Encrypt](https://letsencrypt.org/).

1. Install and enable [mod_wsgi](https://pypi.org/project/mod_wsgi/).
2. Create an app directory for MAAP API, typically under `/var/www`
3. Either clone this repository in the app directory, or [configure PyCharm to sync your local repository with your AWS VM](https://www.codementor.io/abhishake/pycharm-setup-for-aws-automatic-deployment-m7n8uu2n4).
4. Install Pip and Flask:
    - `apt-get install -y python3-pip`
    - `apt-get install -y python3-venv`
5. Create a virtual environment and activate it:
    - `python3 -m venv yourenvironment`
    - `source yourenvironment/bin/activate`
6. Configure Apache conf file to load our new Flask app using WSGI. If using Let's Encrypt, the conf file will likely be `/etc/apache2/sites-available/000-default-le-ssl.conf`. Below is a sample conf file used on https://api.dit.maap-project.org/api/:

    ```XML
    <IfModule mod_ssl.c>
    <VirtualHost *:443>
            # The ServerName directive sets the request scheme, hostname and port that
            # the server uses to identify itself. This is used when creating
            # redirection URLs. In the context of virtual hosts, the ServerName
            # specifies what hostname must appear in the request's Host: header to
            # match this virtual host. For the default virtual host (this file) this
            # value is not decisive as it is used as a last resort host regardless.
            # However, you must set it for any further virtual host explicitly.
            #ServerName www.example.com

            ServerAdmin webmaster@localhost
            WSGIDaemonProcess maapapi  python-home=/var/www/maapapi/venv
            WSGIScriptAlias / /var/www/maapapi/api/flaskapp.wsgi
            <Directory /var/www/maapapi/>
                WSGIProcessGroup maapapi
                WSGIApplicationGroup %{GLOBAL}
                Order allow,deny
                Allow from all
            </Directory>
           # Alias /static /var/www/FlaskApp/FlaskApp/static
           # <Directory /var/www/FlaskApp/FlaskApp/static/>
           #     Order allow,deny
           #     Allow from all
           # </Directory>

            # Available loglevels: trace8, ..., trace1, debug, info, notice, warn,
            # error, crit, alert, emerg.
            # It is also possible to configure the loglevel for particular
            # modules, e.g.
            #LogLevel info ssl:warn

            ErrorLog ${APACHE_LOG_DIR}/error.log
            CustomLog ${APACHE_LOG_DIR}/access.log combined

            # For most configuration files from conf-available/, which are
            # enabled or disabled at a global level, it is possible to
            # include a line for only one particular virtual host. For example the
            # following line enables the CGI configuration for this host only
            # after it has been globally disabled with "a2disconf".
            #Include conf-available/serve-cgi-bin.conf


    ServerName api.dit.maap-project.org
    SSLCertificateFile /etc/letsencrypt/live/api.dit.maap-project.org/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/api.dit.maap-project.org/privkey.pem
    Include /etc/letsencrypt/options-ssl-apache.conf
    </VirtualHost>
    </IfModule>
    ```
7. Restart Apache
    `service apache2 restart`

    ..
