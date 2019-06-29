import logging
import json
import os
import sys, traceback
import requests
from flask import Response, request, render_template_string
from flask_restplus import Resource
from api.restplus import api
import api.utils.auth_util as auth
from api import settings
import api.endpoints.cmr as cmr
from api.utils.Granule import Granule
from collections import OrderedDict
import xmltodict
from flask import redirect

log = logging.getLogger(__name__)

ns = api.namespace('wmts', description='Retrieve tiles')

# Load default collections
ROOT = os.path.dirname(os.path.abspath(__file__))
collections_json = open(os.path.join(ROOT, 'wmts_collections.json'), 'r').read()
default_collections = json.loads(collections_json)

cmr_search_granules_url = os.path.join(settings.CMR_URL, 'search', 'granules')
max_url_length = 8192

def get_collection_cogs(collection={}):
    """
    Given a collection object (name and version), request all granules
    for that collection and return a comma-list of all urls for browse
    links for that collection's granules.
    :return:
    """
    # TODO(aimee): It could be that more than 100 granules are
    # returned - but this would probably overload the tiler? We
    # need a better answer for collections with a large number
    # of granules.
    browse_urls = []
    cmr_query_dict = {
      'short_name': [ collection['short_name'] ],
      'version': [ collection['version'] ],
      'page_size': 100
    }
    if collection['additional_attributes']:
        cmr_query_dict['attribute[]'] = ','.join(collection['additional_attributes'][0])
    search_headers = cmr.get_search_headers()
    search_headers['Accept'] = 'application/json'
    cmr_resp = requests.get(cmr_search_granules_url, headers=search_headers, params=cmr_query_dict)
    cmr_response_feed = json.loads(cmr_resp.text)['feed']['entry']
    for granule in cmr_response_feed:
        granule = Granule(granule, 'aws_access_key_id', 'aws_secret_access_key')
        urls = granule['links']
        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))
        if browse_file:
            browse_urls.append(browse_file[0]['href'])
    browse_urls_query_string = ','.join(browse_urls)
    return browse_urls_query_string

@ns.route('/GetTile/<int:z>/<int:x>/<int:y>.<ext>')
class GetTile(Resource):

    def get(self, z, x, y, ext, color_map=None, rescale=None):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        granule_urs = request.args.get("granule_urs")
        collection_name = request.args.get("collection_name")
        collection_version = request.args.get("collection_version")
        color_map = request.args.get("color_map")
        rescale = request.args.get('rescale')
        response_body = dict()

        if not (granule_urs or (collection_name and collection_version)):
            message = "Neither required param granule_urs nor collection name and version provided in request"
            response_body["code"] = 422
            response_body["message"] = message
            response_body["error"] = message
            response_body["success"] = False
        else:
            try:
                browse_urls = []
                # REVIEW(aimee): Assumption we don't want both granule_urs AND collection identifiers
                if granule_urs:
                    granule_urs = granule_urs.split(',')
                    # REVIEW(aimee): Should this fail if some are missing? Right now it won't fail unless all are missing (I think)
                    # REVIEW(aimee): This is non-ideal since we're making a request for each granule. Would be more ideal to pass query params of the user directly to this method.
                    # TODO(aimee): Enable more CMR queries here
                    # REVIEW(aimee): Should we limit the number of granules that can be requested at once?
                    for granule_ur in granule_urs:
                        cmr_query_dict = { 'granule_ur': [ granule_ur ]}
                        cmr_resp = requests.get(cmr_search_granules_url, headers=cmr.get_search_headers(), params=cmr_query_dict)
                        cmr_response_feed = json.loads(cmr_resp.text)['feed']['entry']
                        granule = Granule(cmr_response_feed[0], 'aws_access_key_id', 'aws_secret_access_key')
                        urls = granule['links']
                        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))
                        if browse_file:
                            browse_urls.append(browse_file[0]['href'])
                    browse_urls_query_string = ','.join(browse_urls)
                else:
                    browse_urls_query_string = None
                    collection = default_collections[collection_name]
                    if 'mosaiced_cog' in collection:
                        browse_urls_query_string = collection['mosaiced_cog']
                    else:
                        browse_urls_query_string = get_collection_cogs(collection)

                mosaic_url = '{}/mosaic/{}/{}/{}.{}?urls={}&color_map={}&rescale={}'.format(
                    settings.TILER_ENDPOINT, z, x, y, ext, browse_urls_query_string, color_map, rescale
                )
                if len(mosaic_url) > max_url_length:
                    mosaic_url = mosaic_url[0:max_url_length]
                    mosaic_url = mosaic_url[0:mosaic_url.rfind(',')]
                tile_response = requests.get(mosaic_url)
                response = Response(tile_response.content, tile_response.status_code, {'Content-Type': 'image/png', 'Access-Control-Allow-Origin': '*'})
                return response

            # TODO(aimee): More specific errors, such as:
            # - One or more granules associated with granule_urs not exist in CMR
            # - One or more granules associated with granule_urs exists in CMR but has no associated imagery
            except:
                exception = sys.exc_info()
                exc_type, exc_message, exc_traceback = exception
                print(repr(traceback.extract_tb(exc_traceback)))
                log.error(str(exc_message))
                log.error(repr(traceback.extract_tb(exc_traceback)))
                error_message = 'Failed to fetch tiles for {}'.format(request.args)
                response_body["code"] = 500
                response_body["message"] = error_message
                response_body["error"] = str(exc_message)
                response_body["success"] = False
        return response_body

@ns.route('/GetCapabilities')
class GetCapabilities(Resource):

    def generate_capabilities(self):
        layers = []
        for collection in default_collections.values():
            if 'mosaiced_cog' in collection:
                browse_urls_query_string = collection['mosaiced_cog']
            else:
                browse_urls_query_string = get_collection_cogs(collection)
            # REVIEW(aimee): We're making a request for all the granule cog
            # urls here but then passing the collection name and version to
            # generate the GetCapabilities which means the service will
            # likely make the request to CMR twice. Is this necessary?
            # This would be a reason to permit GetTile to take a list of urls directly.
            mosaic_tilejson_url = '{}/mosaic/tilejson.json?urls={}'.format(settings.TILER_ENDPOINT, browse_urls_query_string)
            r = requests.get(mosaic_tilejson_url)
            meta = r.json()
            bbox = meta['bounds']
            layer_info = {
                'layer_title': collection['short_name'],
                'collection_version': collection['version'],
                # TODO(aimee): add default and alternatives
                # TODO(aimee): use defaults from /mosaic/tilejson.json
                'color_map': 'schwarzwald',
                'rescale': collection['rescale'],
                'bounds': [ bbox[0], bbox[1], bbox[2], bbox[3] ],
                # TODO(aimee): Should and how is ext and content_type configurable?
                'content_type': 'png',
                'ext': 'png'
            }
            layers.append(layer_info)

        context = {
            'service_title': 'MAAP WMTS',
            'provider': 'MAAP API',
            'provider_url': '{}/api'.format(settings.FLASK_SERVER_NAME),
            'base_url': '{}/api'.format(settings.FLASK_SERVER_NAME),
            'layers': layers,
            'minzoom': meta['minzoom'],
            'maxzoom': meta['maxzoom'],
            'zoom': 10
        }
        ROOT = os.path.dirname(os.path.abspath(__file__))
        template = open(os.path.join(ROOT, 'capabilities_template.xml'), 'r').read()
        xml_string = render_template_string(template, **context)
        return xml_string

    def get(self):
        response_body = dict()
        try:
            get_capabilities_object = self.generate_capabilities()
            # Return get capabilities
            response_body["message"] = "Successfully generated get capabilities"
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
