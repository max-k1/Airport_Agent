"""
Database layer for verified named-person airport contacts.

This version is intentionally REAL-EMAIL-ONLY:
- a named individual and email are required
- generic inboxes are rejected
- confidence is restricted to high/medium
- speculative/guessed contacts are not accepted
"""

import os
from typing import Literal, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

load_dotenv()

GENERIC_EMAIL_PREFIXES = {
    "info", "contact", "admin", "support", "enquiries", "sales", "hello"
}


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


class ContactRecord(BaseModel):
    airport_name: str
    location: str
    full_name: str
    job_title: str
    email: str
    email_confidence: Literal["high", "medium"]
    iata_code: Optional[str] = None
    icao_code: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    contact_form_url: Optional[str] = None
    source_url: str
    status: Optional[str] = "verified"


def save_contact(data: dict) -> dict:
    """Validate and upsert one real named-person contact."""
    try:
        record = ContactRecord(**data)
    except ValidationError as exc:
        return {"success": False, "error": f"Validation failed: {exc}"}

    email = record.email.strip().lower()
    local_part = email.split("@", 1)[0] if "@" in email else ""

    if local_part in GENERIC_EMAIL_PREFIXES:
        return {
            "success": False,
            "error": f"Generic email rejected ('{record.email}')",
        }

    for field in (
        "iata_code", "icao_code", "phone", "linkedin_url", "contact_form_url"
    ):
        value = getattr(record, field)
        if isinstance(value, str) and value.strip() == "":
            setattr(record, field, None)

    record.email = email

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO airport_contacts
                    (airport_name, iata_code, icao_code, location, full_name, job_title,
                     email, email_confidence, phone, linkedin_url, contact_form_url,
                     source_url, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (airport_name) DO UPDATE SET
                    iata_code = COALESCE(EXCLUDED.iata_code, airport_contacts.iata_code),
                    icao_code = COALESCE(EXCLUDED.icao_code, airport_contacts.icao_code),
                    location = EXCLUDED.location,
                    full_name = EXCLUDED.full_name,
                    job_title = EXCLUDED.job_title,
                    email = EXCLUDED.email,
                    email_confidence = EXCLUDED.email_confidence,
                    phone = COALESCE(EXCLUDED.phone, airport_contacts.phone),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, airport_contacts.linkedin_url),
                    contact_form_url = COALESCE(EXCLUDED.contact_form_url, airport_contacts.contact_form_url),
                    source_url = EXCLUDED.source_url,
                    status = EXCLUDED.status
                RETURNING id, (xmax = 0) AS inserted;
                """,
                (
                    record.airport_name,
                    record.iata_code,
                    record.icao_code,
                    record.location,
                    record.full_name,
                    record.job_title,
                    record.email,
                    record.email_confidence,
                    record.phone,
                    record.linkedin_url,
                    record.contact_form_url,
                    record.source_url,
                    record.status,
                ),
            )
            row = cur.fetchone()

        conn.commit()
        return {
            "success": True,
            "id": row["id"],
            "action": "inserted" if row["inserted"] else "updated",
        }

    except Exception as exc:
        conn.rollback()
        return {"success": False, "error": str(exc)}

    finally:
        conn.close()