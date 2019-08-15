import copy
import requests
from io import StringIO

from PIL import Image, ImageChops
from mapproxy.request import Request
from mapproxy.config.loader import ProxyConfiguration
from owslib.wmts import WebMapTileService
from natsort import natsorted
from requests_file import FileAdapter

from owslib.wmts import TileMatrix, testXMLValue, _TILE_MATRIX_TAG, _IDENTIFIER_TAG, _SCALE_DENOMINATOR_TAG, \
    _TOP_LEFT_CORNER_TAG, _TILE_WIDTH_TAG, _TILE_HEIGHT_TAG, _MATRIX_WIDTH_TAG, _MATRIX_HEIGHT_TAG


def tilematrixinit(self, elem):
    if elem.tag != _TILE_MATRIX_TAG:
        raise ValueError('%s should be a TileMatrix' % (elem,))
    self.identifier = testXMLValue(elem.find(_IDENTIFIER_TAG)).strip()
    sd = testXMLValue(elem.find(_SCALE_DENOMINATOR_TAG))
    if sd is None:
        raise ValueError('%s is missing ScaleDenominator' % (elem,))
    self.scaledenominator = float(sd)
    tl = testXMLValue(elem.find(_TOP_LEFT_CORNER_TAG))
    if tl is None:
        raise ValueError('%s is missing TopLeftCorner' % (elem,))
    (lon, lat) = tl.split(" ")
    self.topleftcorner = (float(lon), float(lat))
    width = testXMLValue(elem.find(_TILE_WIDTH_TAG))
    height = testXMLValue(elem.find(_TILE_HEIGHT_TAG))
    if (width is None) or (height is None):
        msg = '%s is missing TileWidth and/or TileHeight' % (elem,)
        raise ValueError(msg)
    self.tilewidth = int(width)
    self.tileheight = int(height)
    mw = testXMLValue(elem.find(_MATRIX_WIDTH_TAG))
    mh = testXMLValue(elem.find(_MATRIX_HEIGHT_TAG))
    if (mw is None) or (mh is None):
        msg = '%s is missing MatrixWidth and/or MatrixHeight' % (elem,)
        raise ValueError(msg)
    self.matrixwidth = int(float(mw)) # Fix here, Lunar xml files have decimals which causes int() to error
    self.matrixheight = int(float(mh)) # Fix here, Lunar xml files have decimals which causes int() to error


def request(method, url, **kwargs):
    """
    This method is to override the requests.request library method so that it will accept local files. Please see the
    documentation/code for requests.request (in api.py) for more information.
    :param method:
    :param url:
    :param kwargs:
    :return:
    """
    with requests.sessions.Session() as session:
        session.mount('file://', FileAdapter())
        return session.request(method=method, url=url, **kwargs)


def create_config_wmts(serviceurls, layernames=()):
    """
    This method creates an in-memory version of the mapproxy configuration file, derived from the GetCapabilities
    xml file. This has only been tested on OnEarth-based tile servers such as GIBS and PO.DAAC.
    :param serviceurls: A list of URIs to xml files or wmts service endpoints.
    :param layernames: An optional list of layer names, otherwise it will create a config file with all layers.
    :return: The in-memory version of the mapproxy configuration file.
    """
    requests.request = request  # do the ugly hack
    TileMatrix.__init__ = tilematrixinit # do more ugly hacks

    # An empty configuration file with known defaults
    mapproxy_conf = {
        'services': {
            'wms': {
                'srs': ['EPSG:4326'],
                'max_output_pixels': [6000, 6000],
                'image_formats': ['image/jpeg', 'image/jpg', 'image/png']
            }
        },
        'layers': [],
        'caches': {},
        'sources': {},
        'grids': {},
        'globals': {
            'image': {
                'resampling_method': 'bicubic',
                'formats': {
                    'image/png': {
                        'mode': 'RGBA',
                        'colors': 0,
                        'resampling_method': 'bicubic'
                    },
                    'image/jpeg': {
                        'mode': 'RGB',
                        'colors': 0,
                        'resampling_method': 'bicubic',
                        'encoding_options': {
                            'jpeg_quality': 90
                        }
                    }
                }
            }
        }
    }

    wmtsconfs = []
    for serviceurl in serviceurls:
        wmtsconfs.append(WebMapTileService(serviceurl))

    if len(layernames) == 0:
        layernames = []
        for wmtsconf in wmtsconfs:
            layernames += wmtsconf.contents.keys()
        layernames = sorted(layernames)

    for layername in layernames:
        foundlayer = False

        for wmtsconf in wmtsconfs:
            if layername in wmtsconf.contents:
                foundlayer = True

                cachekey = layername + "_Cache"
                sourcekey = layername + "_Source"
                tilematrixsetkey = list(wmtsconf.contents[layername].tilematrixsetlinks.keys())[0]
                gridkey = layername + "_Grid"
                # Ideally the gridkey is the same as the tilematrixset name. However, when we're combining
                # GetCapabilities files, there may be grids that have the same name, but have different levels of zoom
                # thus each now needs to be unique. That's why there's a gridkey and tilematrixsetkey.

                if gridkey not in mapproxy_conf['grids']:
                    # Generate grid
                    # https://help.openstreetmap.org/questions/9510/understanding-scale
                    magicnumber = 397569610  # see OSM article regarding scale
                    tilematrixset = wmtsconf.tilematrixsets[tilematrixsetkey]
                    tilematrixsetkeys = natsorted(tilematrixset.tilematrix.keys())
                    firsttilematrix = tilematrixset.tilematrix[tilematrixsetkeys[0]]
                    gridtilesize = [firsttilematrix.tilewidth, firsttilematrix.tileheight]
                    
                    if tilematrixset.crs == "urn:ogc:def:crs:EPSG:6.18.3:3857":
                        mapproxy_conf['grids'][gridkey] = {
                            'base': 'GLOBAL_WEBMERCATOR',
                            'tile_size': gridtilesize
                        }
                    else:

                        gridres = []

                        for tilematrixsetid in tilematrixsetkeys:
                            tilematrix = tilematrixset.tilematrix[tilematrixsetid]
                            sd = tilematrix.scaledenominator
                            gridres.append(round(sd / magicnumber, 12))

                        gridbbox = [int(round(firsttilematrix.topleftcorner[0])),
                                    int(round(firsttilematrix.topleftcorner[1] - (gridres[0] * gridtilesize[0]))),
                                    int(round(firsttilematrix.topleftcorner[0] + 2 * (gridres[0] * gridtilesize[0]))),
                                    int(round(firsttilematrix.topleftcorner[1]))]

                        mapproxy_conf['grids'][gridkey] = {
                            'srs': 'EPSG:4326',
                            'bbox': gridbbox,
                            'tile_size': gridtilesize,
                            'res': gridres,
                            'origin': 'ul'
                        }

                urltemplate = wmtsconf.contents[layername].resourceURLs[0]['template']
                url = urltemplate.replace(
                    '{TileCol}', '%(x)s').replace('{TileRow}', '%(y)s').replace(
                    '{TileMatrix}', '%(z)s').replace('{TileMatrixSet}', tilematrixsetkey).replace(
                    '{Style}', list(wmtsconf.contents[layername].styles.keys())[0])

                sourcetransparency = False
                sourceformat = wmtsconf.contents[layername].formats[0].lower()
                if sourceformat == 'image/png':
                    sourcetransparency = True

                mapproxy_conf['sources'][sourcekey] = {
                    'type': 'tile',
                    'url': url,
                    'grid': gridkey,
                    'transparent': sourcetransparency,
                    'http': {
                        'ssl_no_cert_checks': True
                    },
                    'coverage': {
                        'bbox': wmtsconf.contents[layername].boundingBoxWGS84,
                        'srs': 'EPSG:4326'
                    }
                }

                mapproxy_conf['caches'][cachekey] = {
                    'grids': [gridkey],
                    'sources': [sourcekey],
                    'format': sourceformat,
                    'disable_storage': True
                }

                mapproxy_conf['layers'].append({
                    'name': layername,
                    'title': layername,
                    'sources': [cachekey]
                })

        if not foundlayer:
            raise ValueError("Layer not found!", layername)

    return mapproxy_conf


def mapit(mapproxy_conf, layername, outputmimeformat, lonlatbbox, imagesize, outputfilename=None, time=None):
    """
    This automates the creation of a map image.
    :param mapproxy_conf: The mapproxy in-memory configuration dictionary.
    :param layername: The name of the layer to image.
    :param outputmimeformat: The mime format (i.e. image/png, image/jpeg) of the output
    :param lonlatbbox: The bounding box as a tuple, (west, south, east, north)
    :param imagesize: The images size as a tuple, (width, height)
    :param outputfilename: An optional output filename, if None, then no file will be written.
    :param time: An optional time string for layers that have the time dimension
    :return: The binary data for the image generated.
    """
    if time is None:
        time = ''
    mapproxy_conf = copy.deepcopy(mapproxy_conf)  # dup it for replacing time
    for source in mapproxy_conf['sources']:
        mapproxy_conf['sources'][source]['url'] = mapproxy_conf['sources'][source]['url'].replace("{Time}", time)

    transparent = 'false'
    if 'png' in outputmimeformat.lower():
        transparent = 'true'

    querystring = "LAYERS=%s&FORMAT=%s&SRS=EPSG:4326&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&TRANSPARENT=%s&STYLES=&BBOX=%f,%f,%f,%f&WIDTH=%d&HEIGHT=%d" % (
        layername, outputmimeformat, transparent, lonlatbbox[0], lonlatbbox[1], lonlatbbox[2], lonlatbbox[3],
        imagesize[0],
        imagesize[1])

    conf = ProxyConfiguration(mapproxy_conf, conf_base_dir='', seed=False, renderd=False)

    services = conf.configured_services()

    myreq = {
        'QUERY_STRING': querystring,
        'SERVER_NAME': '',
        'SERVER_PORT': '',
        'wsgi.url_scheme': '',
    }

    response = services[0].handle(Request(myreq))
    data = response.data

    if outputfilename:
        f = open(outputfilename, "w")
        f.write(data)
    return data

