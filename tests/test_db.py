"""
tests/test_db.py — Unit tests for the db module.
Uses a temporary in-memory/temp database to avoid polluting production data.
Run: python -m pytest tests/ -v
"""

import sys
import os
import tempfile
from pathlib import Path

# Point db module to a temp file before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["TEST_DB_PATH"] = _tmp.name

sys.path.insert(0, str(Path(__file__).parent.parent))

# Monkey-patch the DB path before importing db
import db as _db_module
_db_module.DB = Path(_tmp.name)

import pytest
import db


@pytest.fixture(autouse=True)
def fresh_db():
    """Recreate tables before each test."""
    db.init_db()
    yield
    # Clean up after each test
    import sqlite3
    with sqlite3.connect(db.DB) as con:
        con.execute("DELETE FROM jobs")
        con.execute("DELETE FROM applications")
        con.execute("DELETE FROM audit_log")
        con.execute("DELETE FROM daily_queue")
        con.execute("DELETE FROM alerts")


SAMPLE_JOB = {
    "job_key": "gh:stripe:123",
    "source": "Greenhouse",
    "company": "stripe",
    "title": "Software Engineer",
    "location": "Bangalore, India",
    "posted_at": "2024-10-01",
    "description": "Python backend engineer role.",
    "url": "https://boards.greenhouse.io/stripe/jobs/123",
    "visa_sponsorship": 0,
    "is_remote": 0,
    "salary_range": "",
    "tags": "['software engineer', 'backend']",
}


class TestUpsertJobs:
    def test_insert_new_job(self):
        db.upsert_jobs([SAMPLE_JOB])
        jobs = db.get_all_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_key"] == SAMPLE_JOB["job_key"]

    def test_upsert_deduplicates(self):
        db.upsert_jobs([SAMPLE_JOB])
        db.upsert_jobs([SAMPLE_JOB])  # same job again
        jobs = db.get_all_jobs()
        assert len(jobs) == 1

    def test_upsert_returns_only_new_job_count(self):
        assert db.upsert_jobs([SAMPLE_JOB, SAMPLE_JOB]) == 1
        assert db.upsert_jobs([SAMPLE_JOB]) == 0

    def test_upsert_updates_existing(self):
        db.upsert_jobs([SAMPLE_JOB])
        updated = {**SAMPLE_JOB, "title": "Senior Software Engineer"}
        db.upsert_jobs([updated])
        job = db.get_job(SAMPLE_JOB["job_key"])
        assert job["title"] == "Senior Software Engineer"

    def test_get_job_returns_none_for_missing(self):
        assert db.get_job("nonexistent:key") is None

    def test_multiple_jobs(self):
        jobs = [
            {**SAMPLE_JOB, "job_key": f"test:{i}", "title": f"Role {i}"}
            for i in range(5)
        ]
        db.upsert_jobs(jobs)
        assert len(db.get_all_jobs()) == 5


class TestScoreUpdate:
    def test_update_score(self):
        db.upsert_jobs([SAMPLE_JOB])
        db.update_score(SAMPLE_JOB["job_key"], 75, "python_cv.pdf")
        job = db.get_job(SAMPLE_JOB["job_key"])
        assert job["score"] == 75
        assert job["matched_resume"] == "python_cv.pdf"


class TestApplicationStatus:
    def setup_method(self):
        db.upsert_jobs([SAMPLE_JOB])

    def test_default_status_is_discovered(self):
        status = db.get_status(SAMPLE_JOB["job_key"])
        assert status == "Discovered"

    def test_set_and_get_status(self):
        db.set_status(SAMPLE_JOB["job_key"], "Shortlisted")
        assert db.get_status(SAMPLE_JOB["job_key"]) == "Shortlisted"

    def test_status_progression(self):
        for status in ["Shortlisted", "Ready to apply", "Applied"]:
            db.set_status(SAMPLE_JOB["job_key"], status)
            assert db.get_status(SAMPLE_JOB["job_key"]) == status

    def test_is_already_applied_true(self):
        db.set_status(SAMPLE_JOB["job_key"], "Applied")
        assert db.is_already_applied(SAMPLE_JOB["job_key"])

    def test_is_already_applied_false(self):
        db.set_status(SAMPLE_JOB["job_key"], "Shortlisted")
        assert not db.is_already_applied(SAMPLE_JOB["job_key"])

    def test_is_already_applied_false_for_new_job(self):
        assert not db.is_already_applied("gh:test:999")


class TestDailyQueue:
    def setup_method(self):
        db.upsert_jobs([SAMPLE_JOB])

    def test_add_to_queue(self):
        result = db.add_to_queue("2024-10-01", SAMPLE_JOB["job_key"], priority=80)
        assert result is True

    def test_add_duplicate_returns_false(self):
        db.add_to_queue("2024-10-01", SAMPLE_JOB["job_key"])
        result = db.add_to_queue("2024-10-01", SAMPLE_JOB["job_key"])
        assert result is False

    def test_queue_count(self):
        db.add_to_queue("2024-10-01", SAMPLE_JOB["job_key"])
        assert db.queue_count("2024-10-01") == 1

    def test_get_queue(self):
        db.add_to_queue("2024-10-01", SAMPLE_JOB["job_key"])
        queue = db.get_queue("2024-10-01")
        assert len(queue) == 1
        assert queue[0]["job_key"] == SAMPLE_JOB["job_key"]


class TestAlerts:
    def test_add_and_get_alert(self):
        db.add_alert("test:key", "HIGH MATCH", "Score 85/100")
        alerts = db.get_active_alerts()
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "HIGH MATCH"

    def test_dismiss_alert(self):
        db.add_alert("test:key", "HIGH MATCH", "Score 85/100")
        alert_id = db.get_active_alerts()[0]["id"]
        db.dismiss_alert(alert_id)
        assert len(db.get_active_alerts()) == 0


class TestAuditLog:
    def test_audit_creates_entry(self):
        db.audit("TEST:EVENT", "test:key", "detail here")
        log = db.get_audit_log()
        assert len(log) >= 1
        assert any(e["event"] == "TEST:EVENT" for e in log)
