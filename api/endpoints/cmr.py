import logging
import os
import requests
import shapefile
from api import settings

from flask import request, jsonify
from flask_restplus import Resource, reqparse
from api.restplus import api

log = logging.getLogger(__name__)

ns = api.namespace('cmr', description='Operations related to CMR')


@ns.route('/collections')
class CmrCollection(Resource):

    def get(self):
        """
        CMR collections
        """

        url = os.path.join(settings.CMR_URL, 'search', 'collections')

        resp = requests.get(url, headers=get_search_headers(), params=request.args)
        return jsonify(resp.text)

    def post(self):
        parse = reqparse.RequestParser()
        parse.add_argument('shapefile')

        working_directory = os.getcwd()

        sf = shapefile.Reader(working_directory + "/../../antarctica/gis_osm_landuse_a_free_1.shp")
        bbox = sf.bbox
        test = sf.measure

        #args = parse.parse_args()

        # stream = args['shapefile'].stream
        #
        # wav_file = wave.open(stream, 'rb')
        # signal = wav_file.readframes(-1)
        # signal = np.fromstring(signal, 'Int16')
        # fs = wav_file.getframerate()
        # wav_file.close()



@ns.route('/granules')
class CmrGranules(Resource):

    def get(self):
        """
        CMR granules
        """

        url = os.path.join(settings.CMR_URL, 'search', 'granules')

        resp = requests.get(url, headers=get_search_headers(), params=request.args)
        return jsonify(resp.text)


def get_search_headers():
    return {
            'Accept': 'application/json',
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }

