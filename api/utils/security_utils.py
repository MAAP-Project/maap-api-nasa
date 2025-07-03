import os
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, Unauthorized, ServiceUnavailable
from werkzeug.utils import secure_filename
import zipfile
import shapefile # Added for shapefile validation if direct inspection is needed

# Define custom exception classes inheriting from Werkzeug's HTTP exceptions
class InvalidFileTypeError(BadRequest):
    description = "Invalid file type."

class FileSizeTooLargeError(RequestEntityTooLarge):
    description = "File size exceeds the allowable limit."

class InvalidRequestError(BadRequest):
    description = "The request is invalid or malformed."

class AuthenticationError(Unauthorized):
    description = "Authentication failed or is required."

class ExternalServiceError(ServiceUnavailable):
    description = "An external service is currently unavailable or failed to respond."

def sanitize_filename(filename):
    """
    Sanitizes a filename using Werkzeug's secure_filename and removes leading dots/underscores.
    """
    filename = secure_filename(filename)
    # Further remove any leading dots or underscores that secure_filename might leave in some cases
    # or if the original filename started with multiple such characters.
    while filename.startswith('.') or filename.startswith('_'):
        filename = filename[1:]
    return filename

def validate_ssh_key_file(file_storage, max_size_bytes, allowed_extensions):
    """
    Validates an uploaded SSH key file.
    - Checks file extension.
    - Checks file size.
    """
    filename = file_storage.filename
    if not filename: # Should not happen with FileStorage but good for robustness
        raise InvalidFileTypeError("File name is missing.")

    _, ext = os.path.splitext(filename)
    if ext.lower() not in allowed_extensions and '' not in allowed_extensions: # allow no extension if '' is present
         # Check if filename itself is an allowed extension (for files like 'mykey' with no dot)
        if filename.lower() not in allowed_extensions:
            raise InvalidFileTypeError(f"Invalid file extension: {ext}. Allowed: {allowed_extensions}")

    # Check file size (UploadedFile.tell() gives current position, seek to end then tell for size)
    file_storage.seek(0, os.SEEK_END)
    file_size = file_storage.tell()
    file_storage.seek(0)  # Reset stream position

    if file_size > max_size_bytes:
        raise FileSizeTooLargeError(f"File size {file_size} bytes exceeds limit of {max_size_bytes} bytes.")

    # Optionally, attempt to read and decode to ensure it's text-based if strict
    try:
        file_storage.read(max_size_bytes + 1).decode('utf-8') # read a bit more to check total size again indirectly
        file_storage.seek(0)
    except UnicodeDecodeError:
        raise InvalidFileTypeError("File does not appear to be a valid text file (UTF-8 encoding expected).")
    except Exception as e: # Catch other read errors
        raise InvalidFileTypeError(f"Could not read or process file: {str(e)}")


def validate_shapefile_upload(file_storage, max_zip_size_bytes, max_uncompressed_size_bytes):
    """
    Validates an uploaded shapefile (ZIP archive).
    - Checks if it's a ZIP file (by filename extension, could add magic number check).
    - Checks ZIP file size.
    - Validates that the ZIP archive contains required shapefile components (.shp, .shx, .dbf).
    - Checks total uncompressed size of these components.
    """
    filename = file_storage.filename
    if not filename or not filename.lower().endswith('.zip'):
        raise InvalidFileTypeError("File must be a .zip archive.")

    # Check ZIP file size
    file_storage.seek(0, os.SEEK_END)
    zip_file_size = file_storage.tell()
    file_storage.seek(0)

    if zip_file_size > max_zip_size_bytes:
        raise FileSizeTooLargeError(f"ZIP file size {zip_file_size} bytes exceeds limit of {max_zip_size_bytes} bytes.")

    required_extensions = ['.shp', '.shx', '.dbf']
    found_extensions = {ext: False for ext in required_extensions}
    total_uncompressed_size = 0

    try:
        with zipfile.ZipFile(file_storage, 'r') as zf:
            archive_filenames = zf.namelist()

            # Check for at least one set of required files (sharing the same base name)
            # This is a simplified check; a robust one would group files by basename
            has_shp = any(name.lower().endswith('.shp') for name in archive_filenames)
            has_shx = any(name.lower().endswith('.shx') for name in archive_filenames)
            has_dbf = any(name.lower().endswith('.dbf') for name in archive_filenames)

            if not (has_shp and has_shx and has_dbf):
                 raise InvalidFileTypeError(f"ZIP archive must contain .shp, .shx, and .dbf files.")

            # Check uncompressed size of all members (or just the required ones)
            for member_info in zf.infolist():
                # Could refine to only sum sizes of .shp, .shx, .dbf if desired
                total_uncompressed_size += member_info.file_size

                # Check individual file types if needed (e.g. ensure .shp is a valid shapefile)
                # For now, just checking presence and total size

            if total_uncompressed_size > max_uncompressed_size_bytes:
                raise FileSizeTooLargeError(
                    f"Total uncompressed size {total_uncompressed_size} bytes "
                    f"exceeds limit of {max_uncompressed_size_bytes} bytes."
                )
    except zipfile.BadZipFile:
        file_storage.seek(0) # Reset stream in case of partial read
        raise InvalidFileTypeError("Invalid or corrupted ZIP file.")
    except Exception as e: # Catch other potential errors during zip processing
        file_storage.seek(0)
        raise InvalidRequestError(f"Error processing ZIP file: {str(e)}")
    finally:
        # Ensure the file stream is reset if it was passed around,
        # though with 'with open' it's handled for that scope.
        # If file_storage is kept open, resetting is important.
        file_storage.seek(0)
