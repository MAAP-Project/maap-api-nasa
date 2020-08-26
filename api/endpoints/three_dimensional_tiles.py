import logging
import requests
from api import settings
from flask import Response
from flask_restplus import Resource
from api.restplus import api

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace('3d-tiles', description='Operations related to 3d tile querying.')


@ns.route('/<path:path>')
class ThreeDimensionalTiles(Resource):

    def get(self, path):
        """
        3D Tiles

            Examples:

            https://api.maap-project.org/api/3d-tiles/ATL08_ARD-beta___001/afrisar/ept-tiles/tileset.json
            https://api.maap-project.org/api/3d-tiles/ATL08_ARD-beta___001/peru/ept-tiles/tileset.json
        """

        three_d_tile_json_url = settings.DATA_SYSTEM_SERVICES_API_BASE + settings.DATA_SYSTEM_FILES_PATH + path

        r = requests.get(three_d_tile_json_url)

        response = Response(
            r.content,
            r.status_code,
            {
                'Content-Type': 'application/json'
            })
        return response

