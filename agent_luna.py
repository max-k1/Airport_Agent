"""
Real-email-only airport sustainability contact research agent.

Workflow for each airport:
1. Identify several relevant people, ranked by seniority/relevance.
2. Research the best candidate with multiple email-specific search variations.
3. Fetch promising webpages/PDFs.
4. Validate that a source contains BOTH the person's name and exact email.
5. Save immediately when a validated non-generic email is found.
6. Otherwise move down the chain of command and repeat.

Run with:
    python agent_luna.py
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from db import save_contact
from tools import (
    fetch_page,
    search_person_email,
    search_web,
    validate_contact_source,
)

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-5.6-luna"

TOOLS = [
    {
        "type": "function",
        "name": "search_web",
        "description": (
            "General web search. Use this to identify relevant airport personnel, "
            "the airport operator, official domain, leadership pages, reports, and "
            "other useful sources. Returns up to 10 advanced Tavily results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "search_person_email",
        "description": (
            "Deeply search for ONE named candidate's real email. One call runs "
            "multiple exact-name/email/contact/site query variations automatically. "
            "Call this before giving up on a candidate and moving down the chain."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "airport_name": {"type": "string"},
                "operator_name": {
                    "type": "string",
                    "description": "Airport operator/company if known; otherwise omit or empty string",
                },
                "official_domain": {
                    "type": "string",
                    "description": "Official airport/operator domain if known, e.g. flylax.com",
                },
            },
            "required": ["full_name", "airport_name"],
        },
    },
    {
        "type": "function",
        "name": "fetch_page",
        "description": (
            "Fetch a webpage or PDF and return email-first readable content. "
            "It extracts mailto/raw HTML addresses, keeps headers/footers/contact "
            "sections, and supports PDF text extraction when pypdf is installed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "type": "function",
        "name": "validate_contact_source",
        "description": (
            "MANDATORY before save_contact. Fetch the proposed source URL and verify "
            "that it contains BOTH the named person's identity and the exact email. "
            "Also reports whether the source is on the official domain."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "full_name": {"type": "string"},
                "email": {"type": "string"},
                "official_domain": {"type": "string"},
            },
            "required": ["url", "full_name", "email"],
        },
    },
    {
        "type": "function",
        "name": "save_contact",
        "description": (
            "Save the ONE final contact. This call is rejected by the Python "
            "orchestrator unless validate_contact_source previously verified the "
            "same full_name + email + source_url during this airport run. "
            "No guessed/speculated emails are allowed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "airport_name": {"type": "string"},
                "iata_code": {"type": "string"},
                "icao_code": {"type": "string"},
                "location": {"type": "string"},
                "full_name": {"type": "string"},
                "job_title": {"type": "string"},
                "email": {"type": "string"},
                "email_confidence": {
                    "type": "string",
                    "enum": ["high", "medium"],
                    "description": (
                        "high = directly associated on official airport/operator source; "
                        "medium = directly associated on another credible public source"
                    ),
                },
                "phone": {"type": "string"},
                "linkedin_url": {"type": "string"},
                "contact_form_url": {"type": "string"},
                "source_url": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["verified"],
                },
            },
            "required": [
                "airport_name",
                "location",
                "full_name",
                "job_title",
                "email",
                "email_confidence",
                "source_url",
            ],
        },
    },
]


SYSTEM_PROMPT = """You are a research agent whose main objective is to find ONE REAL,
PUBLICLY SUPPORTED email address for a named person responsible for sustainability,
ESG, carbon, environment, climate, noise, or related compliance at a commercial airport.

Real-email-only rules:
- NEVER invent, infer, construct, speculate, or guess an email address.
- Generic inboxes such as info@, contact@, admin@, support@, enquiries@, sales@,
  or hello@ do not count.
- A search snippet is a lead, not sufficient proof by itself.
- Before save_contact, you MUST call validate_contact_source on the exact source URL.
- save_contact will be rejected in code unless the same name + email + URL was validated.

Target roles, in rough priority order:
- Chief Sustainability Officer / VP Sustainability / Head of Sustainability
- Sustainability Director / Environmental Director
- Sustainability Manager / Environmental Manager
- Carbon / Net Zero / Climate Lead or Manager
- ESG / Environmental Compliance / Noise & Environment roles

Research procedure for EACH airport:

1. Use search_web to identify several relevant NAMED candidates and, where possible,
   the airport operator/company and official website domain.

2. Rank candidates by relevance and seniority. Start with the strongest candidate.

3. For EACH candidate, call search_person_email. This is mandatory before abandoning
   that candidate. It automatically performs several query variations, including exact
   name + airport + email, exact name + email, contact searches, sustainability searches,
   and official-domain searches when the domain is known.

4. Inspect the returned results. Fetch every promising source that could contain the
   person's direct email, including official staff/contact pages, press releases,
   environmental pages, conference documents, and PDFs.

5. If a possible direct email is found, call validate_contact_source with the exact
   page/PDF URL, person's full name, email, and official domain if known.

6. If validation fails, do NOT save it. Continue searching that candidate's promising
   sources. If the candidate has been reasonably exhausted, move to the next candidate
   DOWN the chain of command.

7. Never circle back to a candidate whose search_person_email phase has already been
   completed unless there is genuinely new source evidence that was not previously
   inspected.

8. Continue down the chain until either:
   A) a source validates both the named person and exact email, or
   B) all reasonable relevant candidates have been exhausted.

9. When validation succeeds:
   - high confidence if the validating source is the official airport/operator domain.
   - medium confidence if another credible public source explicitly associates the
     person's name with that exact email.
   Then call save_contact IMMEDIATELY. Once save_contact succeeds, stop researching that
   airport and provide a very short summary.

10. Prefer a slightly less senior relevant person with a validated real email over a
    more senior person whose email cannot be found.

11. Do not stop merely because the first 2 or 3 candidates fail. The goal is to continue
    down the relevant chain of command until a real validated named-person email is found
    or the reasonable candidate pool is exhausted.
"""


def _validation_key(full_name: str, email: str, source_url: str) -> tuple[str, str, str]:
    return (
        " ".join(full_name.lower().split()),
        email.strip().lower(),
        source_url.strip(),
    )


def run_agent(user_request: str, max_turns: int = 40):
    # State is per-airport run.
    attempted_candidates = set()
    validated_contacts = set()

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=user_request,
            tools=TOOLS,
            tool_choice="auto",
            reasoning={"effort": "medium"},
            store=True,
        )
    except Exception as exc:
        print(f"[ERROR] Initial API call failed: {exc}")
        return False

    for turn in range(max_turns):
        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not function_calls:
            print(f"\n[Luna]: {response.output_text}")
            return False

        results_input = []

        for tool_call in function_calls:
            try:
                args = json.loads(tool_call.arguments)
                print(f"\n[Tool call]: {tool_call.name}({args})")

                if tool_call.name == "search_web":
                    result = search_web(**args)

                elif tool_call.name == "search_person_email":
                    candidate_key = (
                        args.get("airport_name", "").strip().lower(),
                        " ".join(args.get("full_name", "").lower().split()),
                    )

                    if candidate_key in attempted_candidates:
                        result = {
                            "error": (
                                "This candidate has already completed the deep email-search "
                                "phase. Move to the next relevant candidate unless you have "
                                "genuinely new evidence to inspect with fetch_page."
                            ),
                            "candidate_already_attempted": True,
                        }
                    else:
                        attempted_candidates.add(candidate_key)
                        result = search_person_email(**args)
                        result["attempted_candidates_so_far"] = [
                            name for _, name in sorted(attempted_candidates)
                        ]

                elif tool_call.name == "fetch_page":
                    result = fetch_page(**args)

                elif tool_call.name == "validate_contact_source":
                    result = validate_contact_source(**args)
                    if result.get("verified"):
                        key = _validation_key(
                            args["full_name"],
                            args["email"],
                            result.get("final_url") or args["url"],
                        )
                        validated_contacts.add(key)

                        # Also accept the originally requested URL in case a redirect
                        # occurred but Luna uses the initial URL in save_contact.
                        validated_contacts.add(_validation_key(
                            args["full_name"],
                            args["email"],
                            args["url"],
                        ))

                elif tool_call.name == "save_contact":
                    key = _validation_key(
                        args.get("full_name", ""),
                        args.get("email", ""),
                        args.get("source_url", ""),
                    )

                    if key not in validated_contacts:
                        result = {
                            "success": False,
                            "error": (
                                "SAVE BLOCKED: this exact full_name + email + source_url "
                                "has not passed validate_contact_source in this run."
                            ),
                        }
                    else:
                        # Force real-email-only status.
                        args["status"] = "verified"
                        result = save_contact(args)

                        if result.get("success"):
                            print("\n[SUCCESS] Validated real email saved. Stopping this airport.")
                            return True

                else:
                    result = {"error": f"Unknown tool {tool_call.name}"}

            except json.JSONDecodeError as exc:
                result = {"error": f"Invalid JSON arguments: {exc}"}

            except TypeError as exc:
                result = {
                    "error": (
                        f"Invalid arguments for {tool_call.name}: {exc}. "
                        "Check the parameter names and try again."
                    )
                }

            except Exception as exc:
                result = {
                    "error": f"{tool_call.name} failed: {type(exc).__name__}: {exc}"
                }

            print(f"[Tool result]: {result}")

            results_input.append({
                "type": "function_call_output",
                "call_id": tool_call.call_id,
                "output": json.dumps(result),
            })

        try:
            response = client.responses.create(
                model=MODEL,
                previous_response_id=response.id,
                instructions=SYSTEM_PROMPT,
                tools=TOOLS,
                tool_choice="auto",
                reasoning={"effort": "medium"},
                input=results_input,
                store=True,
            )
        except Exception as exc:
            print(f"[ERROR] API call failed on turn {turn + 1}: {exc}")
            return False

    print(f"\n[Stopped: reached max_turns={max_turns} without finishing]")
    return False


AIRPORT_BATCH = [
    "Liverpool John Lennon Airport",
    "Newcastle International Airport",
    "Leeds Bradford Airport",
    "East Midlands Airport",
    "London City Airport"
]


if __name__ == "__main__":
    FAILED_AIRPORTS = []

    for airport in AIRPORT_BATCH:
        print(f"\n{'=' * 60}\nResearching: {airport}\n{'=' * 60}")

        try:
            saved = run_agent(
                f"Find a named individual responsible for sustainability, carbon "
                f"management, ESG, or environmental compliance at {airport}. "
                f"Find and save ONE real, publicly supported individual email address."
            )

            if not saved:
                FAILED_AIRPORTS.append(airport)

        except Exception as exc:
            print(f"[Error during agent run for {airport}]: {exc}")
            FAILED_AIRPORTS.append(airport)

    if FAILED_AIRPORTS:
        print(f"\n{'=' * 60}\nNo validated email saved for:\n{'=' * 60}")
        for airport in FAILED_AIRPORTS:
            print(f" - {airport}")
