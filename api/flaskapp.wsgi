#!/usr/bin/python                                                                

import sys
import logging

logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/var/www/maapapi/")

from api.maapapp import app as application
