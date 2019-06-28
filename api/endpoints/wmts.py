import logging
import json
import os
import sys, traceback
import requests
from flask import request, render_template_string
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
                cmr_url = os.path.join(settings.CMR_URL, 'search', 'granules')
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
                        cmr_resp = requests.get(cmr_url, headers=cmr.get_search_headers(), params=cmr_query_dict)
                        cmr_response_feed = json.loads(cmr_resp.text)['feed']['entry']
                        granule = Granule(cmr_response_feed[0], 'aws_access_key_id', 'aws_secret_access_key')
                        urls = granule['links']
                        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))
                        if browse_file:
                            browse_urls.append(browse_file[0]['href'])
                    browse_urls_query_string = ','.join(browse_urls)
                    mosaic_url = '{}/mosaic/{}/{}/{}.{}?urls={}&color_map={}&rescale={}'.format(
                        settings.TILER_ENDPOINT, z, x, y, ext, browse_urls_query_string, color_map, rescale
                    )
                    log.info('Redirecting to {}'.format(mosaic_url))
                    return redirect(mosaic_url)
                else:
                    # TODO(aimee): It could be that more than 2000 granules are
                    # returned - but this would probably overload the tiler? We
                    # need a better answer for collections with a large number
                    # of granules.
                    cmr_query_dict = { 'short_name': [ collection_name ], 'version': [ collection_version ], 'page_size': 2000 }
                    cmr_resp = requests.get(cmr_url, headers=cmr.get_search_headers(), params=cmr_query_dict)
                    cmr_response_feed = json.loads(cmr_resp.text)['feed']['entry']
                    for granule in cmr_response_feed:
                        granule = Granule(granule, 'aws_access_key_id', 'aws_secret_access_key')
                        urls = granule['links']
                        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))
                        if browse_file:
                            browse_urls.append(browse_file[0]['href'])
                    browse_urls_query_string = ','.join(browse_urls)
                    mosaic_url = '{}/mosaic/{}/{}/{}.{}?urls={}&color_map={}&rescale={}'.format(
                        settings.TILER_ENDPOINT, z, x, y, ext, browse_urls_query_string, color_map, rescale
                    )
                    log.info('Redirecting to {}'.format(mosaic_url))
                    return redirect(mosaic_url)

            # TODO(aimee): More specific errors, such as:
            # - One or more granules associated with granule_urs not exist in CMR
            # - One or more granules associated with granule_urs exists in CMR but has no associated imagery
            except:
                exception = sys.exc_info()
                exc_type, exc_message, exc_traceback = exception
                print(repr(traceback.extract_tb(exc_traceback)))
                log.error(str(exc_message))
                log.error(repr(traceback.extract_tb(exc_traceback)))
                error_message = 'Failed to fetch tiles for {}'.format(granule_ur)
                response_body["code"] = 500
                response_body["message"] = error_message
                response_body["error"] = str(exc_message)
                response_body["success"] = False

        return response_body

@ns.route('/GetCapabilities')
class GetCapabilities(Resource):

    def generate_capabilities(self, granule):
        urls = granule['links']
        browse_file = list(filter(lambda x: "(BROWSE)" in x['title'], urls))[0]['href']
        layer_title = granule['dataset_id']
        r = requests.get(settings.TILER_ENDPOINT + "/metadata?url=" + browse_file)
        meta = r.json()
        bbox = meta['bounds']['value']
        context = {
          'service_title': 'MAAP WMTS',
          'provider': 'MAAP API',
          'provider_url': '{}/api/'.format(settings.FLASK_SERVER_NAME),
          'base_url': '{}/api/'.format(settings.FLASK_SERVER_NAME),
          'layer_title': layer_title,
          'bounds': [ bbox[0], bbox[1], bbox[2], bbox[3] ],
          'content_type': 'tif',
          'ext': 'tif',
          'zoom': 10,
          'minzoom': 8,
          'maxzoom': 15
        }
        ROOT = os.path.dirname(os.path.abspath(__file__))
        template = open(os.path.join(ROOT, 'capabilities_template.xml'), 'r').read()
        xml_string = render_template_string(template, **context)
        return json.loads(json.dumps(xmltodict.parse(xml_string)))


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
