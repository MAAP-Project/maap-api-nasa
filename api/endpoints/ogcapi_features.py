import logging
import os
from re import A
import requests
from api import settings
from flask import request
from flask_restplus import Resource
from api.restplus import api
from werkzeug.wrappers import Response
from typing import Optional
import json

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace(
    "ogcapi-features", description="Operations related to OGC API - Features"
)


@ns.route("/", defaults={"path": ""})
@ns.route("/<path:path>")
class OgcapiFeatures(Resource):
    def get(self, path: str):
        """
        OGC API Features proxy

            Examples:

        """

        return respond(
            req(path, request.query_string, request.headers.get("accept")),
            f"{request.url_root}api/ogcapi-features",
        )


def req(path: str, query_string: str, accept_content_type: Optional[str]):
    url = os.path.join(settings.OGCAPI_FEATURES_ENDPOINT, path)
    params = urlparse.parse_qs(query_string)
    headers = {}
    if accept_content_type:
        headers["accept"] = accept_content_type
    return requests.get(url, params=params, headers=headers, timeout=10)


def respond(r, url_root: str):
    content_type_header = r.headers.get("content-type")
    status_code = r.status_code
    body = r.text

    if status_code == 200 and content_type_header and ("json" in content_type_header):
        entity = json.loads(body)
        rewrite_urls(entity, url_root)
        rewrite_urls_in_list(entity.get("items"), url_root)
        rewrite_urls_in_list(entity.get("collections"), url_root)
        body = json.dumps(entity)

    return Response(status=status_code, content_type=content_type_header, response=body)


def rewrite_urls_in_list(entities, url_root):
    if entities:
        for entity in entities:
            rewrite_urls(entity, url_root)


def rewrite_urls(entity, url_root):
    for link in entity.get("links", []):
        href = link.get("href")
        if href:
            link["href"] = href.replace(
                settings.OGCAPI_FEATURES_ENDPOINT, url_root, 1
            )
