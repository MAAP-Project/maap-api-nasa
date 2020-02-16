import logging
from flask_restplus import Resource
from api.restplus import api
from api.cas.cas_auth import get_authorized_user, login_required


log = logging.getLogger(__name__)

ns = api.namespace('members', description='Operations for MAAP members')


@ns.route('/self')
class Self(Resource):

    @login_required
    def get(self):
        member = get_authorized_user()

        return member





