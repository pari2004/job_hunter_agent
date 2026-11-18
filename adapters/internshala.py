"""
adapters/internshala.py — Internshala public jobs & internships adapter.

Parses Internshala's public search pages — no authentication required.
Fetches both jobs and internships relevant to fresher software roles.
"""

import re
import time
from typing import Optional

import requests

BASE_JOBS = "https://internshala.com/jobs/keywords-{kw}/"
BASE_INTERNS = "https://internshala.com/internships/keywords-{kw}/"

TIMEOUT = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://internshala.com/",
}

DEFAULT_KEYWORDS = [
    "software-developer",
    "full-stack-developer",
    "python-developer",
    "java-developer",
    "backend-developer",
    "frontend-developer",
]

INDIA_TERMS = {"india", "bengaluru", "bangalore", "mumbai", "pune",
               "hyderabad", "delhi", "chennai", "noida", "gurgaon", "work from home"}


def _parse_internshala(html: str, source_type: str = "Job") -> list[dict]:
    """Parse Internshala's job/internship listing HTML."""
    jobs: list[dict] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "lxml")

    # Internshala uses container_type div.internship_meta or div#internship_list
    containers = (
        soup.find_all("div", class_=re.compile(r"internship_meta|individual_internship", re.I))
        or soup.find_all("div", id=re.compile(r"internship_", re.I))
        or soup.find_all("div", class_=re.compile(r"listing", re.I))
    )

    # Also try script tag with JSON data
    if not containers:
        return _parse_json_fallback(html, source_type)

    for card in containers:
        try:
            # Title
            title_el = (
                card.find("h3", class_=re.compile(r"title|heading", re.I))
                or card.find("a", class_=re.compile(r"view_detail", re.I))
                or card.find("h3") or card.find("h4")
            )
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            # URL
            link_el = card.find("a", href=re.compile(r"/internship/|/jobs/", re.I))
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://internshala.com" + url

            # Job ID
            jid_match = re.search(r"-(\d+)/?$", url)
            job_id = jid_match.group(1) if jid_match else str(abs(hash(url or title)))[:10]

            # Company
            company_el = (
                card.find(class_=re.compile(r"company_name|company-name", re.I))
                or card.find("a", class_=re.compile(r"company", re.I))
            )
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location
            loc_el = card.find(class_=re.compile(r"location_link|location", re.I))
            location = loc_el.get_text(strip=True) if loc_el else "India"
            location = location.strip()

            is_remote = int("work from home" in location.lower() or "remote" in location.lower())
            if is_remote:
                location = "Remote (India)"

            # Skip non-India
            loc_lower = location.lower()
            if not is_remote and not any(t in loc_lower for t in INDIA_TERMS):
                continue

            # Stipend/salary
            pay_el = card.find(class_=re.compile(r"stipend|salary|pay", re.I))
            salary = pay_el.get_text(strip=True) if pay_el else ""

            # Duration/date
            date_el = card.find(class_=re.compile(r"date|duration|start", re.I))
            posted_at = date_el.get_text(strip=True) if date_el else ""

            # Skills
            skills_el = card.find_all(class_=re.compile(r"skill|tag|badge", re.I))
            tags = str([s.get_text(strip=True) for s in skills_el[:8]]) if skills_el else "[]"

            src = f"Internshala ({source_type})"

            jobs.append({
                "job_key":       f"internshala:{source_type.lower()}:{job_id}",
                "source":        src,
                "company":       company[:80],
                "title":         title[:150],
                "location":      location[:100],
                "posted_at":     posted_at,
                "description":   "",
                "url":           url,
                "visa_sponsorship": 0,
                "is_remote":     is_remote,
                "salary_range":  salary[:50],
                "tags":          tags,
            })
        except Exception:
            continue

    return jobs


def _parse_json_fallback(html: str, source_type: str) -> list[dict]:
    """Extract job data from embedded JSON (Internshala sometimes inlines data)."""
    jobs: list[dict] = []
    # Look for JSON-like data in script tags
    matches = re.findall(
        r'"title"\s*:\s*"([^"]+)".*?"company_name"\s*:\s*"([^"]+)".*?"city_name"\s*:\s*"([^"]+)"',
        html, re.DOTALL
    )
    for title, company, city in matches[:20]:
        jid = str(abs(hash(title + company)))[:10]
        jobs.append({
            "job_key": f"internshala:{source_type.lower()}:{jid}",
            "source": f"Internshala ({source_type})",
            "company": company,
            "title": title,
            "location": city or "India",
            "posted_at": "",
            "description": "",
            "url": "https://internshala.com/",
            "visa_sponsorship": 0,
            "is_remote": 0,
            "salary_range": "",
            "tags": "[]",
        })
    return jobs


def fetch(keywords: Optional[list[str]] = None) -> list[dict]:
    """
    Fetch fresher jobs and internships from Internshala's public pages.

    Args:
        keywords: URL-safe keyword slugs (e.g. "software-developer").

    Returns:
        List of job dicts compatible with db.upsert_jobs().
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    all_jobs: list[dict] = []
    seen: set[str] = set()

    for kw in keywords:
        for url_tmpl, src_type in [(BASE_JOBS, "Job"), (BASE_INTERNS, "Internship")]:
            url = url_tmpl.format(kw=kw)
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=TIMEOUT)
                if resp.status_code == 429:
                    raise RuntimeError("Internshala rate limited (HTTP 429). Try again later.")
                resp.raise_for_status()
                for j in _parse_internshala(resp.text, src_type):
                    if j["job_key"] not in seen:
                        seen.add(j["job_key"])
                        all_jobs.append(j)
            except RuntimeError:
                raise
            except requests.RequestException as e:
                raise RuntimeError(f"Internshala request failed ({kw}, {src_type}): {e}") from e
            except Exception:
                pass
            time.sleep(1.5)

    return all_jobs
