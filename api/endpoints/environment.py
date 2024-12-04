import logging
from flask_restx import Resource
from flask import request
from api.restplus import api
from urllib.parse import urlsplit
from api import settings
import requests
import urllib.parse
import json

log = logging.getLogger(__name__)

ns = api.namespace('environment', description='Operations related to the MAAP environment')
print("graceal1 in environment.py for API")

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
    print("graceal1 in API get_config with")
    print(ade_host)
    with open("environments.json") as f:
        data = json.loads(f)

    base_url = "{0.netloc}".format(urlsplit(urllib.parse.unquote(ade_host)))
    print("graceal1 req returned is")
    print(data)
    match = next((x for x in data if base_url in x['ade_server']), None)
    maap_config = next((x for x in data if x['default_host'] == True), None) if match is None else match
    print("graceal1 the maap_config is")
    print(maap_config)
    return maap_config
