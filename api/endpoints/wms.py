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
            wmts_getcapabilities_filename = 'maap.wmts.xml'

            # TODO(Aimee): This avoids an error response from CMR "Parameter [service]
            # was not recognized" but we probably want a longer list of permitted
            # params.
            cmr_search_params_whitelist = ['granule_ur', 'short_name', 'version']
            cmr_search_params = {}
            for key in cmr_search_params_whitelist:
                if key in request.args:
                   cmr_search_params[key] = request.args[key]

            get_capabilities_string = GetCapabilities().generate_capabilities(cmr_search_params)
            wmts_capabilities_file = open(wmts_getcapabilities_filename, 'w')
            wmts_capabilities_file.write(get_capabilities_string)
            wmts_capabilities_file.close()

            wmts_confs = create_config_wmts(["file://" + os.path.abspath(wmts_getcapabilities_filename)])

            # Get args from request
            bbox = (11.41071054972465, -0.3848431107778577, 11.857202093935395, 0.09666737807686826)
            size = (1200, 600)
            layer = 'AfriSAR_UAVSAR_Coreg_SLC'
            img_format = 'image/png'
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