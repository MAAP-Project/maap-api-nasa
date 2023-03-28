import logging
import os
import requests
import shapefile
from api import settings
from zipfile import ZipFile
import tempfile
from flask import request, json, Response, stream_with_context
from flask_restx import Resource
from flask_api import status
from api.restplus import api
from api.cas.cas_auth import get_authorized_user, edl_federated_request
from api.maap_database import db
from api.models.member import Member
from urllib import parse


try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace('cmr', description='Operations related to CMR')


@ns.route('/granules')
class CmrGranules(Resource):

    def get(self):
        """
        CMR granules

            Examples:

            Find granules by granule ur
            https://api.maap.xyz/api/cmr/granules?granule_ur=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin

            With multiple dataset ids
            https://api.maap.xyz/api/cmr/granules?granule_ur[]=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin&granule_ur[]=biosar1_105_kz.tiff

            Find granules by instrument
            https://api.maap.xyz/api/cmr/granules?instrument=UAVSAR


        For a comprehensive list of granule search examples, see: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html#granule-search-by-parameters
        """

        url = os.path.join(settings.CMR_URL, 'search', 'granules')
        resp = requests.get(url, headers=get_search_headers(), params=parse_query_string(request.query_string), verify=False)

        return respond(resp)

    def put(self):
        """
        CMR granule ingestion
            Expects granule metadata in JSON format
            CMR granule validation is hit before ingestion
            If granule fails validation, validation errors are returned
                prior to ingestion

        For CMR granule ingestion documentation, see: https://cmr.earthdata.nasa.gov/ingest/site/docs/ingest/api.html#create-update-granule
        """

        response_body = dict()

        try:
            if not request.is_json or not request.get_json():
                log.error('Validation attempt with no json')
                raise Exception('Expecting a json. No json uploaded')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with granule metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        try:
            meta = request.get_json()
            if 'GranuleUR' not in meta.keys():
                log.error('Granule metadata missing GranuleUR')
                raise Exception('GranuleUR is required for granule validation. No GranuleUR in granule metadata')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with granule metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        validation_response = validate(meta)

        if validation_response.status_code != 200:
            log.error(f'Granule metadata failed validation with errors: {validation_response.text}')
            resp = validation_response
        else:
            if validation_response.text:
                log.debug(f'Granule metadata validation succeeded with warnings: {validation_response.text}')
            url = os.path.join(settings.CMR_URL, 'ingest', 'providers', settings.CMR_PROVIDER, 'granules', meta['GranuleUR'])
            resp = requests.put(url, json=meta, headers=get_ingest_headers('granule'))    
        return respond(resp)


@ns.route('/granules/validate')
class CmrGranuleValidation(Resource):
    def post(self):
        """
        CMR granule validation. This may be utilized in the future for the CMR Delivery
         DPS Job.

        CMR granule validation
            Validates CMR granule metadata
            Returns status code 200 with a list of any warnings on successful 
                validation, status code 400 with a list of validation errors 
                on failed validation

        NOTE: A collection is required when validating the granule. The granule 
            being validated can either refer to an existing collection in the 
            CMR or the collection can be sent in a multi-part HTTP request.
        
        For CMR granule validation documentation, see: https://cmr.earthdata.nasa.gov/ingest/site/docs/ingest/api.html#validate-granule
        """
        response_body = dict()

        try:
            if not request.is_json:
                log.error('Validation attempt with no json')
                raise Exception('Expecting a json. No json uploaded')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with granule metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500
            
        meta = request.get_json()

        try:
            if 'GranuleUR' not in meta.keys():
                log.error('Granule metadata missing GranuleUR')
                raise Exception('GranuleUR required for validation. No GranuleUR in collection metadata')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with granule metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        resp = validate(meta)
        return respond(resp)

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

    def put(self):
        """
        CMR collection ingestion
            Expects collection metadata in JSON format
            CMR collection validation is hit before ingestion
            If collection fails validation, validation errors are returned
                prior to ingestion

        For CMR collection ingestion documentation, see: https://cmr.earthdata.nasa.gov/ingest/site/docs/ingest/api.html#create-update-collection
        """
        response_body = dict()

        try:
            if not request.is_json or not request.get_json():
                log.error('Validation attempt with no json')
                raise Exception('Expecting a json. No json uploaded')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with collection metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        try:
            meta = request.get_json()
            if 'ShortName' not in meta.keys():
                log.error('Collection metadata missing ShortName')
                raise Exception('ShortName is required for collection validation. No ShortName in collection metadata')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with collection metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        validation_response = validate(meta)

        if validation_response.status_code != 200:
            log.error(f'Collection metadata failed validation with errors: {validation_response.text}')
            resp = validation_response
        else:
            if validation_response.text:
                log.debug(f'Collection metadata validation succeeded with warnings: {validation_response.text}')
            url = os.path.join(settings.CMR_URL, 'ingest', 'providers', settings.CMR_PROVIDER, 'collections', meta['ShortName'])
            resp = requests.put(url, json=meta, headers=get_ingest_headers('collection'))    
        return respond(resp)


@ns.route('/collections/validate')
class CmrCollectionValidation(Resource):
    def post(self):
        """
        CMR collection validation
            Validates CMR collection metadata
            Returns status code 200 with a list of any warnings on successful 
                validation, status code 400 with a list of validation errors 
                on failed validation
        
        For CMR collection validation documentation, see: https://cmr.earthdata.nasa.gov/ingest/site/docs/ingest/api.html#validate-collection
        """
        response_body = dict()
        try:
            if not request.is_json:
                log.error('Validation attempt with no json')
                raise Exception('Expecting a json. No json uploaded')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with collection metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500
        
        try:
            meta = request.get_json()
            if 'ShortName' not in meta.keys():
                log.error('Collection metadata missing ShortName')
                raise Exception('ShortName is required for collection validation. No ShortName in collection metadata')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with collection metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

        resp = validate(meta)
        return respond(resp)


@ns.route('/collections/shapefile')
class ShapefileUpload(Resource):

    def post(self):
        """
        CMR collections search by shape file
            File input expected: .zip including .shp, .dbf, and .shx file
        """
        response_body = dict()

        try:
            if 'file' not in request.files:
                log.error('Upload attempt with no file')
                raise Exception('No file uploaded')
        except Exception as e:
            tb = traceback.format_exc()
            response_body["code"] = 500
            response_body["message"] = 'Error with collection metadata JSON'
            response_body["error"] = f'{e} Traceback: {tb}'
            return response_body, 500

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
        resp = requests.get(url, headers=get_search_headers(), params={'bounding_box': bbox}, verify=False)

        return respond(resp)

def validate(meta):
    '''
    Collection and granule metadata validation. Endpoints handle missing essential
    keys (ShortName or GranuleUR) from metadata. 
    '''
    base_url = os.path.join(settings.CMR_URL, 'ingest', 'providers', settings.CMR_PROVIDER, 'validate')
    if 'ShortName' in meta.keys():
        url = os.path.join(base_url, 'collection', meta['ShortName'])
        resp = requests.post(url, headers=get_ingest_headers('collection'), json=meta)
    elif 'GranuleUR' in meta.keys():
        url = os.path.join(base_url, 'granule', meta['GranuleUR'])
        resp = requests.post(url, headers=get_ingest_headers('granule'), json=meta)
    return resp

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


@ns.route('/granules/<string:file_uri>/data')
class CmrGranuleData(Resource):
    """
    CMR granule data

        Download granule by file URI
        file_uri: a UTF-8 encoded URI

        Example:
        https://api.maap-project.org/api/cmr/granules/https%3A%2F%2Fdata.ornldaac.earthdata.nasa.gov%2Fprotected%2Fgedi%2FGEDI_L3_Land_Surface_Metrics%2Fdata%2FGEDI03_elev_lowestmode_stddev_2019108_2020106_001_08.tif/data
    """

    def get(self, file_uri):
        response = edl_federated_request(parse.unquote(file_uri), stream=True)

        if response.status_code == status.HTTP_200_OK:
            return Response(
                response=stream_with_context(response.iter_content(chunk_size=1024 * 10)),
                content_type=response.headers.get('Content-Type'),
                direct_passthrough=True)
        else:
            # Propagate the error
            return response


def get_search_headers():
    accept = next(iter(request.headers.getlist('accept') or ['application/json']), ['application/json'])

    return {
            'Accept': accept,
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }

def get_ingest_headers(type):
    content_type = 'application/vnd.nasa.cmr.umm+json'
    if type == 'collection':
        content_type = f'{content_type};version={settings.UMM_C_VERSION}'
    elif type == 'granule':
        content_type = f'{content_type};version={settings.UMM_G_VERSION}'
    return {
        'Accept': 'application/json',
        'Content-Type': content_type,
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
    response_text = response.text if response.status_code == status.HTTP_200_OK else 'CMR Error %s' % response.text

    if response.text == '':
        return {}
    else:
        if "xml" in response.headers['content-type']:
            return response_text, response.status_code, {'Content-Type': 'application/xml'}
        else:
            return json.loads(response.text)
