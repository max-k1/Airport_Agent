"""
export_contacts.py

Standalone script to export saved contacts from the airport_contacts table
to a CSV or JSON file. Doesn't touch the agent or the scraping tools at all --
just reads what's already in Postgres and writes it out.

Usage:
    python export_contacts.py                          # all rows, CSV, auto-named file
    python export_contacts.py --format json             # all rows, JSON
    python export_contacts.py --status unverified        # only rows with that status
    python export_contacts.py --output leads.csv         # write to a specific path
"""

import argparse
import csv
import json
import sys
from datetime import datetime

from db import get_connection

# Column order for the export -- matches ContactRecord in db.py, plus id/status.
COLUMNS = [
    "id",
    "airport_name",
    "iata_code",
    "icao_code",
    "location",
    "full_name",
    "job_title",
    "email",
    "email_confidence",
    "phone",
    "linkedin_url",
    "contact_form_url",
    "source_url",
    "status",
]


def fetch_contacts(status: str | None = None) -> list[dict]:
    """
    Pull rows from airport_contacts, optionally filtered by status
    (e.g. 'unverified', 'Outdated', 'Updated' -- whatever values you're using).
    Returns a list of plain dicts, one per row, in COLUMNS order.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = f"SELECT {', '.join(COLUMNS)} FROM airport_contacts"
            params = ()
            if status:
                query += " WHERE status = %s"
                params = (status,)
            query += " ORDER BY airport_name;"

            cur.execute(query, params)
            rows = cur.fetchall()

        return [dict(zip(COLUMNS, row)) for row in rows]
    finally:
        conn.close()


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="Export airport_contacts to CSV or JSON.")
    parser.add_argument(
        "--format", choices=["csv", "json"], default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--status", default=None,
        help="Only export rows with this status (e.g. 'unverified'). Omit to export everything.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output file path. If omitted, an auto-named file is created in the current directory.",
    )
    args = parser.parse_args()

    try:
        rows = fetch_contacts(status=args.status)
    except Exception as e:
        print(f"[ERROR] Could not read from the database: {e}")
        sys.exit(1)

    if not rows:
        print("No matching contacts found -- nothing to export.")
        sys.exit(0)

    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"airport_contacts_{timestamp}.{args.format}"

    if args.format == "csv":
        write_csv(rows, output_path)
    else:
        write_json(rows, output_path)

    print(f"Exported {len(rows)} contact(s) to {output_path}")


if __name__ == "__main__":
    main()