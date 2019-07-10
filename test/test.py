import unittest
from api.maapapp import app

class MyAppCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()

    def test_index(self):
        response = self.app.get('/')
        data = response.get_data(as_text=True)
        self.assertEqual(data, '<a href=/api/>MAAP API</a>')
