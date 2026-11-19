"""
Resolve and authorize the S3 output target (bucket + prefix) of a DPS job.

MAAP-Project/Community#1336: a user may ask for job outputs to land in an
organization bucket they can write to, instead of the platform workspace bucket.

- No ``output_bucket``: the default target is used (the platform workspace
  bucket, prefix = username). ``output_prefix`` is rejected. Nothing is sent to
  Mozart, so the executor falls back to ``DEFAULT_OUTPUT_BUCKET`` from the
  worker's maap-dps.env and the username, exactly as before.
- ``output_bucket`` given: prefix = normalized ``output_prefix`` or the username.
  The user must have a writable org grant (``organization_s3_access``, through
  org membership including descendant orgs) whose prefix covers it. No STS call.

This is the only gate: nothing in HySDS enforces an allow-list.
"""
from api import settings
from api.utils import s3_access

OUTPUT_TARGET_PARAMS = ("output_bucket", "output_prefix")

# Generous but bounded: S3 keys max out at 1024 bytes and the executor appends
# /dps_output/<algorithm>/<version>/<timestamp> plus the product files.
MAX_PREFIX_LENGTH = 512


class OutputTargetError(ValueError):
    """The requested output target is malformed (400) or not permitted (403)."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_prefix(prefix):
    """
    Strip leading/trailing slashes and collapse repeated slashes. Reject '.' or
    '..' segments, control characters and over-long values.
    """
    if not isinstance(prefix, str):
        raise OutputTargetError("output_prefix must be a string")
    if any(ord(c) < 32 or ord(c) == 127 for c in prefix):
        raise OutputTargetError("output_prefix must not contain control characters")
    segments = [s for s in prefix.strip().split("/") if s != ""]
    if not segments:
        raise OutputTargetError("output_prefix must not be empty")
    for segment in segments:
        if segment in (".", ".."):
            raise OutputTargetError("output_prefix must not contain '.' or '..' path segments")
        if segment != segment.strip():
            raise OutputTargetError("output_prefix segments must not start or end with whitespace")
    normalized = "/".join(segments)
    if len(normalized.encode("utf-8")) > MAX_PREFIX_LENGTH:
        raise OutputTargetError(f"output_prefix must be at most {MAX_PREFIX_LENGTH} bytes")
    return normalized


def _grant_prefix(grant):
    raw = grant.get("bucket_prefix")
    if _is_blank(raw):
        return None
    return "/".join(s for s in raw.split("/") if s != "")


def _covers(grant_prefix, prefix):
    """Segment-boundary match: a grant on 'a/b' covers 'a/b' and 'a/b/c', never 'a/bc'."""
    return grant_prefix is None or prefix == grant_prefix or prefix.startswith(grant_prefix + "/")


def resolve_output_target(user_id, username, output_bucket=None, output_prefix=None):
    """
    Return ``(bucket, prefix)`` to send to Mozart, or ``None`` for the default target.

    :raises OutputTargetError: 400 for malformed input, 403 when not permitted
    """
    if _is_blank(output_bucket):
        if not _is_blank(output_prefix):
            raise OutputTargetError("output_prefix requires output_bucket")
        return None

    if not isinstance(output_bucket, str) or not s3_access._is_valid_bucket_name(output_bucket.strip()):
        raise OutputTargetError(f"'{output_bucket}' is not a valid S3 bucket name")
    bucket = output_bucket.strip()
    prefix_supplied = not _is_blank(output_prefix)
    prefix = normalize_prefix(output_prefix) if prefix_supplied else username

    # Naming the workspace bucket with the default prefix is just the default target.
    # Custom prefixes on the workspace bucket are out of scope for iteration 1.
    if settings.WORKSPACE_BUCKET and bucket == settings.WORKSPACE_BUCKET:
        if prefix == username:
            return None
        raise OutputTargetError(
            f"Custom output_prefix is not supported on the default bucket '{bucket}'", 403)

    grants = [g for g in s3_access.get_user_s3_access(user_id) if g.get("bucket_name") == bucket]
    # get_user_s3_access aggregates with bool_and, so read-write wins on overlapping grants.
    covering = [g for g in grants if _covers(_grant_prefix(g), prefix)]
    if any(not g.get("readonly") for g in covering):
        return bucket, prefix

    if covering:
        raise OutputTargetError(
            f"You have read-only access to s3://{bucket}/{prefix}; job outputs need write access", 403)
    writable_prefixes = sorted(_grant_prefix(g) for g in grants
                               if not g.get("readonly") and _grant_prefix(g) is not None)
    if writable_prefixes and not prefix_supplied:
        raise OutputTargetError(
            f"Your write access to bucket '{bucket}' is limited to prefix(es) "
            f"{', '.join(writable_prefixes)}; set output_prefix to a path under one of them", 403)
    raise OutputTargetError(f"You are not permitted to write job outputs to s3://{bucket}/{prefix}", 403)


def apply_output_target(params, user_id, username, output_bucket=None, output_prefix=None):
    """
    Resolve the output target and set it on the Mozart job ``params`` in place.

    Any ``output_bucket``/``output_prefix`` already in ``params`` (e.g. passed as an
    ordinary algorithm input, which hysds-io now declares) is always removed first,
    so only values that passed the permission check ever reach Mozart.
    """
    for name in OUTPUT_TARGET_PARAMS:
        params.pop(name, None)
    target = resolve_output_target(user_id, username, output_bucket, output_prefix)
    if target is not None:
        params["output_bucket"], params["output_prefix"] = target
    return params
