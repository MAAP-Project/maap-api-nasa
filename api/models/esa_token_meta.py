from datetime import datetime, timezone

from api.models import Base
from api.maap_database import db


class EsaTokenMeta(Base):
    """Local, best-effort metadata for ESA-managed tokens.

    ESA personal access tokens are created and stored on ESA's gateway, not in
    our personal_access_token table. ESA does not return a creation timestamp,
    so we record our own here — keyed by the ESA token_id — purely to keep the
    Console UI consistent with locally-managed NASA tokens. This timestamp is
    NOT authoritative (it marks when we proxied the create request, not ESA's
    own record) and is never used for authentication.
    """
    __tablename__ = 'esa_token_meta'

    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.String(), unique=True, nullable=False)
    user_identifier = db.Column(db.String(), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return "<EsaTokenMeta(token_id={self.token_id!r})>".format(self=self)
