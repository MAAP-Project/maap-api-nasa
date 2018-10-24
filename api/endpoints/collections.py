import logging
import os
import requests
from api import settings

from flask import request, jsonify
from flask_restplus import Resource
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

