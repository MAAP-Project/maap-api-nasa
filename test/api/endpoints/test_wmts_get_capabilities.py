import unittest
from api.maapapp import app, initialize_app
from api import settings
import json

g1 = {
    'granule_ur': 'uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt',
    'cog_url': 's3://cumulus-map-internal/file-staging/circleci/AfriSAR_UAVSAR_Coreg_SLC___1/uavsar_AfriSAR_v1_SLC-lopenp_14043_16015_001_160308_L090.vrt.cog.tif',
    'color_map': 'schwarzwald',
    'rescale': '-1,1',
    'zxy': '10/545/513'
}

g2 = {
    'granule_ur': 'uavsar_AfriSAR_v1_SLC-hundre_14048_16008_007_160225_L090.vrt',
    'cog_url': 's3://cumulus-map-internal/file-staging/circleci/AfriSAR_UAVSAR_Coreg_SLC___1/uavsar_AfriSAR_v1_SLC-hundre_14048_16008_007_160225_L090.vrt.cog.tif'
}

collection = {
  'short_name': 'AfriSAR_UAVSAR_Coreg_SLC',
  'version': '1'
}

class MyAppCase(unittest.TestCase):
    def get_tile_path(self, zxy='1/1/1.png'):
      return 'api/wmts/GetTile/{}.png'.format(zxy)

    def setUp(self):
        app.config['TESTING'] = True
        self.maxDiff = None # For seeing the whole redirect message
        self.app = app.test_client()

    def test_get_tile_no_identifier(self):
        response = self.app.get(self.get_tile_path())
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 422)
        error_message = 'Neither required param granule_urs nor collection name and version provided in request'
        self.assertEqual(data['message'], error_message)
        self.assertEqual(data['error'], error_message)

    def test_get_tile_no_browse(self):
        test_granule_ur = 'test.vrt'
        response = self.app.get('{}?granule_urs={}'.format(self.get_tile_path(), test_granule_ur))
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data['code'], 500)
        error_message = 'Failed to fetch tiles for {}'.format(test_granule_ur)
        self.assertEqual(data['message'], error_message)
        self.assertEqual(data['error'], 'list index out of range')

    def get_tiler_endpoint(self, granules):
      cog_urls = ','.join(map(lambda g: g['cog_url'], granules))
      g1 = granules[0]
      return '{}/mosaic/{}.png?urls={}&color_map={}&rescale={}'.format(
        settings.TILER_ENDPOINT, g1['zxy'], cog_urls, g1['color_map'], g1['rescale']
      )


    # An integration test
    def test_get_tile_redirects_single_granule(self):
        response = self.app.get(
          '{}?granule_urs={}&color_map={}&rescale={}'.format(self.get_tile_path(g1['zxy']), g1['granule_ur'], g1['color_map'], g1['rescale'])
        )
        data = response.get_data(as_text=True)
        self.assertTrue('Redirecting' in data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.get_tiler_endpoint([g1]))

    def test_get_tile_redirects_multiple_granules(self):
        granule_urs = ','.join([g1['granule_ur'], g2['granule_ur']] )
        response = self.app.get(
          '{}?granule_urs={}&color_map={}&rescale={}'.format(self.get_tile_path(g1['zxy']), granule_urs, g1['color_map'], g1['rescale'])
        )
        data = response.get_data(as_text=True)
        self.assertTrue('Redirecting' in data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.get_tiler_endpoint([g1, g2]))

    def test_get_tile_redirects_collection(self):
        response = self.app.get(
          '{}?collection_name={}&collection_version={}&color_map={}&rescale={}'.format(
            self.get_tile_path(g1['zxy']), collection['short_name'], collection['version'], g1['color_map'], g1['rescale']
          )
        )
        data = response.get_data(as_text=True)
        self.assertTrue('Redirecting' in data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(g1['cog_url'] in response.location)
        self.assertTrue(g2['cog_url'] in response.location)
