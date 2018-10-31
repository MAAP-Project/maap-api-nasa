#!/usr/bin/python                                                                

import os
import sys
import logging

activate_this = '/var/www/maapapi/venv/bin/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))


logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/var/www/maapapi/")
#sys.path.append('/var/www/maapapi/venv/')
###

#os.environ.setdefault("PYTHONPATH", "/var/www/maapapi")

from api.maapapp import app as application
