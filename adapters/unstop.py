"""
adapters/unstop.py — Unstop (formerly Dare2Compete) public jobs API adapter.

Uses Unstop's public REST API — no authentication required.
Returns JSON with full job metadata including experience range, skills, company info.
"""

import re
import time
from typing import Optional

import requests

API_URL = "https://unstop.com/api/public/opportunity/search-result"
TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://unstop.com/jobs",
    "Origin": "https://unstop.com",
}

DEFAULT_KEYWORDS = [
    "software engineer",
    "java developer",
    "python developer",
    "full stack developer",
    "backend developer",
    "frontend developer",
    "data engineer",
]

INDIA_TERMS = {"india", "bengaluru", "bangalore", "mumbai", "pune",
               "hyderabad", "delhi", "chennai", "noida", "gurgaon", "remote"}


def _extract_jobs(data: dict) -> list[dict]:
    """Extract job records from Unstop API response payload."""
    jobs: list[dict] = []

    items = []
    if isinstance(data, dict):
        # Try common response shapes
        items = (
            data.get("data", {}).get("data", [])
            or data.get("data", [])
            or data.get("result", {}).get("data", [])
            or []
        )

    for item in items:
        try:
            uid  = str(item.get("id", ""))
            if not uid:
                continue

            title = item.get("title") or item.get("name") or ""
            if not title:
                continue

            org   = item.get("organisation") or item.get("company") or {}
            company = (
                org.get("name") or org.get("organisation_name") or
                item.get("company_name") or "Unknown"
            )

            # Location
            city_info = item.get("city") or item.get("location") or {}
            if isinstance(city_info, dict):
                location = city_info.get("name") or city_info.get("city_name") or "India"
            elif isinstance(city_info, str):
                location = city_info
            else:
                location = "India"

            # Posted date
            posted_at = item.get("start_date") or item.get("published_at") or item.get("created_at") or ""
            if posted_at and len(posted_at) > 10:
                posted_at = posted_at[:10]  # keep YYYY-MM-DD

            # Experience
            min_exp = item.get("min_exp") or item.get("minimum_experience") or 0
            max_exp = item.get("max_exp") or item.get("maximum_experience") or 1
            salary  = item.get("salary") or item.get("ctc") or ""
            if isinstance(salary, (int, float)):
                salary = f"{salary} LPA"

            # Remote detection
            is_remote = 0
            work_mode = str(item.get("work_mode") or item.get("job_type") or "").lower()
            if "remote" in work_mode or "remote" in location.lower():
                is_remote = 1

            # Skills / tags
            skills = item.get("skills") or item.get("tags") or []
            if isinstance(skills, list):
                skill_names = [
                    (s.get("name") or s) if isinstance(s, dict) else str(s)
                    for s in skills[:10]
                ]
                tags_json = str(skill_names)
            else:
                tags_json = "[]"

            # Description
            desc = item.get("description") or item.get("about") or ""
            if isinstance(desc, dict):
                desc = str(desc)

            # URL
            slug = item.get("slug") or item.get("friendly_url") or uid
            url  = f"https://unstop.com/jobs/{slug}"

            # Skip non-India
            loc_lower = location.lower()
            if not is_remote and not any(t in loc_lower for t in INDIA_TERMS):
                continue

            # Skip jobs requiring >1 year experience
            try:
                if int(min_exp) > 1:
                    continue
            except (TypeError, ValueError):
                pass

            jobs.append({
                "job_key":        f"unstop:{uid}",
                "source":         "Unstop",
                "company":        str(company),
                "title":          str(title),
                "location":       location,
                "posted_at":      posted_at,
                "description":    str(desc)[:2000],
                "url":            url,
                "visa_sponsorship": 0,
                "is_remote":      is_remote,
                "salary_range":   str(salary),
                "tags":           tags_json,
            })
        except Exception:
            continue

    return jobs


def fetch(
    keywords: Optional[list[str]] = None,
    min_exp: int = 0,
    max_exp: int = 1,
    per_page: int = 20,
) -> list[dict]:
    """
    Fetch fresher jobs from Unstop's public API.

    Args:
        keywords:  Search terms. Defaults to DEFAULT_KEYWORDS.
        min_exp:   Minimum experience years filter (default 0).
        max_exp:   Maximum experience years filter (default 1).
        per_page:  Results per keyword request.

    Returns:
        List of job dicts compatible with db.upsert_jobs().
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    all_jobs: list[dict] = []
    seen: set[str] = set()

    for kw in keywords:
        params = {
            "opportunity":   "jobs",
            "per_page":      per_page,
            "oppstatus":     "open",
            "search":        kw,
            "min_exp":       min_exp,
            "max_exp":       max_exp,
            "start":         0,
            "ordering":      "latest",
        }
        try:
            resp = requests.get(API_URL, params=params, headers=_HEADERS, timeout=TIMEOUT)
            if resp.status_code == 429:
                raise RuntimeError("Unstop rate limited (HTTP 429). Wait before retrying.")
            resp.raise_for_status()
            data = resp.json()
            for j in _extract_jobs(data):
                if j["job_key"] not in seen:
                    seen.add(j["job_key"])
                    all_jobs.append(j)
        except RuntimeError:
            raise
        except requests.RequestException as e:
            raise RuntimeError(f"Unstop request failed for '{kw}': {e}") from e
        except Exception:
            pass

        time.sleep(1.5)

    return all_jobs
