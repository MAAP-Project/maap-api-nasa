import logging
from flask import session
from flask_restplus import Resource
from api.restplus import api
from api.cas.CAS import login_required
# from flask_cas import login_required


log = logging.getLogger(__name__)

ns = api.namespace('members', description='Operations for MAAP members')

# TODO:
# 1. Add members 'all' route for retrieving member list from Syncope
# 2. Overload the login_required decorator to return a 403 if and only if
#    1) the user is not logged in and 2) the http request content-type is json.
# 3. Support proxy ticket requests to bypass the login dependency.
#    See https://github.com/python-cas/python-cas/blob/master/tests/test_cas.py
# 4. Add authorization requirement to all api endpoints
# 5. User activity logging?
# 6. Inject user identification into sub component calls (cmr, dps, wmts)


@ns.route('/self')
class Self(Resource):

    @login_required
    def get(self):
        """
        Metadata for the authenticated user.
        """

        return session['CAS_ATTRIBUTES']





