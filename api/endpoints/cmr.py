import logging
import os
import requests
import shapefile
from api import settings
from zipfile import ZipFile
import tempfile
from flask import request, json
from flask_restplus import Resource
from api.restplus import api
import api.utils.auth_util as auth

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace('cmr', description='Operations related to CMR')


@ns.route('/collections')
class CmrCollection(Resource):

    @auth.token_required
    def get(self):
        """
        CMR collections
        """

        url = os.path.join(settings.CMR_URL, 'search', 'collections')
        resp = requests.get(url, headers=get_search_headers(), params=parse_query_string(request.query_string))

        return respond(resp)


@ns.route('/collections/shapefile')
class ShapefileUpload(Resource):

    @auth.token_required
    def post(self):

        if 'file' not in request.files:
            log.error('Upload attempt with no file')
            raise Exception('No file uploaded')

        f = request.files['file']

        dst = tempfile.NamedTemporaryFile()
        f.save(dst)
        dst.flush()
        zipfile = ZipFile(dst.name)

        filenames = [y for y in sorted(zipfile.namelist()) for ending in ['dbf', 'prj', 'shp', 'shx'] if
                     y.endswith(ending)][:4]

        dbf, prj, shp, shx = [filename for filename in filenames]

        r = shapefile.Reader(
            shp=zipfile.open(shp),
            hx=zipfile.open(shx),
            dbf=zipfile.open(dbf))

        dst.close()

        bbox = ','.join(map(str, r.bbox))

        url = os.path.join(settings.CMR_URL, 'search', 'collections')
        resp = requests.get(url, headers=get_search_headers(), params={'bounding_box': bbox})

        return respond(resp)


@ns.route('/granules')
class CmrGranules(Resource):

    @auth.token_required
    def get(self):
        """
        CMR granules
        """

        url = os.path.join(settings.CMR_URL, 'search', 'granules')
        resp = requests.get(url, headers=get_search_headers(), params=parse_query_string(request.query_string))

        return respond(resp)


def get_search_headers():
    accept = next(iter(request.headers.getlist('accept') or ['application/json']), ['application/json'])

    return {
            'Accept': accept,
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }


#Preserves keys that occur more than once, as allowed for in CMR
def parse_query_string(qs):
    return urlparse.parse_qs(qs)


def respond(response):
    if response.status_code != 200:
        raise Exception('CMR Error %s' % response.text)
    if response.text == '':
        return {}
    else:
        if "xml" in response.headers['content-type']:
            return response.text, 200, {'Content-Type': 'application/xml'}
        else:
            return json.loads(response.text)

