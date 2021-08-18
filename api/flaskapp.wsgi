#!/usr/bin/python

import sys
import logging
import os
from pathlib import Path
top = str(Path(__file__ + '../..').resolve()).replace('/api', '')

logging.basicConfig(stream=sys.stderr)
sys.path.insert(0, top)

activate_this = os.path.join(top, 'venv', 'bin', 'activate_this.py')

with open(activate_this) as f:
    code = compile(f.read(), activate_this, 'exec')
    exec(code, dict(__file__=activate_this))

from api.maapapp import app as application