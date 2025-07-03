import pytest
from unittest.mock import MagicMock
from werkzeug.datastructures import FileStorage
from io import BytesIO

from api.utils.security_utils import (
    sanitize_filename,
    validate_ssh_key_file,
    validate_shapefile_upload,
    InvalidFileTypeError,
    FileSizeTooLargeError,
    InvalidRequestError
)
import zipfile

# Tests for sanitize_filename
def test_sanitize_filename_basic():
    assert sanitize_filename("test_file.txt") == "test_file.txt"
    assert sanitize_filename("../../../etc/passwd") == "etc_passwd"
    assert sanitize_filename(" leading_space.txt") == "leading_space.txt"
    assert sanitize_filename("trailing_space.txt ") == "trailing_space.txt"
    assert sanitize_filename("fi!le*n@me.sh") == "fi_le_n_me.sh"
    assert sanitize_filename(".leading_dot.txt") == "leading_dot.txt"
    assert sanitize_filename("_leading_underscore.ini") == "leading_underscore.ini"
    assert sanitize_filename("..double_dot.cfg") == "double_dot.cfg"

# Tests for validate_ssh_key_file
@pytest.fixture
def mock_filestorage_ssh():
    def _mock_filestorage(filename, content, content_type='text/plain'):
        file_bytes = content.encode('utf-8')
        mock_file = BytesIO(file_bytes)
        # Werkzeug FileStorage needs a stream, filename, name, content_type
        # 'name' attribute is often same as filename for FileStorage
        fs = FileStorage(stream=mock_file, filename=filename, name=filename, content_type=content_type)
        return fs
    return _mock_filestorage

def test_validate_ssh_key_valid(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey.pub", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.pub', '.txt', ''])
    fs.stream.seek(0) # Ensure stream is reset for any further reads if necessary

def test_validate_ssh_key_no_extension_allowed(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.pub', '.txt', ''])
    fs.stream.seek(0)

def test_validate_ssh_key_invalid_extension(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey.exe", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError):
        validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.pub', '.txt'])

def test_validate_ssh_key_too_large(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey.pub", "a" * 2000)
    with pytest.raises(FileSizeTooLargeError):
        validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.pub', '.txt', ''])

def test_validate_ssh_key_not_text(mock_filestorage_ssh):
    # Simulate binary content by using bytes that don't form valid UTF-8
    fs = FileStorage(stream=BytesIO(b'\x80\x81\x82'), filename="key.pub", name="key.pub")
    with pytest.raises(InvalidFileTypeError, match="File does not appear to be a valid text file"):
        validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.pub', ''])


# Tests for validate_shapefile_upload
@pytest.fixture
def create_zip_file():
    def _create_zip(file_contents_map, filename="test.zip"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in file_contents_map.items():
                zf.writestr(name, content)
        zip_buffer.seek(0)
        return FileStorage(stream=zip_buffer, filename=filename, name=filename, content_type='application/zip')
    return _create_zip

def test_validate_shapefile_valid(create_zip_file):
    fs = create_zip_file({
        "test.shp": "shp_content",
        "test.shx": "shx_content",
        "test.dbf": "dbf_content"
    })
    validate_shapefile_upload(fs, max_zip_size_bytes=1024*10, max_uncompressed_size_bytes=1024*50)
    fs.stream.seek(0)

def test_validate_shapefile_not_zip():
    fs = FileStorage(stream=BytesIO(b"not a zip"), filename="test.txt", name="test.txt")
    with pytest.raises(InvalidFileTypeError, match="File must be a .zip archive."):
        validate_shapefile_upload(fs, 1024, 1024)

def test_validate_shapefile_zip_too_large(create_zip_file):
    fs = create_zip_file({"test.shp": "content" * 500}) # Make zip content large
    # To properly test zip size, the content needs to be substantial *before* compression.
    # Let's make content that will result in a > 1KB zip
    large_content = "a" * 2048 # This content itself is 2KB
    fs_large_zip = create_zip_file({"test.shp": large_content, "test.shx": "s", "test.dbf": "d"})

    with pytest.raises(FileSizeTooLargeError, match="ZIP file size"):
        validate_shapefile_upload(fs_large_zip, max_zip_size_bytes=1024, max_uncompressed_size_bytes=5000)

def test_validate_shapefile_uncompressed_too_large(create_zip_file):
    fs = create_zip_file({
        "test.shp": "a" * 500,
        "test.shx": "b" * 500,
        "test.dbf": "c" * 500  # Total uncompressed = 1500
    })
    with pytest.raises(FileSizeTooLargeError, match="Total uncompressed size"):
        validate_shapefile_upload(fs, max_zip_size_bytes=1024*10, max_uncompressed_size_bytes=1000)

def test_validate_shapefile_missing_required_files(create_zip_file):
    fs = create_zip_file({"test.shp": "shp_content"})
    with pytest.raises(InvalidFileTypeError, match="ZIP archive must contain .shp, .shx, and .dbf files."):
        validate_shapefile_upload(fs, 1024, 1024)

    fs_missing_shx = create_zip_file({"test.shp": "s", "test.dbf": "d"})
    with pytest.raises(InvalidFileTypeError, match="ZIP archive must contain .shp, .shx, and .dbf files."):
        validate_shapefile_upload(fs_missing_shx, 1024, 1024)

def test_validate_shapefile_bad_zip(create_zip_file):
    # Create a FileStorage with non-zip bytes but .zip extension
    fs = FileStorage(stream=BytesIO(b"this is not zip content"), filename="bad.zip", name="bad.zip")
    with pytest.raises(InvalidFileTypeError, match="Invalid or corrupted ZIP file."): # Our function wraps BadZipFile
        validate_shapefile_upload(fs, 1024, 1024)

def test_validate_ssh_key_filename_missing(mock_filestorage_ssh):
    # Create a FileStorage without a filename
    fs = FileStorage(stream=BytesIO(b"content"), filename=None, name="some_name")
    with pytest.raises(InvalidFileTypeError, match="File name is missing."):
        validate_ssh_key_file(fs, 1024, ['.txt'])

def test_validate_shapefile_empty_zip(create_zip_file):
    fs = create_zip_file({}) # Empty zip
    with pytest.raises(InvalidFileTypeError, match="ZIP archive must contain .shp, .shx, and .dbf files."):
        validate_shapefile_upload(fs, 1024, 1024)

def test_validate_shapefile_subdirectories(create_zip_file):
    fs = create_zip_file({
        "folder/test.shp": "shp_content",
        "folder/test.shx": "shx_content",
        "folder/test.dbf": "dbf_content"
    })
    validate_shapefile_upload(fs, max_zip_size_bytes=1024*10, max_uncompressed_size_bytes=1024*50)
    fs.stream.seek(0)

def test_validate_shapefile_case_insensitive_extensions(create_zip_file):
    fs = create_zip_file({
        "test.SHP": "shp_content",
        "test.Shx": "shx_content",
        "test.dBf": "dbf_content"
    })
    validate_shapefile_upload(fs, max_zip_size_bytes=1024*10, max_uncompressed_size_bytes=1024*50)
    fs.stream.seek(0)

# Example of how you might mock settings for tests that depend on them
# from unittest.mock import patch
# @patch('api.utils.security_utils.settings') # if settings were imported there
# def test_with_mocked_settings(mock_settings, create_zip_file):
#     mock_settings.MAX_ZIP_SIZE = 100
#     mock_settings.MAX_UNCOMPRESSED_SIZE = 200
#     # ... your test logic ...
#     pass

# Note: To test the file content itself (e.g. is it a *valid* shapefile, not just a file named .shp),
# the validate_shapefile_upload would need to use a library like pyshp to attempt to read the shapefile data.
# The current tests focus on presence, naming, and size, as per the implementation.
# If validate_shapefile_upload was enhanced to do deeper inspection, tests would expand similarly.

# Test for when '' is an allowed extension (no extension)
def test_validate_ssh_key_no_extension_explicitly_allowed(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey", "ssh-rsa AAAA...") # filename "mykey"
    validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['']) # Only allow no extension
    fs.stream.seek(0)

def test_validate_ssh_key_no_extension_not_allowed(mock_filestorage_ssh):
    fs = mock_filestorage_ssh("mykey", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError):
        validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.txt']) # Does not allow no extension

def test_validate_ssh_key_filename_is_extension(mock_filestorage_ssh):
    # Test case where filename itself is one of the allowed extensions (e.g. filename="pub")
    fs = mock_filestorage_ssh("pub", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs, max_size_bytes=1024, allowed_extensions=['.txt', 'pub'])
    fs.stream.seek(0)

    fs_fail = mock_filestorage_ssh("pub", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError): # Should fail if "pub" is not in allowed_extensions
         validate_ssh_key_file(fs_fail, max_size_bytes=1024, allowed_extensions=['.txt', '.ssh'])
    fs_fail.stream.seek(0)

    # Test case for empty extension in allowed_extensions
    fs_empty_allowed = mock_filestorage_ssh("mykey", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs_empty_allowed, max_size_bytes=1024, allowed_extensions=['.txt', ''])
    fs_empty_allowed.stream.seek(0)

    fs_empty_not_explicitly_allowed = mock_filestorage_ssh("mykey", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError):
        validate_ssh_key_file(fs_empty_not_explicitly_allowed, max_size_bytes=1024, allowed_extensions=['.txt', '.pub'])
    fs_empty_not_explicitly_allowed.stream.seek(0)

    # Test filename "key" with allowed_extensions=['key', '.pub']
    fs_key_allowed = mock_filestorage_ssh("key", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs_key_allowed, max_size_bytes=1024, allowed_extensions=['key', '.pub'])
    fs_key_allowed.stream.seek(0)

    # Test filename "key" with allowed_extensions=['.key', '.pub'] - should fail
    fs_key_not_allowed = mock_filestorage_ssh("key", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError):
        validate_ssh_key_file(fs_key_not_allowed, max_size_bytes=1024, allowed_extensions=['.key', '.pub'])
    fs_key_not_allowed.stream.seek(0)

    # Test filename ".key" with allowed_extensions=['.key', '.pub'] - should pass
    fs_dot_key_allowed = mock_filestorage_ssh(".key", "ssh-rsa AAAA...")
    validate_ssh_key_file(fs_dot_key_allowed, max_size_bytes=1024, allowed_extensions=['.key', '.pub'])
    fs_dot_key_allowed.stream.seek(0)

    # Test filename ".key" with allowed_extensions=['key', '.pub'] - should fail
    fs_dot_key_not_allowed = mock_filestorage_ssh(".key", "ssh-rsa AAAA...")
    with pytest.raises(InvalidFileTypeError):
        validate_ssh_key_file(fs_dot_key_not_allowed, max_size_bytes=1024, allowed_extensions=['key', '.pub'])
    fs_dot_key_not_allowed.stream.seek(0)

print("Finished creating test_security_utils.py")
