# AI Sustainability Officer Finder

An agent that finds the single named individual responsible for sustainability,
ESG, or environmental compliance at a given airport, and saves their real,
verified email address to a Postgres database.

No email is ever saved on trust. Before a contact can be saved, the code —
not just the AI's instructions — requires that a separate validation step has
already confirmed the person's name and email both appear together on a real,
fetched web page.

## What it does

1. Searches the web for the airport's sustainability leadership.
2. Runs a deep, multi-query email search for the top candidate.
3. Fetches the most promising pages (including PDFs) to find a real email.
4. **Independently re-verifies** that the name and email both appear on the
   source page before allowing a save.
5. Saves the single best validated contact to Postgres. If a candidate can't
   be verified, it moves to the next person down the chain of command.

## Project files

 `agent_luna.py`  - Orchestrates the whole process — the tools, the system prompt, and the per-airport loop. Edit `AIRPORT_BATCH` at the bottom to change which airports get researched. 
 `tools.py`- The web-facing tools: search, per-person email search, page/PDF fetching, and source validation. 
 `db.py` - Database layer — validates a contact record and upserts it into Postgres. 
 `export_contacts.py` - Standalone, read-only script to dump the database to CSV/JSON. 
 `schema.sql` - Run this once against a fresh Postgres database to create the required table. 
 `requirements.txt` - Python dependencies. 
 `.env.example` - Template for the required environment variables — copy to `.env` and fill in real values. 

## Setup

pip install -r requirements.txt
cp .env.example .env   # then fill in real values — never commit .env

Create the database table:

psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f schema.sql

## Running it

python agent_luna.py

Watch the console output — it prints every `[Tool call]` and `[Tool result]`
live, so you can see exactly which candidate the agent is trying, which pages
it's fetching, and whether validation passed or failed for each one.

Export whatever's been saved so far at any time:


python export_contacts.py                    # all rows, CSV, auto-named file
python export_contacts.py --format json       # all rows, JSON
python export_contacts.py --output leads.csv  # write to a specific path

`export_contacts.py` is read-only and never touches the agent — safe to run
mid-batch.

## Required environment variables

See `.env.example` for the full list. In short: `OPENAI_API_KEY`,
`TAVILY_API_KEY`, and `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` /
`DB_PASSWORD`. Never commit a filled-in `.env` — it's already excluded by
`.gitignore`.

## Known limitations

- `AIRPORT_BATCH` is a hardcoded list — no config file or CLI yet for
  choosing which airports to target.
- No CRM integration — output currently stops at CSV/JSON.
- No human review step before a contact is considered final.
- No SMTP/deliverability check — validation confirms the email is
  genuinely associated with the person on a real page, not that the mailbox
  is currently live.
- No rate limiting on outbound requests — fine at the current batch size,
  will need addressing before scaling to a much larger airport list.