"""
adapters/iimjobs.py — IIMJobs public job feed adapter.

Parses the public job feed at https://www.iimjobs.com/jobfeed
with fresher/entry-level experience filter (minexp=0&maxexp=1).
No authentication required — this is the publicly visible job feed.
"""

import re
import time
from typing import Optional

import requests

BASE_URL = "https://www.iimjobs.com/jobfeed"
TIMEOUT  = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.iimjobs.com/",
}

INDIA_TERMS = {"india", "bengaluru", "bangalore", "mumbai", "pune",
               "hyderabad", "delhi", "ncr", "chennai", "noida", "gurgaon"}

TARGET_ROLES = re.compile(
    r"software|developer|engineer|python|java|full[\s-]?stack|backend|"
    r"frontend|data|machine\s+learning|artificial\s+intelligence|ai|ml|"
    r"devops|cloud|react|angular|node|spring|django",
    re.I,
)


def _parse_html(html: str) -> list[dict]:
    """Parse IIMJobs feed HTML using BeautifulSoup."""
    jobs: list[dict] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "lxml")

    # IIMJobs renders jobs in cards/rows — try multiple container selectors
    containers = (
        soup.find_all("div", class_=re.compile(r"job[-_]card|job[-_]row|listing|jobListing", re.I))
        or soup.find_all("li", class_=re.compile(r"job|listing", re.I))
        or soup.find_all("div", class_=re.compile(r"job", re.I))
    )

    if not containers:
        # Fallback: find all anchor tags that look like job links
        return _parse_links_fallback(soup)

    for card in containers:
        try:
            # Title
            title_el = (
                card.find("h2") or card.find("h3") or card.find("h4")
                or card.find("a", href=re.compile(r"/j/"))
                or card.find(class_=re.compile(r"title|heading|name", re.I))
            )
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or not TARGET_ROLES.search(title):
                continue

            # URL
            link_el = card.find("a", href=re.compile(r"/j/|/job/|/jobs/", re.I))
            if not link_el:
                link_el = card.find("a", href=True)
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.iimjobs.com" + url

            # Job ID from URL or hash from title
            jid_match = re.search(r"/j(?:ob)?s?/[^/]+-(\d+)", url)
            job_id = jid_match.group(1) if jid_match else str(abs(hash(url or title)))[:10]

            # Company
            company_el = card.find(class_=re.compile(r"company|employer|org", re.I))
            if not company_el:
                ems = card.find_all(["span", "div", "p"])
                company_el = next(
                    (e for e in ems if e != title_el and e.get_text(strip=True)), None
                )
            company = company_el.get_text(strip=True) if company_el else "Unknown"
            company = company[:80]

            # Location
            loc_el = card.find(class_=re.compile(r"location|city|place", re.I))
            location = loc_el.get_text(strip=True) if loc_el else "India"
            location = location[:100]

            # Skip non-India postings
            loc_lower = location.lower()
            if not any(t in loc_lower for t in INDIA_TERMS) and "india" not in location.lower():
                if "remote" not in loc_lower:
                    continue

            is_remote = int("remote" in loc_lower)

            # Posted date
            date_el = card.find("time") or card.find(class_=re.compile(r"date|posted|time", re.I))
            posted_at = ""
            if date_el:
                posted_at = date_el.get("datetime") or date_el.get_text(strip=True) or ""

            jobs.append({
                "job_key":       f"iimjobs:{job_id}",
                "source":        "IIMJobs",
                "company":       company,
                "title":         title,
                "location":      location,
                "posted_at":     posted_at,
                "description":   "",
                "url":           url,
                "visa_sponsorship": 0,
                "is_remote":     is_remote,
                "salary_range":  "",
                "tags":          "[]",
            })
        except Exception:
            continue

    return jobs


def _parse_links_fallback(soup) -> list[dict]:
    """Fallback: extract job links from any anchor matching IIMJobs URL patterns."""
    jobs: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"/j[oa]b", re.I)):
        try:
            url = a["href"]
            if not url.startswith("http"):
                url = "https://www.iimjobs.com" + url
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or not TARGET_ROLES.search(title):
                continue
            jid = str(abs(hash(url)))[:10]
            if jid in seen:
                continue
            seen.add(jid)
            jobs.append({
                "job_key": f"iimjobs:{jid}",
                "source": "IIMJobs",
                "company": "See listing",
                "title": title[:150],
                "location": "India",
                "posted_at": "",
                "description": "",
                "url": url,
                "visa_sponsorship": 0,
                "is_remote": 0,
                "salary_range": "",
                "tags": "[]",
            })
        except Exception:
            continue
    return jobs


def fetch(min_exp: int = 0, max_exp: int = 1) -> list[dict]:
    """
    Fetch fresher jobs from IIMJobs public feed.

    Args:
        min_exp: Minimum years of experience (default 0).
        max_exp: Maximum years of experience (default 1).

    Returns:
        List of job dicts compatible with db.upsert_jobs().
    """
    params = {"minexp": min_exp, "maxexp": max_exp}
    try:
        resp = requests.get(BASE_URL, params=params, headers=_HEADERS, timeout=TIMEOUT)
        if resp.status_code == 403:
            raise RuntimeError("IIMJobs returned HTTP 403. Site may be blocking automated access.")
        if resp.status_code == 429:
            raise RuntimeError("IIMJobs rate limited (HTTP 429). Try again later.")
        resp.raise_for_status()
        return _parse_html(resp.text)
    except RuntimeError:
        raise
    except requests.RequestException as e:
        raise RuntimeError(f"IIMJobs request failed: {e}") from e
