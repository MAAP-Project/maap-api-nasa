import logging
from flask import session
from flask_restplus import Resource
from api.restplus import api
from flask_cas import login_required


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

    #@login_required
    def get(self):
        """
        Metadata for the authenticated user.
        """

        #return session['CAS_ATTRIBUTES']

        return {
            'username': 'maapuser',
            'study_area': 'Cryospheric Studies',
            'organization': 'JPL',
            'display_name': 'MAAP User',
            'given_name': 'MAAP',
            'family_name': 'User',
            'email': 'maapuser@maap-project.org',
            'public_ssh_keys': 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDaAmQEvp7kr3A0KScStL2O6VBSdSSrMy6K4A53A1nbSTEOtql2OFP8eZpmh6he2+YIrIhaKa0K48ejAusXfmaHHzfEoVBvGr1sxHlWFqNFsRqOBvY3aoG5tmAth9tb9mV44p65eUu09xCzSjpEvjWaBzxhort2U4en7plRoCWlm43St6P3XZBsPC7A8A6IGek6zOyzT3f9mWJzjfFu4fFFzRb24Bx+lxDbLdcApCv/cMAMN36Y+H+PsTlx56E4bBPY58xH00t+IlgL2XBl5RVLUwoDLWZVThOJD365BuxH0hx7JmDHUEZVGwMWHHXRGAkpsFf7SwlexvGlQf6wn8cr gchang@Akari'
        }





