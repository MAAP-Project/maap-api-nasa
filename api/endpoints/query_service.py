import json
import logging
import uuid

import boto3
from flask import jsonify, request
from flask_restplus import Resource

from api.restplus import api
import api.settings as settings

log = logging.getLogger(__name__)

ns = api.namespace('query-service', description='Operations for Query Service')

s3_client = boto3.client('s3')
sf_client = boto3.client('stepfunctions')


def get_signed_url(query_id: str, expiration: int = 60 * 60 * 24):
    return s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.QS_RESULT_BUCKET,
            'Key': query_id
        },
        ExpiresIn=expiration
    )


def err_response(msg, code=400):
    return {
        'code': code,
        'message': msg
    }, code


@ns.route('/query')
class QueryServiceCreate(Resource):

    def _is_valid_fields(self, fields):
        return all([isinstance(f, str) for f in fields])

    def _is_valid_bbox(self, bbox):
        return all([
            len(bbox) is 4,
            *[isinstance(f, float) or isinstance(f, int) for f in bbox]
        ])

    def _is_valid_src(self, src):
        return any([
            self._contains_valid_collection(src),
            self._contains_valid_granule(src)
        ])

    def _contains_valid_collection(self, src):
        collection = src.get('Collection')
        if not isinstance(collection, object):
            return False
        return all([
            isinstance(collection.get('ShortName'), str),
            isinstance(collection.get('VersionId'), str)
        ])

    def _contains_valid_granule(self, src):
        granule = src.get('Granule')
        if not isinstance(granule, object):
            return False
        return all([
            self._contains_valid_collection(granule),
            isinstance(granule.get('GranuleUR'), str),
        ])

    def post(self):
        """
        Create query execution
        """
        req_data = request.get_json()

        fields = req_data.get('fields') or []
        if fields and not self._is_valid_fields(fields):
            return err_response("Optional 'fields' property must be array of field names")

        bbox = req_data.get('bbox') or []
        if bbox and not self._is_valid_bbox(bbox):
            return err_response(
                "Optional 'bbox' property must be a GeoJSON compliant bbox, an array of 4 numbers"
            )

        src = req_data.get('src', {})
        if not self._is_valid_src(src):
            return err_response(
                "'src' property failed to validate as a Collection or Granule object."
            )

        # Schedule execution
        query_id = str(uuid.uuid4())
        query_input = {
            'id': query_id,
            'src': src,
            'query': {
                'fields': fields,
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
            url=get_signed_url(query_id),
            meta=get_signed_url(f'{query_id}.meta')
        )


@ns.route('/query/<string:query_id>')
class QueryServiceResults(Resource):

    def get(self, query_id):
        """
        Get query results
        """
        return get_signed_url(query_id)


@ns.route('/query/<string:query_id>/meta')
class QueryServiceMetadata(Resource):

    def get(self, query_id):
        """
        Get query metadata
        """
        return get_signed_url(f"{query_id}.meta")
