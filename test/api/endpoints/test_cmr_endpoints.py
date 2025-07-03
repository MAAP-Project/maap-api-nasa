import unittest
import json
from unittest.mock import patch, MagicMock
from io import BytesIO
from werkzeug.datastructures import FileStorage
import zipfile

from api.maapapp import app # Your Flask app instance
from api.models.member import Member # If needed for auth mocking
from api.models.role import Role
from api.maap_database import db
from api.models import initialize_sql
from api import settings

# Mock get_authorized_user for CMR endpoints if they require authentication
# For shapefile upload, it does not seem to explicitly call get_authorized_user,
# but operations it calls (like CMR search) might.
# Assuming shapefile upload itself is unauthenticated or auth is handled by a general decorator.
# If it needs auth:
# def mock_cmr_authorized_user():
#     mock_user = MagicMock(spec=Member)
#     mock_user.id = 1
#     mock_user.username = 'cmr_testuser'
#     return mock_user

# If cmr.py's get_authorized_user is from api.auth.security, then patch that.
# For now, let's assume the endpoint itself doesn't gate on a specific user for upload,
# but the subsequent CMR request might.

class TestCmrEndpoints(unittest.TestCase):
    """Test suite for CMR endpoint, especially shapefile uploads."""

    @classmethod
    def setUpClass(cls):
        cls.app = app.test_client()
        with app.app_context():
            initialize_sql(db.engine)
            # Create roles if they don't exist (needed by base models/app setup)
            TestCmrEndpoints._create_roles_if_not_exist()


    def setUp(self):
        """Set up test data/state before each test."""
        with app.app_context():
            # Clean relevant tables, if any are affected by these tests
            db.session.commit()
        # Mock external CMR call
        self.mock_cmr_patcher = patch('api.endpoints.cmr.requests.get')
        self.mock_cmr_get = self.mock_cmr_patcher.start()

        # Configure a default successful response for CMR
        self.mock_cmr_response = MagicMock()
        self.mock_cmr_response.status_code = 200
        self.mock_cmr_response.headers = {'content-type': 'application/json'}
        self.mock_cmr_response.text = json.dumps({"feed": {"entry": [{"id": "C123-TEST"}]}})
        self.mock_cmr_get.return_value = self.mock_cmr_response

    def tearDown(self):
        self.mock_cmr_patcher.stop()
        with app.app_context():
            db.session.rollback() # Ensure session is clean

    @staticmethod
    def _create_roles_if_not_exist():
        roles_to_ensure = [
            (Role.ROLE_GUEST, 'guest'), (Role.ROLE_MEMBER, 'member'), (Role.ROLE_ADMIN, 'admin')
        ]
        for role_id, role_name in roles_to_ensure:
            if not db.session.query(Role).get(role_id): db.session.add(Role(id=role_id, role_name=role_name))
        db.session.commit()

    def _create_zip_filestorage(self, file_contents_map, zip_filename="test.zip"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in file_contents_map.items():
                zf.writestr(name, content.encode('utf-8') if isinstance(content, str) else content)
        zip_buffer.seek(0)
        return FileStorage(stream=zip_buffer, filename=zip_filename, name=zip_filename, content_type='application/zip')

    def _upload_shapefile(self, filestorage):
        data = {'file': filestorage}
        return self.app.post('/api/cmr/collections/shapefile', data=data, content_type='multipart/form-data')

    def test_shapefile_upload_valid(self):
        """Test: Successfully upload a valid shapefile ZIP."""
        fs = self._create_zip_filestorage({
            "myshape.shp": "shp_dummy_content",
            "myshape.shx": "shx_dummy_content",
            "myshape.dbf": "dbf_dummy_content"
        })
        response = self._upload_shapefile(fs)
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("feed", response_data) # Check for CMR response structure
        self.mock_cmr_get.assert_called_once() # Verify CMR was actually called

    def test_shapefile_upload_no_file(self):
        """Test: Uploading with no file results in BadRequest."""
        response = self.app.post('/api/cmr/collections/shapefile', data={}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("No file uploaded", response_data.get('message', ''))

    def test_shapefile_upload_not_a_zip(self):
        """Test: Uploading a non-ZIP file."""
        fs = FileStorage(stream=BytesIO(b"this is not a zip"), filename="test.txt", content_type="text/plain")
        response = self._upload_shapefile(fs)
        self.assertEqual(response.status_code, 400) # InvalidFileTypeError
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("File must be a .zip archive", response_data.get('message', ''))

    def test_shapefile_upload_zip_too_large(self):
        """Test: Uploading a ZIP file that is too large."""
        original_max_size = settings.MAX_SHAPEFILE_ZIP_SIZE_BYTES
        settings.MAX_SHAPEFILE_ZIP_SIZE_BYTES = 50 # Small limit for test

        fs = self._create_zip_filestorage({"large.shp": "a" * 100, "large.shx": "b", "large.dbf": "c"})
        response = self._upload_shapefile(fs)

        settings.MAX_SHAPEFILE_ZIP_SIZE_BYTES = original_max_size # Reset

        self.assertEqual(response.status_code, 413) # FileSizeTooLargeError
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("ZIP file size", response_data.get('message', ''))
        self.assertIn("exceeds limit", response_data.get('message', ''))

    def test_shapefile_upload_uncompressed_too_large(self):
        """Test: Uploading a ZIP with uncompressed content too large."""
        original_max_uncompressed_size = settings.MAX_SHAPEFILE_UNCOMPRESSED_SIZE_BYTES
        settings.MAX_SHAPEFILE_UNCOMPRESSED_SIZE_BYTES = 150 # Small limit

        fs = self._create_zip_filestorage({
            "file1.shp": "a" * 100, # 100 bytes
            "file1.shx": "b" * 30,  # 30 bytes
            "file1.dbf": "c" * 30   # 30 bytes, total 160
        })
        response = self._upload_shapefile(fs)

        settings.MAX_SHAPEFILE_UNCOMPRESSED_SIZE_BYTES = original_max_uncompressed_size # Reset

        self.assertEqual(response.status_code, 413) # FileSizeTooLargeError
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("Total uncompressed size", response_data.get('message', ''))

    def test_shapefile_upload_missing_required_files_in_zip(self):
        """Test: Uploading ZIP missing .shp, .shx, or .dbf."""
        fs_no_shp = self._create_zip_filestorage({"test.shx": "x", "test.dbf": "d"})
        response_no_shp = self._upload_shapefile(fs_no_shp)
        self.assertEqual(response_no_shp.status_code, 400) # InvalidFileTypeError
        data_no_shp = json.loads(response_no_shp.data.decode('utf-8'))
        self.assertIn("ZIP archive must contain .shp, .shx, and .dbf files", data_no_shp.get('message', ''))

        fs_no_shx = self._create_zip_filestorage({"test.shp": "s", "test.dbf": "d"})
        response_no_shx = self._upload_shapefile(fs_no_shx)
        self.assertEqual(response_no_shx.status_code, 400)
        data_no_shx = json.loads(response_no_shx.data.decode('utf-8'))
        self.assertIn("ZIP archive must contain .shp, .shx, and .dbf files", data_no_shx.get('message', ''))


    def test_shapefile_upload_corrupted_zip(self):
        """Test: Uploading a corrupted ZIP file."""
        fs = FileStorage(stream=BytesIO(b"PKthisisacorruptzip"), filename="corrupt.zip", content_type="application/zip")
        response = self._upload_shapefile(fs)
        self.assertEqual(response.status_code, 400) # InvalidFileTypeError (from BadZipFile)
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("Invalid or corrupted ZIP file", response_data.get('message', ''))

    def test_shapefile_upload_cmr_call_timeout(self):
        """Test: CMR call times out after shapefile processing."""
        self.mock_cmr_get.side_effect = requests.exceptions.Timeout("CMR timed out")

        fs = self._create_zip_filestorage({
            "myshape.shp": "shp_dummy_content", "myshape.shx": "shx_dummy_content", "myshape.dbf": "dbf_dummy_content"
        })
        response = self._upload_shapefile(fs)

        self.assertEqual(response.status_code, 503) # ServiceUnavailable
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("CMR service timed out", response_data.get('message', ''))

    def test_shapefile_upload_cmr_call_http_error(self):
        """Test: CMR call returns an HTTP error."""
        self.mock_cmr_response.status_code = 500
        self.mock_cmr_response.raise_for_status.side_effect = requests.exceptions.HTTPError("CMR Server Error")
        self.mock_cmr_get.return_value = self.mock_cmr_response

        fs = self._create_zip_filestorage({
            "myshape.shp": "s", "myshape.shx": "x", "myshape.dbf": "d"
        })
        response = self._upload_shapefile(fs)

        self.assertEqual(response.status_code, 503) # ServiceUnavailable
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("Could not connect to CMR service", response_data.get('message', ''))

    # This test depends on how shapefile.Reader (pyshp) is used.
    # If validate_shapefile_upload or the endpoint tries to parse the shapefile data itself.
    # The current implementation of ShapefileUpload.post does use shapefile.Reader.
    def test_shapefile_upload_invalid_shapefile_content(self):
        """Test: Uploading a ZIP with invalid shapefile content (e.g., malformed .shp)."""
        # This requires creating a "bad" .shp file content.
        # For simplicity, we'll mock shapefile.Reader to raise ShapefileException.

        fs = self._create_zip_filestorage({
            "bad.shp": "actually_bad_shp_content",
            "bad.shx": "shx",
            "bad.dbf": "dbf"
        })

        with patch('api.endpoints.cmr.shp_validator.Reader') as mock_shp_reader:
            mock_shp_reader.side_effect = shp_validator.ShapefileException("Malformed shapefile data")
            response = self._upload_shapefile(fs)

        self.assertEqual(response.status_code, 400) # InvalidRequestError
        response_data = json.loads(response.data.decode('utf-8'))
        self.assertIn("Invalid shapefile content: Malformed shapefile data", response_data.get('message', ''))

if __name__ == '__main__':
    unittest.main()
