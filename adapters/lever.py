"""
adapters/lever.py — Lever public job posting adapter.

Uses the official public Lever Postings API (no auth required):
  GET https://api.lever.co/v0/postings/{site}?mode=json

Reference: https://hire.lever.co/developer/postings
"""

import re
import time
import logging
from typing import Optional

import requests

from scorer import detect_visa_sponsorship, detect_remote, extract_tags

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{site}"
HEADERS = {"User-Agent": "JobHunterPersonal/2.0 (personal-use)"}
TIMEOUT = 25
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _get_with_retry(url: str, params: Optional[dict] = None) -> requests.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = BACKOFF_BASE ** attempt
                logger.warning("Rate-limited by Lever; waiting %.1fs", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning("Lever request failed (%s); retry %d in %.1fs", exc, attempt, wait)
            time.sleep(wait)
    raise RuntimeError("Lever: max retries exceeded")


def fetch(site: str) -> list[dict]:
    """
    Fetch all postings from a Lever company site.

    Args:
        site: Company site slug (e.g. 'netflix' from jobs.lever.co/netflix).

    Returns:
        List of normalised job dicts.
    """
    url = BASE_URL.format(site=site)
    try:
        r = _get_with_retry(url, params={"mode": "json"})
    except Exception as exc:
        logger.error("Lever[%s] failed: %s", site, exc)
        raise

    jobs = []
    for j in r.json():
        cats = j.get("categories") or {}
        title = j.get("text", "")
        location = cats.get("location", "") or j.get("workplaceType", "")
        description = _strip_html(j.get("descriptionPlain") or j.get("description") or "")
        # Lever timestamps are Unix ms
        posted_ts = j.get("createdAt", 0)
        if isinstance(posted_ts, (int, float)) and posted_ts > 0:
            from datetime import datetime, timezone
            posted_at = datetime.fromtimestamp(posted_ts / 1000, tz=timezone.utc).isoformat()
        else:
            posted_at = str(posted_ts)

        jobs.append({
            "job_key": f"lever:{site}:{j.get('id')}",
            "source": "Lever",
            "company": site,
            "title": title,
            "location": location,
            "posted_at": posted_at,
            "description": description,
            "url": j.get("hostedUrl", ""),
            "visa_sponsorship": int(detect_visa_sponsorship(description + " " + title)),
            "is_remote": int(detect_remote(location + " " + description)),
            "salary_range": "",
            "tags": str(extract_tags(title, description)),
        })

    logger.info("Lever[%s]: fetched %d jobs", site, len(jobs))
    return jobs
