import logging
import json
import os
import sys, traceback
import requests
from flask import Response, request, render_template_string
from flask_restplus import Resource
from api.restplus import api
from api.utils.mapproxy_snap import create_config_wmts, mapit
from api.endpoints.wmts import GetCapabilities
from api import settings

log = logging.getLogger(__name__)

ns = api.namespace('wms', description='WMS GetMap')

@ns.route('/GetMap')
class GetMap(Resource):

    def get(self):
        """
        This will return OGC WMS GetMap response (image file)
        :return:
        """
        try:
            # Pass param which can be used to generate GetCapabilities dynamically
            cmr_search_params = {'granule_ur': request.args['LAYERS']}

            # Review(Aimee): This generates a local copy of WMTS GetCapabilities
            # XML, which `create_config_wmts` requires. `create_config_wmts`
            # could also call the /wmts/GetCapabilities endpoint but it would
            # run the same code to generate the XML so the tradeoff is making a
            # network call vs writing to the local filesystem.
            get_capabilities_string = GetCapabilities().generate_capabilities(cmr_search_params)
            wmts_capabilities_file = open(settings.MAAP_WMTS_XML, 'w')
            wmts_capabilities_file.write(get_capabilities_string)
            wmts_capabilities_file.close()
            wmts_confs = create_config_wmts(["file://" + settings.MAAP_WMTS_XML])

            # Get args from request
            # TODO(Aimee): Permitted parameters should be consistent with the
            # OGC WMS spec. There are other args which could be supported such
            # as STYLE. Also, multiple layers could be passed.
            if request.args.get('BBOX'):
                bbox = tuple(map(float, request.args.get('BBOX').split(',')))
            else:
                bbox = (-90, -180, 90, 180)
            if request.args.get('HEIGHT') and request.args.get('WIDTH'):
                size = (int(request.args.get('HEIGHT')),
                        int(request.args.get('WIDTH')))
            else:
                size = (256, 256)

            # FIXME: One collection (AFLVIS2) has granule urs which include
            # a colon, which causes a mapproxy configuration error.
            # Example: SC:AFLVIS2.001:138348873. This also shows up in wmts.py.
            layer = request.args['LAYERS'].replace(':', '')
            if request.args.get('FORMAT'):
                img_format = request.args.get('FORMAT')
            else:
                img_format = 'image/png'

            # Create the image
            img_data = mapit(wmts_confs, layer, img_format, bbox, size)

            response = Response(
                img_data,
                200,
                {
                    'Content-Type': img_format,
                    'Access-Control-Allow-Origin': '*'
                })
            return response
        except Exception as ex:
            response_body = dict()
            log.error(str(ex))
            log.error(json.dumps(ex, indent=2))
            response_body["code"] = 500
            response_body["message"] = 'Failed to generate map'
            response_body["error"] = str(ex)
            response_body["success"] = False
            return response_body
