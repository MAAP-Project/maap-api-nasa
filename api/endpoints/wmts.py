import logging
import json
import os
import pystache
import requests
from flask import request
from flask_restplus import Resource
from api.restplus import api
import api.utils.auth_util as auth
from api import settings
import api.endpoints.cmr as cmr
from maap.Result import Granule
from collections import OrderedDict
from xmljson import BadgerFish
bf = BadgerFish(dict_type=OrderedDict)
from xml.etree.ElementTree import fromstring

log = logging.getLogger(__name__)

ns = api.namespace('wmts', description='Retrieve tiles')

@ns.route('/GetTile')
class GetTile(Resource):

    # TODO(aimee): Revert this comment of @auth.token_required
    # @auth.token_required
    def get(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        granule_ur = request.args.get("granule_ur")
        log.info('request.args {}'.format(request.args))
        response_body = dict()

        if not granule_ur:
            message = "required param granule_ur not provided in request"
            response_body["code"] = 422
            response_body["message"] = message
            response_body["error"] = message
            response_body["success"] = False            

        try:
            cmr_url = os.path.join(settings.CMR_URL, 'search', 'granules')
            cmr_resp = requests.get(cmr_url, headers=cmr.get_search_headers(), params=cmr.parse_query_string(request.query_string))
            granule = Granule(json.loads(cmr_resp.text)['feed']['entry'][0], 'aws_access_key_id', 'aws_secret_access_key')
            urls = granule['links']
            browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))[0]['href']
            response_body["message"] = "Successfully fetched browse image for {}".format(granule_ur)
            response_body["browse"] = browse_file
            response_body["code"] = 200
            response_body["success"] = True
        except Exception as ex:
            log.error(str(ex))
            log.error(json.dumps(ex, indent=2))
            response_body["code"] = 500
            response_body["message"] = "Failed to fetch tiles for {}".format(granule_ur)
            response_body["error"] = str(ex)
            response_body["success"] = False

        return response_body

@ns.route('/GetCapabilities')
class GetCapabilities(Resource):

    def generate_capabilities(self, granule):
        urls = granule['links']
        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))[0]['href']
        if 'LVIS' in granule['dataset_id']:
            layer_title = 'LVIS'
        elif 'UAVSAR' in granule['dataset_id']:
            layer_title = 'UAVSAR'
        r = requests.get(f"{settings.TILER_ENDPOINT}/metadata?url={browse_file}")
        meta = r.json()
        bbox = meta["bounds"]["value"]
        ROOT = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(ROOT, 'capabilities_template.xml'), 'r') as file:
            template = file.read()
        context = {
          'service_title': 'MAAP WMTS',
          'provider': 'MAAP API',
          'provider_url': '{}/api/'.format(settings.FLASK_SERVER_NAME),
          'base_url': '{}/api/'.format(settings.FLASK_SERVER_NAME),
          'layer_title': layer_title,
          'bounds': [ bbox[0], bbox[1], bbox[2], bbox[3] ],
          'content_type': 'tif',
          'ext': 'tif',
          'zoom': 10
        }
        xml_string = pystache.render(template, context)
        return bf.data(fromstring(xml_string))


    # TODO(aimee): Revert this comment of @auth.token_required
    # @auth.token_required
    def get(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        granule_ur = request.args.get("granule_ur")
        log.info('request.args {}'.format(request.args))
        response_body = dict()

        if not granule_ur:
            message = "required param granule_ur not provided in request"
            response_body["code"] = 422
            response_body["message"] = message
            response_body["error"] = message
            response_body["success"] = False

        try:
            cmr_url = os.path.join(settings.CMR_URL, 'search', 'granules')
            cmr_resp = requests.get(cmr_url, headers=cmr.get_search_headers(), params=cmr.parse_query_string(request.query_string))
            granule = Granule(json.loads(cmr_resp.text)['feed']['entry'][0], 'aws_access_key_id', 'aws_secret_access_key')
            get_capabilities_object = self.generate_capabilities(granule)
            # Return get capabilities
            response_body["message"] = "Successfully generated capabilities for {}".format(granule_ur)
            response_body["body"] = get_capabilities_object
            response_body["code"] = 200
            response_body["success"] = True
        except Exception as ex:
            log.error(str(ex))
            log.error(json.dumps(ex, indent=2))
            response_body["code"] = 500
            response_body["message"] = "Failed to fetch tiles for {}".format(granule_ur)
            response_body["error"] = str(ex)
            response_body["success"] = False

        return response_body
