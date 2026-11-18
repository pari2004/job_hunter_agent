"""
adapters/greenhouse.py — Greenhouse public job board adapter.

Uses the official public Greenhouse Boards API (no auth required):
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Reference: https://developers.greenhouse.io/job-board.html
"""

import re
import time
import logging
from typing import Optional

import requests

from scorer import detect_visa_sponsorship, detect_remote, extract_tags

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
HEADERS = {"User-Agent": "JobHunterPersonal/2.0 (personal-use; contact: user@example.com)"}
TIMEOUT = 25
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # seconds


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _get_with_retry(url: str, params: Optional[dict] = None) -> requests.Response:
    """GET with exponential backoff. Respects rate limits (429)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = BACKOFF_BASE ** attempt
                logger.warning("Rate-limited by Greenhouse; waiting %.1fs", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning("Greenhouse request failed (%s); retry %d in %.1fs", exc, attempt, wait)
            time.sleep(wait)
    raise RuntimeError("Greenhouse: max retries exceeded")


def fetch(token: str) -> list[dict]:
    """
    Fetch all jobs from a Greenhouse company board.

    Args:
        token: Company board token (e.g. 'airbnb' from careers.airbnb.com/greenhouse).

    Returns:
        List of normalised job dicts.
    """
    url = BASE_URL.format(token=token)
    try:
        r = _get_with_retry(url, params={"content": "true"})
    except Exception as exc:
        logger.error("Greenhouse[%s] failed: %s", token, exc)
        raise

    data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        description = _strip_html(j.get("content", ""))
        location_data = j.get("location") or {}
        location = location_data.get("name", "") if isinstance(location_data, dict) else str(location_data)
        title = j.get("title", "")
        url_apply = j.get("absolute_url", "")
        # updated_at is not the publication date; leave it blank when the API
        # does not provide first_published rather than presenting a misleading date.
        posted_at = j.get("first_published", "") or ""

        jobs.append({
            "job_key": f"gh:{token}:{j.get('id')}",
            "source": "Greenhouse",
            "company": token,
            "title": title,
            "location": location,
            "posted_at": posted_at,
            "description": description,
            "url": url_apply,
            "visa_sponsorship": int(detect_visa_sponsorship(description + " " + title)),
            "is_remote": int(detect_remote(location + " " + description)),
            "salary_range": "",
            "tags": str(extract_tags(title, description)),
        })

    logger.info("Greenhouse[%s]: fetched %d jobs", token, len(jobs))
    return jobs
