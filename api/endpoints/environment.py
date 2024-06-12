import logging
from flask_restx import Resource
from flask import request
from api.restplus import api
from urllib.parse import urlsplit
from api import settings
import requests
import urllib.parse

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
    req = requests.get(settings.MAAP_ENVIRONMENT_FILE)
    if req.status_code == requests.codes.ok:
        data = req.json()
    else:
        print('Content was not found.')

    base_url = "{0.netloc}".format(urlsplit(urllib.parse.unquote(ade_host)))

    match = next((x for x in data if base_url in x['ade_server']), None)
    maap_config = next((x for x in data if x['default_host'] == True), None) if match is None else match

    return maap_config

