-- Table required by db.py's save_contact(). Column names, nullability, and
-- the UNIQUE constraint on airport_name all match db.py's ContactRecord and
-- its ON CONFLICT (airport_name) DO UPDATE upsert logic exactly -- if you
-- change one, change the other.

CREATE TABLE IF NOT EXISTS airport_contacts (
    id                SERIAL PRIMARY KEY,

    -- Required fields -- db.py's ContactRecord rejects a save without these.
    -- airport_name is UNIQUE because db.py upserts on it: a second save for
    -- the same airport updates this row instead of creating a duplicate.
    airport_name      VARCHAR(255) NOT NULL UNIQUE,
    location          VARCHAR(255) NOT NULL,
    full_name         VARCHAR(255) NOT NULL,
    job_title         VARCHAR(255) NOT NULL,
    email             VARCHAR(255) NOT NULL,
    email_confidence  VARCHAR(20)  NOT NULL,  -- db.py restricts this to 'high' or 'medium'
    source_url        VARCHAR(500) NOT NULL,

    -- Optional fields.
    iata_code         VARCHAR(10),
    icao_code         VARCHAR(10),
    phone             VARCHAR(50),
    linkedin_url      VARCHAR(500),
    contact_form_url  VARCHAR(500),

    status            VARCHAR(20)  DEFAULT 'verified'
);

-- If a table already exists from an earlier, more permissive version of this
-- project (where email was optional), the ALTER below will fail on any
-- existing row with a NULL email. Either delete those rows first, or backfill
-- a real email before running it:
--
--   DELETE FROM airport_contacts WHERE email IS NULL;
--   ALTER TABLE airport_contacts ALTER COLUMN email SET NOT NULL;
--
-- Same idea applies to any other column being tightened from nullable to
-- NOT NULL on an existing table.