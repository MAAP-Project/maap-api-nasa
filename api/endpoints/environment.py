import logging
from flask_restx import Resource
from flask import request
from api.restplus import api
from urllib.parse import urlsplit
from api import settings
import requests
import urllib.parse
import os
import api.endpoints.constants as constants

log = logging.getLogger(__name__)

ns = api.namespace('environment', description='Operations related to the MAAP environment')


@ns.route('/config')
class Config(Resource):
    def get(self):
        """
        Request environment metadata for a current ADE hostname
        :return:
        """
        try:
            key = "CLIENT_SETTINGS"
            config = getattr(settings, key)
            maap_api_root = request.base_url.replace("/environment/config", '')
            service = config.get("service")
            service.update({"maap_api_root": maap_api_root})
            return config
        except ValueError as e:
            logging.exception("No CLIENT_SETTINGS found in settings file")
            return {}, 404



@ns.route('/config/<string:ade_host>')
class Config(Resource):
    def get(self, ade_host):
        """
        Request environment metadata for a given ADE hostname
        :return:
        """
        config = get_config(ade_host)

        return config


@ns.route('/bucketPrefix/<string:ade_host>')
class BucketPrefix(Resource):
    def get(self, ade_host):
        """
        Request environment bucket prefix for a given ADE hostname
        :return:
        """
        config = get_config(ade_host)
        prefix = config['workspace_bucket'].split('-')[1]

        return prefix


def get_config(ade_host):
    api_host = os.getenv("MAAP_API_HOST", constants.DEFAULT_API)
    print("graceal1 api host is ")
    print(api_host)
    maap_api_config_endpoint = os.getenv("MAAP_API_CONFIG_ENDPOINT", "api/environment/config")
    print("graceal1 constants ADE options ")
    print(constants.ADE_OPTIONS)
    ade_host = ade_host if ade_host in constants.ADE_OPTIONS else os.getenv("MAAP_ADE_HOST", constants.DEFAULT_ADE)
    environments_endpoint = "https://" + api_host + "/" + maap_api_config_endpoint + "/"+urllib.parse.quote(urllib.parse.quote("https://", safe=""))+ade_host
    print("graceal1 environments endpoint is ")
    print(environments_endpoint)
    return requests.get(environments_endpoint).json()
