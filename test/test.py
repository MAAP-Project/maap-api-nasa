import unittest
from datetime import datetime, timezone
from cachetools import cached, TLRUCache
from flask import jsonify

from api.maapapp import app
import uuid


def now_utc() -> float:
    """Return the current datetime value in UTC."""
    return datetime.now(timezone.utc).timestamp() * 1000


def creds_expiration_utc(_key, creds, now_utc_cred: float) -> float:
    """Return the UTC time that is halfway between now and the expiration time
    of a credentials object.

    Assume ``creds`` is an object containing the key ``'expiration'`` associated
    to a ``str`` value representing the expiration date/time of the credentials
    in the format ``'%Y-%m-%d %H:%M:%S%z'``.

    If there is no such key, or the associated value cannot be successfully
    parsed into a ``datetime`` value using the format above, return ``now_utc``.
    Otherwise, return a datetime value halfway between ``now_utc`` and the
    parsed expiration value (converted to UTC).

    Note that if the parsed value is prior to ``now_utc``, the returned value
    will also be prior to ``now_utc``, halfway between both values.
    """

    try:
        expiration = creds['expiration']
        expiration_dt = datetime.strptime(expiration, "%Y-%m-%d %H:%M:%S%z")
        expiration_dt_utc = expiration_dt.astimezone(timezone.utc).timestamp() * 1000
    except (KeyError, ValueError):
        expiration_dt_utc = now_utc_cred

    # Expire creds in half the actual expiration time
    return expiration_dt_utc - (expiration_dt_utc - now_utc_cred) / 2


class MyAppCase(unittest.TestCase):

    @classmethod
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()

    def test_index(self):
        response = self.app.get('/')
        data = response.get_data(as_text=True)
        self.assertEqual(data, '<a href=/api/>MAAP API</a>')

    def test_cache(self):
        testCache1 = self.get_edc_credentials("foo", 1)
        testCache2 = self.get_edc_credentials("foo", 2)

        self.assertEqual(testCache1, testCache2)

        testCache3 = self.get_edc_credentials("foo", 3)
        testCache4 = self.get_edc_credentials("foo", 3)

        self.assertNotEqual(testCache3, testCache4)

    @cached(TLRUCache(ttu=creds_expiration_utc, timer=now_utc, maxsize=128))
    def get_edc_credentials(self, endpoint_uri, user_id):
        uuid_val = str(uuid.uuid4())

        response = {
            'user_id': user_id,
            'endpoint_uri': endpoint_uri,
            'uuid': uuid_val,
            'expiration': '2024-01-31 23:32:05+00:00'
        }
        return response
