import io
import os
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

GENERIC_EMAIL_PREFIXES = {
    "info", "contact", "admin", "support", "enquiries", "sales", "hello"
}


def search_web(query: str, max_results: int = 10) -> list[dict]:
    """Search the web with Tavily, prioritising recall over speed/cost."""
    if not TAVILY_API_KEY:
        return [{
            "error": (
                "Tavily API key is not set. "
                "Set TAVILY_API_KEY in your .env file."
            )
        }]

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
            },
            timeout=30,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        return [
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "content": result.get("content"),
            }
            for result in results
        ]

    except requests.RequestException as exc:
        return [{"error": str(exc)}]


def search_person_email(
    full_name: str,
    airport_name: str,
    operator_name: str = "",
    official_domain: str = "",
    max_results_per_query: int = 10,
) -> dict:
    """
    Run several email-specific searches for one named candidate.

    This deliberately performs multiple query variations before the agent is
    expected to abandon a candidate and move down the chain of command.
    """
    full_name = " ".join(full_name.split())
    airport_name = " ".join(airport_name.split())
    operator_name = " ".join(operator_name.split())
    official_domain = _clean_domain(official_domain)

    queries = [
        f'"{full_name}" "{airport_name}" email',
        f'"{full_name}" email',
        f'"{full_name}" "{airport_name}" contact',
        f'"{full_name}" sustainability email',
    ]

    if operator_name:
        queries.append(f'"{full_name}" "{operator_name}" email')

    if official_domain:
        queries.extend([
            f'site:{official_domain} "{full_name}"',
            f'site:{official_domain} "{full_name}" email',
        ])

    all_results = []
    seen_urls = set()
    detected_emails = set()

    for query in queries:
        results = search_web(query, max_results=max_results_per_query)

        for result in results:
            if "error" in result:
                all_results.append({"query": query, **result})
                continue

            url = result.get("url") or ""
            content = result.get("content") or ""
            title = result.get("title") or ""

            for email in EMAIL_PATTERN.findall(f"{title}\n{content}"):
                if not _is_generic_email(email):
                    detected_emails.add(email.lower())

            # Deduplicate normal results by URL while retaining which query
            # surfaced the result first.
            key = url.strip().lower()
            if key and key in seen_urls:
                continue
            if key:
                seen_urls.add(key)

            all_results.append({
                "query": query,
                "title": title,
                "url": url,
                "content": content,
            })

    return {
        "candidate": full_name,
        "airport": airport_name,
        "queries_used": queries,
        "detected_non_generic_emails_in_snippets": sorted(detected_emails),
        "results": all_results,
    }


def _extract_pdf_text(content: bytes) -> str:
    """Extract PDF text when pypdf is installed."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "[PDF detected but pypdf is not installed. "
            "Run: pip install pypdf]"
        )

    try:
        reader = PdfReader(io.BytesIO(content))
        text_parts = []

        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)

        return "\n".join(text_parts)

    except Exception as exc:
        return f"[Could not extract PDF text: {exc}]"


def _request_url(url: str) -> requests.Response:
    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        },
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _response_to_text(response: requests.Response, original_url: str) -> tuple[str, list[str]]:
    """Return searchable page text and every email found in the response."""
    content_type = response.headers.get("Content-Type", "").lower()

    if "application/pdf" in content_type or original_url.lower().endswith(".pdf"):
        text = _extract_pdf_text(response.content)
        emails = sorted(set(email.lower() for email in EMAIL_PATTERN.findall(text)))
        return text, emails

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract mailto addresses BEFORE touching the DOM.
    mailto_emails = []
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if href.lower().startswith("mailto:"):
            mailto_part = href.split(":", 1)[1].split("?", 1)[0]
            mailto_emails.extend(EMAIL_PATTERN.findall(mailto_part))

    # Scan raw HTML too: addresses may be in attributes or embedded data.
    raw_html_emails = EMAIL_PATTERN.findall(response.text)

    # Keep headers, footers, nav, forms and contact sections. Only remove
    # elements that are overwhelmingly noise.
    for tag in soup(["script", "style", "svg", "noscript", "template"]):
        tag.decompose()

    visible_text = soup.get_text("\n", strip=True)
    visible_emails = EMAIL_PATTERN.findall(visible_text)

    all_emails = sorted(set(
        email.lower()
        for email in (mailto_emails + raw_html_emails + visible_emails)
    ))

    return visible_text, all_emails


def fetch_page(url: str, max_chars: int = 60000) -> str:
    """
    Fetch a webpage/PDF and return email-first readable content.

    Unlike the old tool, this keeps header/footer/form/nav content and extracts
    mailto/raw-HTML email addresses before any cleanup.
    """
    try:
        response = _request_url(url)
    except requests.RequestException as exc:
        return f"Error fetching page: {exc}"

    text, emails = _response_to_text(response, url)

    non_generic = [email for email in emails if not _is_generic_email(email)]
    generic = [email for email in emails if _is_generic_email(email)]

    sections = [
        "=== NON-GENERIC EMAIL ADDRESSES FOUND ===\n"
        + ("\n".join(non_generic) if non_generic else "None"),
        "=== GENERIC EMAIL ADDRESSES FOUND ===\n"
        + ("\n".join(generic) if generic else "None"),
        "=== READABLE PAGE TEXT ===\n" + text,
    ]

    return "\n\n".join(sections)[:max_chars]




def _clean_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""

    if "://" in value:
        value = urlparse(value).netloc

    value = value.split("/", 1)[0]
    value = value.split(":", 1)[0]

    if value.startswith("www."):
        value = value[4:]

    return value


def _is_generic_email(email: str) -> bool:
    if "@" not in email:
        return True
    local_part = email.split("@", 1)[0].lower()
    return local_part in GENERIC_EMAIL_PREFIXES


def _normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _name_appears(full_name: str, normalized_text: str) -> bool:
    normalized_name = _normalize_text(full_name)
    if not normalized_name:
        return False

    if normalized_name in normalized_text:
        return True

    parts = normalized_name.split()
    if len(parts) < 2:
        return normalized_name in normalized_text

    first = parts[0]
    last = parts[-1]

    reverse_name = f"{last} {first}"
    if reverse_name in normalized_text:
        return True

    # Handles pages that split the first/last name across separate elements.
    return first in normalized_text and last in normalized_text

def validate_contact_source(
    url: str,
    full_name: str,
    email: str,
    official_domain: str = "",
) -> dict:
    """
    Verify that a real source contains BOTH the named person and exact email.

    This is intentionally stricter than simply seeing the email in a search
    snippet. A contact cannot be saved by the agent until this function has
    verified the source association.
    """
    email = email.strip().lower()
    full_name = " ".join(full_name.split()).strip()

    if not EMAIL_PATTERN.fullmatch(email):
        return {
            "verified": False,
            "reason": "Invalid email syntax",
            "url": url,
        }

    if _is_generic_email(email):
        return {
            "verified": False,
            "reason": "Generic inboxes do not qualify as named-person emails",
            "url": url,
        }

    try:
        response = _request_url(url)
    except requests.RequestException as exc:
        return {
            "verified": False,
            "reason": f"Could not fetch source: {exc}",
            "url": url,
        }

    text, emails = _response_to_text(response, url)
    normalized_text = _normalize_text(text)

    email_found = email in {item.lower() for item in emails}
    name_found = _name_appears(full_name, normalized_text)

    source_domain = _clean_domain(urlparse(response.url).netloc)
    official_domain = _clean_domain(official_domain)
    official_source = bool(
        official_domain
        and (
            source_domain == official_domain
            or source_domain.endswith("." + official_domain)
        )
    )

    verified = email_found and name_found

    return {
        "verified": verified,
        "email_found": email_found,
        "name_found": name_found,
        "requested_url": url,
        "final_url": response.url,
        "source_domain": source_domain,
        "official_source": official_source,
        "recommended_confidence": (
            "high" if verified and official_source
            else "medium" if verified
            else None
        ),
        "reason": (
            "Source contains both the named person and exact email"
            if verified
            else "Source did not contain both the named person and exact email"
        ),
    }



if __name__ == "__main__":
    test_url = (
        "https://www.heathrow.com/company/about-heathrow/"
        "heathrow-sustainability-strategy"
    )
    print(fetch_page(test_url))
