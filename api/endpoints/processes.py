from api.restplus import api
from flask import request, Response
from flask_restx import Resource
from api.auth.security import get_authorized_user, login_required

ns = api.namespace('mas', description='Operations to interface with HySDS Mozart')


@ns.route('/processes')
class Submit(Resource):

    @api.doc(security='ApiKeyAuth')
    @login_required()
    def post(self):
        print("in post of processes ")