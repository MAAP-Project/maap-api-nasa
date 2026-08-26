-- Adds EDL refresh-token support to the member table.
-- Required because db.create_all() does not alter existing tables.
-- Run against each venue's database before deploying the API changes.
ALTER TABLE member ADD COLUMN IF NOT EXISTS urs_refresh_token VARCHAR;
ALTER TABLE member ADD COLUMN IF NOT EXISTS urs_token_expiration TIMESTAMP;
