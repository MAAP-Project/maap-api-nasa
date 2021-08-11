#!/usr/bin/python                                                                

import sys
import logging
import os

logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/var/www/maap-api-nasa/")

activate_this = os.path.join('/var/www/maap-api-nasa/venv', 'bin', 'activate_this.py')
#execfile(activate_this, dict(__file__=activate_this))

with open(activate_this) as f:
    code = compile(f.read(), activate_this, 'exec')
    exec(code, dict(__file__=activate_this))

from api.maapapp import app as application
