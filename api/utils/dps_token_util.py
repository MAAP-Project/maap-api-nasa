"""System-issued DPS job token.

DPS jobs authenticate to the API with whatever the DPS wrapper receives as
``session_key`` from ``GET /members/<username>`` (sent with the dps-token
header). Jobs can be submitted in batches of tens of thousands and can run for
a day, so instead of one token per job, each user has a single system-issued
personal access token that is reused across jobs and rolled over by the API:

* the token lives ``DPS_TOKEN_EXPIRY_SECONDS`` (default 48h);
* once it has less than ``DPS_TOKEN_RENEWAL_THRESHOLD_SECONDS`` (default 24h)
  of life left, the next DPS request gets a freshly issued token, so a job
  always starts with a token valid for at least the threshold;
* the previous token is *not* revoked (jobs still running with it must keep
  working) — it is left to expire, and expired/revoked system tokens are
  pruned on the next issuance so they never accumulate for the user.

The raw token is stored Fernet-encrypted (``token_encrypted``) alongside its
hash so it can be handed back on reuse; user-created tokens never set it.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import or_

import api.settings as settings
from api.maap_database import db
from api.models.personal_access_token import PersonalAccessToken

log = logging.getLogger(__name__)

DPS_TOKEN_NAME = "DPS job token (system-issued)"

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.FERNET_KEY)
    return _fernet


def _system_tokens(user_identifier):
    return db.session.query(PersonalAccessToken) \
        .filter_by(user_identifier=user_identifier) \
        .filter(PersonalAccessToken.token_encrypted.isnot(None))


def _prune_dead_system_tokens(user_identifier, now):
    """Delete this user's system tokens that are expired or revoked."""
    deleted = _system_tokens(user_identifier) \
        .filter(or_(PersonalAccessToken.revoked_at.isnot(None),
                    PersonalAccessToken.expires_at <= now)) \
        .delete(synchronize_session=False)
    if deleted:
        log.debug("Pruned %d expired/revoked DPS token(s) for %s", deleted, user_identifier)
    return deleted


def get_or_create_dps_token(user_identifier):
    """Return the raw DPS token for the member identified by ``user_identifier``
    (the member's email, which is what personal access tokens key on), issuing
    a new one when none exists or the current one is inside the renewal window."""
    now = datetime.now(timezone.utc)
    renewal_threshold = timedelta(seconds=settings.DPS_TOKEN_RENEWAL_THRESHOLD_SECONDS)

    _prune_dead_system_tokens(user_identifier, now)

    current = _system_tokens(user_identifier) \
        .filter(PersonalAccessToken.revoked_at.is_(None)) \
        .order_by(PersonalAccessToken.expires_at.desc()) \
        .first()

    if current is not None and current.expires_at is not None \
            and current.expires_at - now > renewal_threshold:
        db.session.commit()
        return _get_fernet().decrypt(current.token_encrypted.encode("utf-8")).decode("utf-8")

    raw_token = secrets.token_urlsafe(32)
    pat = PersonalAccessToken(
        user_identifier=user_identifier,
        user_origin=settings.NASA_CAS_OIDC_ORIGIN,
        token_name=DPS_TOKEN_NAME,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(seconds=settings.DPS_TOKEN_EXPIRY_SECONDS),
        token_encrypted=_get_fernet().encrypt(raw_token.encode("utf-8")).decode("utf-8"),
    )
    try:
        db.session.add(pat)
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception("Failed to issue DPS token for %s", user_identifier)
        raise

    log.info("Issued new DPS token for %s (expires %s)", user_identifier, pat.expires_at.isoformat())
    return raw_token
