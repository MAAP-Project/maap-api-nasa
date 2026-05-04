import uuid
from datetime import datetime, timezone

from api.models import Base
from api.maap_database import db


class PersonalAccessToken(Base):
    __tablename__ = 'personal_access_token'

    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.String(), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_identifier = db.Column(db.String(), nullable=False)
    user_origin = db.Column(db.String(), nullable=False)
    token_name = db.Column(db.String())
    token_hash = db.Column(db.String(), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    revoked_at = db.Column(db.DateTime(timezone=True))

    @property
    def is_active(self):
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at < datetime.now(timezone.utc):
            return False
        return True

    def __repr__(self):
        return "<PersonalAccessToken(token_id={self.token_id!r})>".format(self=self)
