import json
import logging
import uuid

import boto3
from flask import jsonify, request, redirect
from flask_restplus import Resource

from api.restplus import api
import api.settings as settings

log = logging.getLogger(__name__)

ns = api.namespace('query', description='Operations for Query Service')

s3_client = boto3.client('s3', region_name=settings.AWS_REGION)
sf_client = boto3.client('stepfunctions', region_name=settings.AWS_REGION)


def get_signed_url(key: str, expiration: int = 60 * 60 * 24):
    return s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.QS_RESULT_BUCKET,
            'Key': key
        },
        ExpiresIn=expiration
    )


def err_response(msg, code=400):
    return {
        'code': code,
        'message': msg
    }, code


@ns.route('/')
class QueryServiceCreate(Resource):

    def _is_valid_fields(self, fields):
        return all([isinstance(f, str) for f in fields])

    def _is_valid_bbox(self, bbox):
        return all([
            len(bbox) is 4,
            *[isinstance(f, float) or isinstance(f, int) for f in bbox]
        ])

    def _is_valid_where(self, where):
        return isinstance(where, dict)

    def _is_valid_src(self, src):
        collection = src.get('Collection')
        if not isinstance(collection, dict):
            return False
        return all([
            isinstance(collection.get('ShortName'), str),
            isinstance(collection.get('VersionId'), str)
        ])

    def post(self, *args, **kwargs):
        """
        Create query execution

        Format of JSON to post:
        {
            "src": {
                "Collection": {
                    "ShortName": "",
                    "VersionId": ""
                }
            },
            "query": {
                "where": {}     // Key:Value mapping
                "bbox": [],     // GeoJSON compliant bbox
                "fields": []    // Array of field names (string)
            }
        }

        Sample JSON:
        {
            "src": {
                "Collection": {
                    "ShortName": "GEDI Cal/Val Field Data_1",
                    "VersionId": "001"
                }
            },
            "query": {
                "where": {
                    "project": "usa_sonoma"
                },
                "bbox": [
                    -122.6,
                    38.4,
                    -122.5,
                    38.5
                ],
                "fields": ["project", "wkt"]
            }
        }
        """
        req_data = request.get_json()
        if not isinstance(req_data, dict):
            return err_response("Valid JSON body object required.")

        query = req_data.get('query', {})
        if not isinstance(query, dict):
            return err_response("Valid query object required.")

        fields = query.get('fields') or []
        if fields and not self._is_valid_fields(fields):
            return err_response("Optional 'fields' property must be array of field names")

        where = query.get('where') or []
        if where and not self._is_valid_where(where):
            return err_response("Optional 'where' property must be object")

        bbox = query.get('bbox') or []
        if bbox and not self._is_valid_bbox(bbox):
            return err_response(
                "Optional 'bbox' property must be a GeoJSON compliant bbox, an array of 4 numbers"
            )

        src = req_data.get('src') or {}
        if not self._is_valid_src(src):
            return err_response(
                "'src' property failed to validate as a Collection object."
            )

        # Schedule execution
        query_id = str(uuid.uuid4())
        query_input = {
            'id': query_id,
            'src': src,
            'query': {
                'fields': fields,
                'where': where,
                'bbox': bbox
            }
        }
        sf_client.start_execution(
            stateMachineArn=settings.QS_STATE_MACHINE_ARN,
            name=query_id,
            input=json.dumps(query_input)
        )

        # Return signed response URL to query results
        return jsonify(
            id=query_id,
            results=get_signed_url(query_id),
            meta=get_signed_url(f'{query_id}.meta')
        )


@ns.route('/<string:query_id>')
class QueryServiceResults(Resource):

    def get(self, query_id):
        """
        Return redirect to query results
        """
        return redirect(get_signed_url(query_id), code=302)
