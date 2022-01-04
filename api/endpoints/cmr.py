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

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace('cmr', description='Operations related to CMR')


@ns.route('/collections')
class CmrCollection(Resource):

    def get(self):
        """
        CMR collections

            Examples:

            Find collection by concept id
            https://api.dit.maap-project.org/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP

            With multiple dataset ids
            https://api.dit.maap-project.org/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP&concept_id[]=C1200090707-NASA_MAAP

            Find collections by bounding box
            https://api.dit.maap-project.org/api/cmr/collections?bounding_box=-35.4375,-55.6875,-80.4375,37.6875

        For a comprehensive list of collection search examples, see: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html#collection-search-by-parameters
        """

        resp = req(request.query_string, 'collections')

        return respond(resp)


@ns.route('/collections/shapefile')
class ShapefileUpload(Resource):

    def post(self):
        """
        CMR collections search by shape file
            File input expected: .zip including .shp, .dbf, and .shx file
        """

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

    def get(self):
        """
        CMR granules

            Examples:

            Find granules by granule ur
            https://api.dit.maap-project.org/api/cmr/granules?granule_ur=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin

            With multiple dataset ids
            https://api.dit.maap-project.org/api/cmr/granules?granule_ur[]=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin&granule_ur[]=biosar1_105_kz.tiff

            Find granules by instrument
            https://api.dit.maap-project.org/api/cmr/granules?instrument=UAVSAR


        For a comprehensive list of granule search examples, see: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html#granule-search-by-parameters
        """

        resp = req(request.query_string, 'granules')

        return respond(resp)


def get_search_headers():
    accept = next(iter(request.headers.getlist('accept') or ['application/json']), ['application/json'])

    return {
            'Accept': accept,
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }


# Preserves keys that occur more than once, as allowed for in CMR
def parse_query_string(qs):
    return urlparse.parse_qs(qs)


def req(query_string, search_type):
    url = os.path.join(settings.CMR_URL, 'search', search_type)
    parms = parse_query_string(query_string)

    # If an alternate cmr_host is specified in a search request,
    # use that in place of the default config 'CMR_URL' setting.
    if 'cmr_host'.encode('utf-8') in parms.keys():
        cmr_host = parms.pop('cmr_host'.encode('utf-8'))[0]
        url = os.path.join('https://' + cmr_host.decode('utf-8'), 'search', search_type)

    return requests.get(url, headers=get_search_headers(), params=parms)


def respond(response):
    response_text = response.text if response.status_code == 200 else 'CMR Error %s' % response.text

    if response.text == '':
        return {}
    else:
        if "xml" in response.headers['content-type']:
            return response_text, response.status_code, {'Content-Type': 'application/xml'}
        else:
            return json.loads(response.text)

