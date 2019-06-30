import logging
import json
import os
import sys, traceback
import requests
from flask import Response, request, render_template_string
from flask_restplus import Resource
from api.restplus import api
from api import settings
import api.endpoints.cmr as cmr
from api.utils.Granule import Granule
from collections import OrderedDict
import xmltodict
from api.endpoints.wmts_collections import default_collections
from werkzeug.datastructures import ImmutableMultiDict

log = logging.getLogger(__name__)

ns = api.namespace('wmts', description='Retrieve tiles')

# Load default collections
cmr_search_granules_url = os.path.join(settings.CMR_URL, 'search', 'granules')
# TODO: assert the URL is not longer than max_url_length to avoid a 413 error.
max_url_length = 8192

def collection_params(collection={}):
    collection_attrs = ['short_name', 'version', 'mosaiced_cog']
    return {k: v for k,v in collection.items() if k in collection_attrs}

def get_cog_urls_string(params={}):
    """
    Given a collection object (name and version), request all granules
    for that collection and return a comma-list of all urls for browse
    links for that collection's granules.
    :return:
    """
    if type(params) == ImmutableMultiDict:
        params = params.to_dict()
    if 'mosaiced_cog' in params:
        return params['mosaiced_cog']
    browse_urls = []
    # REVIEW / TODO(aimee): What's reasonable? Default page_size is 10,
    # but many granules do not have associated browse imagery at this
    # time. Depending on what's reasonable, throw an error if over a
    # limit (e.g. refine query?) We need a better answer for collections
    # with a large number of granules.
    params['page_size'] = 100
    search_headers = cmr.get_search_headers()
    search_headers['Accept'] = 'application/json'
    cmr_resp = requests.get(cmr_search_granules_url, headers=search_headers, params=params)
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
        urls = request.args.get("urls")
        short_name = request.args.get("short_name")
        version = request.args.get("version")
        color_map = request.args.get("color_map")
        rescale = request.args.get('rescale')
        response_body = dict()

        if not (granule_urs or urls or (short_name and version)):
            message = "Neither required param granule_urs nor collection name and version provided in request"
            response_body["code"] = 422
            response_body["message"] = message
            response_body["error"] = message
            response_body["success"] = False
        else:
            try:
                if urls:
                    browse_urls_query_string = urls
                # Granule URs are passed
                elif granule_urs:
                    browse_urls = []
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
                    collection = default_collections[short_name]
                    browse_urls_query_string = get_cog_urls_string(collection_params(collection))

                mosaic_url = '{}/mosaic/{}/{}/{}.{}?urls={}&color_map={}&rescale={}'.format(
                    settings.TILER_ENDPOINT, z, x, y, ext, browse_urls_query_string, color_map, rescale
                )
                tile_response = requests.get(mosaic_url)
                response = Response(
                    tile_response.content,
                    tile_response.status_code,
                    {
                        'Content-Type': 'image/png',
                        'Access-Control-Allow-Origin': '*'
                    })
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
                error_message = 'Failed to fetch tiles for {}'.format(json.dumps(request.args))
                response_body["code"] = 500
                response_body["message"] = error_message
                response_body["error"] = str(exc_message)
                response_body["success"] = False
        return response_body

@ns.route('/GetCapabilities')
class GetCapabilities(Resource):

    def generate_layer_info(self, key, urls_query_string, collection={}):
        # REVIEW(aimee): We're making a request for all the granule cog
        # urls here but then passing the collection name and version to
        # generate the GetCapabilities which means the service will
        # likely make the request to CMR twice. Is this necessary?
        # This would be a reason to permit GetTile to take a list of urls directly.
        mosaic_tilejson_url = '{}/mosaic/tilejson.json?urls={}'.format(settings.TILER_ENDPOINT, urls_query_string)
        r = requests.get(mosaic_tilejson_url)
        meta = r.json()
        bbox = meta['bounds']
        layer_info = {
            'layer_title': key,
            'bounds': [ bbox[0], bbox[1], bbox[2], bbox[3] ],
            # TODO(aimee): Should and how is ext and content_type configurable?
            'content_type': 'png',
            'ext': 'png',
            # TODO(aimee): add settings to collection object
            # TODO(aimee): use defaults from /mosaic/tilejson.json
            'color_map': 'schwarzwald',
            'rescale': '0,70'
        }
        if collection:
            layer_info['query'] = f"short_name={collection['short_name']}&version={collection['version']}"
            if 'color_map' in collection:
                layer_info['color_map'] = collection['color_map']
            if 'rescale' in collection:
                layer_info['rescale'] = collection['rescale']
        else:
            layer_info['query'] = f'urls={urls_query_string}'

        return layer_info

    def generate_capabilities(self, request_args):
        layers = []
        # TODO(aimee): assumes single layer for all request args,
        # results from different collections should probably be grouped
        # into different layers
        if len(request_args) > 0:
            urls = get_cog_urls_string(request_args)
            layers.append(self.generate_layer_info('search_results', urls))
        else:
            for key, collection in default_collections.items():
                browse_urls_query_string = get_cog_urls_string(collection_params(collection))
                layer_info = self.generate_layer_info(key, browse_urls_query_string, collection)
                layers.append(layer_info)

        context = {
            'service_title': 'MAAP WMTS',
            'provider': 'MAAP API',
            'provider_url': '{}/api'.format(settings.FLASK_SERVER_NAME),
            'base_url': '{}/api'.format(settings.FLASK_SERVER_NAME),
            'layers': layers,
            'minzoom': 0,
            'maxzoom': 18,
            'zoom': 10,
            'tile_width': 256,
            'tile_height': 256
        }
        ROOT = os.path.dirname(os.path.abspath(__file__))
        template = open(os.path.join(ROOT, 'capabilities_template.xml'), 'r').read()
        xml_string = render_template_string(template, **context)
        return xml_string

    def get(self):
        try:
            get_capabilities_object = self.generate_capabilities(request.args)
            # Return get capabilities
            response = Response(get_capabilities_object, 200, {
                'Content-Type': 'application/xml',
                'Access-Control-Allow-Origin': '*'
            })
            return response
        except Exception as ex:
            response_body = dict()
            log.error(str(ex))
            log.error(json.dumps(ex, indent=2))
            response_body["code"] = 500
            response_body["message"] = "Failed to fetch tiles for {}".format(granule_ur)
            response_body["error"] = str(ex)
            response_body["success"] = False
            return response_body
