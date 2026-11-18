"""
tests/test_adapters.py — Integration tests for job board adapters.

These tests make real HTTP calls to public APIs.
They are skipped automatically if the network is unavailable.
Run: python -m pytest tests/test_adapters.py -v -m integration
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import requests

# ---------------------------------------------------------------------------
# Network availability check
# ---------------------------------------------------------------------------

def _network_ok() -> bool:
    try:
        requests.get("https://boards-api.greenhouse.io", timeout=5)
        return True
    except Exception:
        return False


requires_network = pytest.mark.skipif(
    not _network_ok(),
    reason="Network not available — skipping live API tests",
)


# ---------------------------------------------------------------------------
# Greenhouse adapter tests
# ---------------------------------------------------------------------------

@requires_network
class TestGreenhouseAdapter:
    def test_fetch_known_token_returns_list(self):
        from adapters.greenhouse import fetch
        jobs = fetch("airbnb")
        assert isinstance(jobs, list)
        assert len(jobs) > 0

    def test_job_has_required_fields(self):
        from adapters.greenhouse import fetch
        jobs = fetch("airbnb")
        for key in ["job_key", "source", "company", "title", "location",
                    "posted_at", "description", "url"]:
            assert key in jobs[0], f"Missing field: {key}"

    def test_job_key_format(self):
        from adapters.greenhouse import fetch
        jobs = fetch("airbnb")
        assert all(j["job_key"].startswith("gh:airbnb:") for j in jobs)

    def test_source_is_greenhouse(self):
        from adapters.greenhouse import fetch
        jobs = fetch("airbnb")
        assert all(j["source"] == "Greenhouse" for j in jobs)

    def test_invalid_token_raises(self):
        from adapters.greenhouse import fetch
        with pytest.raises(Exception):
            fetch("this-token-definitely-does-not-exist-xyz-999")

    def test_visa_sponsorship_is_int(self):
        from adapters.greenhouse import fetch
        jobs = fetch("airbnb")
        assert all(isinstance(j["visa_sponsorship"], int) for j in jobs)

    def test_stripe_has_india_jobs(self):
        from adapters.greenhouse import fetch
        jobs = fetch("stripe")
        india = [j for j in jobs if any(
            kw in (j.get("location") or "").lower()
            for kw in ["india", "bengaluru", "bangalore"]
        )]
        assert len(india) > 0, "Stripe expected to have India jobs"


# ---------------------------------------------------------------------------
# Lever adapter tests
# ---------------------------------------------------------------------------

@requires_network
class TestLeverAdapter:
    def test_fetch_known_site_returns_list(self):
        from adapters.lever import fetch
        jobs = fetch("cred")
        assert isinstance(jobs, list)

    def test_job_has_required_fields(self):
        from adapters.lever import fetch
        jobs = fetch("cred")
        if not jobs:
            pytest.skip("No jobs currently on cred Lever board")
        for key in ["job_key", "source", "company", "title", "location",
                    "posted_at", "description", "url"]:
            assert key in jobs[0], f"Missing field: {key}"

    def test_job_key_format(self):
        from adapters.lever import fetch
        jobs = fetch("cred")
        if not jobs:
            pytest.skip("No jobs currently on cred Lever board")
        assert all(j["job_key"].startswith("lever:cred:") for j in jobs)

    def test_invalid_site_raises(self):
        from adapters.lever import fetch
        with pytest.raises(Exception):
            fetch("this-site-does-not-exist-xyz-999-abc")


# ---------------------------------------------------------------------------
# Deduplication tests (no network required)
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Verify that upsert_jobs deduplicates correctly across sources."""

    def test_same_key_deduped(self):
        import db, tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        original_db = db.DB
        db.DB = Path(tmp.name)
        db.init_db()

        job = {
            "job_key": "gh:test:1",
            "source": "Greenhouse",
            "company": "test",
            "title": "Engineer",
            "location": "Bangalore",
            "posted_at": "2024-01-01",
            "description": "Test",
            "url": "https://example.com/1",
            "visa_sponsorship": 0,
            "is_remote": 0,
            "salary_range": "",
            "tags": "[]",
        }

        db.upsert_jobs([job, job, job])  # three identical entries
        all_jobs = db.get_all_jobs()
        assert len(all_jobs) == 1

        db.DB = original_db
        # SQLite WAL files may still be held on Windows — best-effort cleanup
        import gc
        gc.collect()
        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(tmp.name + ext)
            except OSError:
                pass
