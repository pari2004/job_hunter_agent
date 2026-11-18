"""
adapters/remoteok.py — RemoteOK public JSON API adapter.

RemoteOK provides a public JSON feed (no auth required):
  GET https://remoteok.com/api

Terms: The feed is public. We rate-limit aggressively and identify ourselves.
We filter to tech/dev roles relevant to the user's target roles.

Reference: https://remoteok.com/api
"""

import time
import logging

import requests

from scorer import detect_visa_sponsorship, detect_remote, extract_tags, TARGET_ROLES

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"
HEADERS = {
    "User-Agent": "JobHunterPersonal/2.0 (personal-use; not a scraper)",
    "Accept": "application/json",
}
TIMEOUT = 30
RATE_LIMIT_DELAY = 2.0  # seconds between requests

# Tags we want to match from RemoteOK
TARGET_TAGS = {
    "python", "java", "javascript", "typescript", "react", "node",
    "backend", "frontend", "fullstack", "full-stack", "software",
    "engineer", "developer", "django", "spring", "ml", "ai",
    "machine-learning", "data-engineering", "devops",
}


def _is_relevant(job: dict) -> bool:
    """Filter to jobs relevant for the target role list."""
    title = (job.get("position") or "").lower()
    tags = [t.lower() for t in (job.get("tags") or [])]
    # Check title against our target roles
    if any(role in title for role in TARGET_ROLES):
        return True
    # Check RemoteOK tags
    if TARGET_TAGS & set(tags):
        return True
    return False


def fetch(max_jobs: int = 50) -> list[dict]:
    """
    Fetch relevant remote jobs from RemoteOK public feed.

    Args:
        max_jobs: Cap at this many jobs to avoid overloading the DB.

    Returns:
        List of normalised job dicts.
    """
    time.sleep(RATE_LIMIT_DELAY)  # be a good citizen
    try:
        r = requests.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.error("RemoteOK fetch failed: %s", exc)
        raise

    data = r.json()
    # First item is a legal note dict, skip it
    postings = [j for j in data if isinstance(j, dict) and j.get("id")]

    jobs = []
    for j in postings:
        if not _is_relevant(j):
            continue
        title = j.get("position", "")
        company = j.get("company", "")
        description = j.get("description", "") or ""
        url = j.get("url", "") or f"https://remoteok.com/remote-jobs/{j.get('id')}"
        location = "Remote"
        salary = ""
        if j.get("salary_min") and j.get("salary_max"):
            salary = f"${j['salary_min']:,}–${j['salary_max']:,}"
        elif j.get("salary_min"):
            salary = f"${j['salary_min']:,}+"

        jobs.append({
            "job_key": f"remoteok:{j.get('id')}",
            "source": "RemoteOK",
            "company": company,
            "title": title,
            "location": location,
            "posted_at": j.get("date", ""),
            "description": description,
            "url": url,
            "visa_sponsorship": int(detect_visa_sponsorship(description + " " + title)),
            "is_remote": 1,
            "salary_range": salary,
            "tags": str(extract_tags(title, description)),
        })

        if len(jobs) >= max_jobs:
            break

    logger.info("RemoteOK: fetched %d relevant jobs (capped at %d)", len(jobs), max_jobs)
    return jobs
