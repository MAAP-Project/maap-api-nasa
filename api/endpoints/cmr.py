import logging
import os
import requests
import shapefile
from api import settings
from zipfile import ZipFile
import tempfile
from flask import request, json, Response, stream_with_context
from flask_restx import Resource
from flask_api import status
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, ServiceUnavailable
from api.restplus import api
from api.auth.security import get_authorized_user, edl_federated_request
from api.maap_database import db
from api.models.member import Member
from urllib import parse
from api.utils.security_utils import validate_shapefile_upload, sanitize_filename, InvalidFileTypeError, FileSizeTooLargeError, InvalidRequestError
import zipfile # Already imported, ensure it's available for specific exceptions
import shapefile as shp_validator # Alias to avoid confusion if shapefile is also a var name

try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse as urlparse

log = logging.getLogger(__name__)

ns = api.namespace('cmr', description='Operations related to CMR')


@ns.route('/collections')
class CmrCollection(Resource):

    def get(self):
        """
        CMR collections

            Examples:

            Find collection by concept id
            https://api.dit.maap-project.org/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP

            With multiple dataset ids
            https://api.dit.maap-project.org/api/cmr/collections?concept_id[]=C1200015068-NASA_MAAP&concept_id[]=C1200090707-NASA_MAAP

            Find collections by bounding box
            https://api.dit.maap-project.org/api/cmr/collections?bounding_box=-35.4375,-55.6875,-80.4375,37.6875

        For a comprehensive list of collection search examples, see: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html#collection-search-by-parameters
        """

        resp = req(request.query_string, 'collections')

        return respond(resp)


@ns.route('/collections/shapefile')
class ShapefileUpload(Resource):

    def post(self):
        """
        CMR collections search by shape file
            File input expected: .zip including .shp, .dbf, and .shx file
        """
        if 'file' not in request.files:
            log.error('Shapefile upload attempt with no file')
            raise BadRequest('No file uploaded.')

        f = request.files['file']

        # It's good practice to sanitize the filename, even if not directly used for storage here,
        # in case logs or temporary file creation uses it.
        _ = sanitize_filename(f.filename) # Result not directly used, but good to run

        temp_dir = None # For extracting files if needed by shapefile.Reader with paths
        dst_path = None

        try:
            # Validate the uploaded file (type, size, content)
            # The validate_shapefile_upload function handles ZIP checks, member presence, and size limits.
            # It expects a file-like object, so f (FileStorage) is fine.
            validate_shapefile_upload(
                f,
                settings.MAX_SHAPEFILE_ZIP_SIZE_BYTES,
                settings.MAX_SHAPEFILE_UNCOMPRESSED_SIZE_BYTES
            )
            # f.seek(0) should be handled by validate_shapefile_upload if it reads the file

            # The shapefile.Reader can often read from file-like objects directly from the zip.
            # To do this robustly, we might need to extract to a temporary location if Reader
            # doesn't handle in-memory zip file members well for all its needs (e.g. .dbf, .shx access).
            # Let's try with a temporary file for the ZIP first.

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip_file:
                f.save(tmp_zip_file) # Save FileStorage to a temporary file path
                dst_path = tmp_zip_file.name

            # Now use the path with ZipFile and shapefile.Reader
            # This ensures shapefile.Reader can access related files (.shx, .dbf) correctly.
            with ZipFile(dst_path, 'r') as zf:
                shp_filename = None
                # Find the .shp file, assuming one primary shapefile per ZIP for this use case
                for member_name in zf.namelist():
                    if member_name.lower().endswith('.shp'):
                        shp_filename = member_name
                        break

                if not shp_filename:
                    # This should have been caught by validate_shapefile_upload if it checks namelist
                    raise InvalidFileTypeError("No .shp file found in the archive.")

                # shapefile.Reader needs to access .shp, .shx, .dbf.
                # It can take BytesIO for shp, shx, dbf.
                # Let's extract them to BytesIO objects.
                shp_io = None
                shx_io = None
                dbf_io = None

                # Construct expected .shx and .dbf names from .shp name
                base_name, _ = os.path.splitext(shp_filename)
                shx_expected_name = base_name + ".shx"
                dbf_expected_name = base_name + ".dbf"

                # Search for case-insensitive matches in the zip file
                for member_name_in_zip in zf.namelist():
                    if member_name_in_zip.lower() == shp_filename.lower():
                         shp_io = zf.open(member_name_in_zip)
                    elif member_name_in_zip.lower() == shx_expected_name.lower():
                         shx_io = zf.open(member_name_in_zip)
                    elif member_name_in_zip.lower() == dbf_expected_name.lower():
                         dbf_io = zf.open(member_name_in_zip)

                if not all([shp_io, shx_io, dbf_io]):
                    # This should also be caught by validate_shapefile_upload
                    raise InvalidFileTypeError("Required shapefile components (.shp, .shx, .dbf) not found or accessible with the same base name.")

                r = shp_validator.Reader(shp=shp_io, shx=shx_io, dbf=dbf_io)
                bbox = ','.join(map(str, r.bbox))

                # Close BytesIO objects
                if shp_io: shp_io.close()
                if shx_io: shx_io.close()
                if dbf_io: dbf_io.close()

        except (InvalidFileTypeError, FileSizeTooLargeError, InvalidRequestError) as e:
            log.error(f"Shapefile upload validation failed: {e.description}")
            raise e # Re-raise to be handled by Flask/RestX
        except shp_validator.ShapefileException as e:
            log.error(f"Error reading shapefile: {e}")
            raise InvalidRequestError(f"Invalid shapefile content: {e}")
        except zipfile.BadZipFile:
            log.error("Uploaded file is not a valid ZIP archive.")
            raise InvalidFileTypeError("Uploaded file is not a valid ZIP archive.")
        except Exception as e:
            log.error(f"Unexpected error processing shapefile: {e}")
            raise ServiceUnavailable("An unexpected error occurred while processing the shapefile.")
        finally:
            if dst_path and os.path.exists(dst_path):
                os.remove(dst_path) # Clean up the temporary file
            f.seek(0) # Reset original FileStorage stream just in case

        # Proceed with CMR search using bbox
        url = os.path.join(settings.CMR_URL, 'search', 'collections')
        try:
            cmr_resp = requests.get(url, headers=get_search_headers(), params={'bounding_box': bbox}, timeout=settings.REQUESTS_TIMEOUT_SECONDS)
            cmr_resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        except requests.exceptions.Timeout:
            log.error("Timeout connecting to CMR for shapefile search.")
            raise ServiceUnavailable("CMR service timed out.")
        except requests.exceptions.RequestException as e:
            log.error(f"CMR request failed for shapefile search: {e}")
            raise ServiceUnavailable(f"Could not connect to CMR service: {e}")

        return respond(cmr_resp)


@ns.route('/granules')
class CmrGranules(Resource):

    def get(self):
        """
        CMR granules

            Examples:

            Find granules by granule ur
            https://api.dit.maap-project.org/api/cmr/granules?granule_ur=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin

            With multiple dataset ids
            https://api.dit.maap-project.org/api/cmr/granules?granule_ur[]=uavsar_AfriSAR_v1-cov_lopenp_14043_16008_140_001_160225-geo_cov_4-4.bin&granule_ur[]=biosar1_105_kz.tiff

            Find granules by instrument
            https://api.dit.maap-project.org/api/cmr/granules?instrument=UAVSAR


        For a comprehensive list of granule search examples, see: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html#granule-search-by-parameters
        """

        resp = req(request.query_string, 'granules')

        return respond(resp)


@ns.route('/granules/<string:file_uri>/data')
class CmrGranuleData(Resource):
    """
    CMR granule data

        Download granule by file URI
        file_uri: a UTF-8 encoded URI

        Example:
        https://api.maap-project.org/api/cmr/granules/https%3A%2F%2Fdata.ornldaac.earthdata.nasa.gov%2Fprotected%2Fgedi%2FGEDI_L3_Land_Surface_Metrics%2Fdata%2FGEDI03_elev_lowestmode_stddev_2019108_2020106_001_08.tif/data
    """

    def get(self, file_uri):
        s = requests.Session()
        response = s.get(parse.unquote(file_uri), stream=True)

        if response.status_code == 401:
            maap_user = get_authorized_user()

            if maap_user is None:
                return Response(response.text, status=401)
            else:
                urs_token = db.session.query(Member).filter_by(id=maap_user.id).first().urs_token
                s.headers.update({'Authorization': f'Bearer {urs_token},Basic {settings.MAAP_EDL_CREDS}',
                                  'Connection': 'close'})

                response = s.get(url=response.url, stream=True)

                if response.status_code >= 400:
                    return Response(response.text, status=response.status_code)

        return Response(
            response=stream_with_context(response.iter_content(chunk_size=1024 * 10)),
            content_type=response.headers.get('Content-Type'),
            direct_passthrough=True)


def get_search_headers():
    accept = next(iter(request.headers.getlist('accept') or ['application/json']), ['application/json'])

    return {
            'Accept': accept,
            'Echo-Token': settings.CMR_API_TOKEN,
            'Client-Id': settings.CMR_CLIENT_ID
        }


# Preserves keys that occur more than once, as allowed for in CMR
def parse_query_string(qs):
    return urlparse.parse_qs(qs)


def req(query_string, search_type):
    url = os.path.join(settings.CMR_URL, 'search', search_type)
    parms = parse_query_string(query_string)

    # If an alternate cmr_host is specified in a search request,
    # use that in place of the default config 'CMR_URL' setting.
    if 'cmr_host'.encode('utf-8') in parms.keys():
        cmr_host = parms.pop('cmr_host'.encode('utf-8'))[0]
        url = os.path.join('https://' + cmr_host.decode('utf-8'), 'search', search_type)

    return requests.get(url, headers=get_search_headers(), params=parms)


def respond(response):
    response_text = response.text if response.status_code == status.HTTP_200_OK else 'CMR Error %s' % response.text

    if response.text == '':
        return {}
    else:
        if "xml" in response.headers['content-type']:
            return response_text, response.status_code, {'Content-Type': 'application/xml'}
        else:
            return json.loads(response.text)
