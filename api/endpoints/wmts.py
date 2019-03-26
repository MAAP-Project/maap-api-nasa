import logging
from flask import request
from flask_restplus import Resource
from api.restplus import api
import api.utils.auth_util as auth
import api.endpoints.cmr as cmr
from maap.Result import Granule

log = logging.getLogger(__name__)

ns = api.namespace('wmts', description='Retrieve tiles')


@ns.route('/GetTile')
class GetTile(Resource):

    # TODO(aimee): Revert this comment of @auth.token_required
    # @auth.token_required
    def get(self):
        """
        This will submit jobs to the Job Execution System (HySDS)
        :return:
        """
        granule_ur = request.args.get("granule_ur")
        log.info('request.args {}'.format(request.args))
        response_body = dict()

        if not granule_ur:
            message = "required param granule_ur not provided in request"
            response_body["code"] = 422
            response_body["message"] = message
            response_body["error"] = message
            response_body["success"] = False            

        try:
            cmr_url = os.path.join(settings.CMR_URL, 'search', 'granules')
            cmr_resp = requests.get(cmr_url, headers=cmr.get_search_headers(), params=cmr.parse_query_string())
            granule = Granule(response.body, 'aws_access_key_id', 'aws_secret_access_key')
            browse_image_url = granule._BrowseUrl
            tile = requests.get('{}{}'.format(settings.BROWSE_URL, browse_image_url))
            response_body["message"] = "Successfully fetched browse image for {}".format(granule_ur)
            ## Update me with resposne from fastbrowse api
            response_body["tile"] = response.get("tile")
            response_body["code"] = 200
            response_body["success"] = True
        except Exception as ex:
            log.error(str(ex))
            log.error(json.dumps(ex, indent=2))
            response_body["code"] = 500
            response_body["message"] = "Failed to fetch tiles for {}".format(granule_ur)
            response_body["error"] = str(ex)
            response_body["success"] = False

        return response_body
