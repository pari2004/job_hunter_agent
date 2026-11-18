"""
adapters/linkedin.py — LinkedIn public guest jobs API adapter.

Uses the same public endpoint LinkedIn serves to unauthenticated visitors
at https://www.linkedin.com/jobs/search/ — no login, no CAPTCHA bypass,
no private data access, no account required.

Fetches job listings (title, company, location, date, URL) only.
Job descriptions require a separate API call and are left blank here;
users click the URL to read the full description on LinkedIn.

Rate: 2.5-second delay between keyword requests, max 25 per keyword.
"""

import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
TIMEOUT = 15
INTER_REQUEST_DELAY = 2.5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.linkedin.com/jobs/search/",
}

# Experience level codes: 1=Entry, 2=Associate, 3=Mid-Senior, 6=Internship
ENTRY_LEVEL   = "1"
INTERNSHIP    = "6"

DEFAULT_KEYWORDS = [
    "software engineer fresher",
    "java developer entry level",
    "python developer fresher",
    "full stack developer fresher",
    "backend developer fresher",
    "frontend developer fresher",
    "AI ML engineer fresher",
]

INDIA_TERMS = {"india", "bengaluru", "bangalore", "mysuru", "mysore",
               "mumbai", "pune", "hyderabad", "delhi", "chennai", "remote"}


def _parse_html(html: str) -> list[dict]:
    """Parse LinkedIn job cards from the guest API HTML response."""
    jobs: list[dict] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _parse_html_regex(html)

    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_=lambda c: c and "base-card" in c)

    for card in cards:
        try:
            # URL + job ID
            link_el = card.find("a", href=re.compile(r"linkedin\.com/jobs/view/\d+"))
            if not link_el:
                continue
            url = link_el.get("href", "").split("?")[0]
            jid_match = re.search(r"/jobs/view/(\d+)", url)
            if not jid_match:
                continue
            job_id = jid_match.group(1)

            title_el = card.find("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            company_el = card.find("h4")
            company_text = company_el.get_text(strip=True) if company_el else "Unknown"
            # Remove nested <a> tag artifacts
            company = re.sub(r"\s+", " ", company_text).strip()

            loc_el = card.find(class_=re.compile(r"location|city", re.I))
            location = loc_el.get_text(strip=True) if loc_el else "India"

            time_el = card.find("time")
            posted_at = time_el.get("datetime", "") if time_el else ""

            is_remote = int(bool(
                card.find(string=re.compile(r"\bremote\b", re.I))
            ))

            # Skip non-India non-remote jobs
            loc_lower = location.lower()
            if not is_remote and not any(t in loc_lower for t in INDIA_TERMS):
                continue

            jobs.append({
                "job_key": f"linkedin:{job_id}",
                "source":  "LinkedIn",
                "company": company,
                "title":   title,
                "location": location,
                "posted_at": posted_at,
                "description": "",
                "url": url if url.startswith("http") else "https://www.linkedin.com" + url,
                "visa_sponsorship": 0,
                "is_remote": is_remote,
                "salary_range": "",
                "tags": "[]",
            })
        except Exception:
            continue

    return jobs


def _parse_html_regex(html: str) -> list[dict]:
    """Regex fallback if BeautifulSoup is unavailable."""
    jobs: list[dict] = []
    for m in re.finditer(
        r'href="(https://[a-z.]*linkedin\.com/jobs/view/(\d+)[^"]*)"'
        r'.*?<h3[^>]*>\s*([^<]+?)\s*</h3>'
        r'.*?<h4[^>]*>(.*?)</h4>',
        html, re.DOTALL,
    ):
        url = m.group(1).split("?")[0]
        job_id = m.group(2)
        title = m.group(3).strip()
        company = re.sub(r"<[^>]+>", "", m.group(4)).strip()
        jobs.append({
            "job_key": f"linkedin:{job_id}",
            "source": "LinkedIn",
            "company": company,
            "title": title,
            "location": "India",
            "posted_at": "",
            "description": "",
            "url": url,
            "visa_sponsorship": 0,
            "is_remote": 0,
            "salary_range": "",
            "tags": "[]",
        })
    return jobs


def fetch(
    keywords: Optional[list[str]] = None,
    location: str = "India",
    experience_level: str = ENTRY_LEVEL,
    max_per_keyword: int = 25,
) -> list[dict]:
    """
    Fetch entry-level jobs from LinkedIn's public guest jobs API.

    Args:
        keywords:         List of search phrases. Defaults to DEFAULT_KEYWORDS.
        location:         LinkedIn location string. Default: "India".
        experience_level: LinkedIn f_E value. Default: "1" (Entry level).
        max_per_keyword:  Max results per keyword (25 = 1 page).

    Returns:
        List of job dicts compatible with db.upsert_jobs().
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    all_jobs: list[dict] = []
    seen: set[str] = set()

    for kw in keywords:
        params = {
            "keywords": kw,
            "location": location,
            "f_E": experience_level,
            "start": 0,
        }
        try:
            resp = requests.get(
                GUEST_API, params=params, headers=_HEADERS,
                timeout=TIMEOUT,
            )
            if resp.status_code == 429:
                raise RuntimeError("LinkedIn rate-limited this IP (HTTP 429). Wait before retrying.")
            resp.raise_for_status()

            for j in _parse_html(resp.text):
                if j["job_key"] not in seen:
                    seen.add(j["job_key"])
                    all_jobs.append(j)
        except RuntimeError:
            raise
        except requests.RequestException as e:
            raise RuntimeError(f"LinkedIn request failed for '{kw}': {e}") from e
        except Exception:
            pass  # Skip malformed cards silently

        time.sleep(INTER_REQUEST_DELAY)

    return all_jobs
