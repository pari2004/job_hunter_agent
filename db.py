"""
db.py — centralised SQLite access layer for Job Hunter Agent.
All schema creation, migrations, and CRUD helpers live here.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
DB = Path(os.environ.get("JOB_HUNTER_DB_PATH", str(BASE / "jobs.db"))).expanduser()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key         TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT DEFAULT '',
    posted_at       TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    url             TEXT DEFAULT '',
    first_seen      TEXT NOT NULL,
    score           INTEGER DEFAULT 0,
    matched_resume  TEXT DEFAULT '',
    visa_sponsorship INTEGER DEFAULT 0,   -- 1 if job mentions visa/relocation support
    is_remote       INTEGER DEFAULT 0,
    salary_range    TEXT DEFAULT '',
    tags            TEXT DEFAULT '',       -- JSON list of detected role tags
    required_experience TEXT DEFAULT ''    -- fresher | junior | mid | senior | ''
);

CREATE TABLE IF NOT EXISTS applications (
    job_key     TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'Discovered',
    notes       TEXT DEFAULT '',
    updated_at  TEXT NOT NULL,
    submitted_at TEXT DEFAULT '',
    source_url  TEXT DEFAULT '',
    draft_path  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    event       TEXT NOT NULL,
    job_key     TEXT DEFAULT '',
    detail      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS daily_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_date  TEXT NOT NULL,
    job_key     TEXT NOT NULL,
    priority    INTEGER DEFAULT 0,
    added_at    TEXT NOT NULL,
    UNIQUE(queue_date, job_key)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    job_key     TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    dismissed   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS outreach (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key         TEXT NOT NULL,
    company         TEXT NOT NULL DEFAULT '',
    job_title       TEXT NOT NULL DEFAULT '',
    recipient_email TEXT NOT NULL,
    recipient_source_url TEXT NOT NULL DEFAULT '',  -- URL where email was found
    subject         TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    resume_filename TEXT NOT NULL DEFAULT '',
    resume_version  TEXT NOT NULL DEFAULT '',
    gmail_message_id TEXT DEFAULT '',               -- returned by Gmail API on success
    status          TEXT NOT NULL DEFAULT 'queued', -- queued|sent|failed|bounced|replied|follow_up_due
    error_detail    TEXT DEFAULT '',                -- redacted error info
    send_ts         TEXT DEFAULT '',
    follow_up_date  TEXT DEFAULT '',
    recruiter_replied INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE(job_key, recipient_email)                -- prevent duplicate outreach
);
"""

_MIGRATIONS = [
    # v1 → add visa_sponsorship, is_remote, salary_range, tags to jobs
    "ALTER TABLE jobs ADD COLUMN visa_sponsorship INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN is_remote INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN salary_range TEXT DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN tags TEXT DEFAULT ''",
    # v1 → extend applications table
    "ALTER TABLE applications ADD COLUMN submitted_at TEXT DEFAULT ''",
    "ALTER TABLE applications ADD COLUMN source_url TEXT DEFAULT ''",
    "ALTER TABLE applications ADD COLUMN draft_path TEXT DEFAULT ''",
    # v3 → required_experience level detection
    "ALTER TABLE jobs ADD COLUMN required_experience TEXT DEFAULT ''",
    # v2 → outreach table (created via schema; migration for existing DBs)
    """CREATE TABLE IF NOT EXISTS outreach (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        job_key         TEXT NOT NULL,
        company         TEXT NOT NULL DEFAULT '',
        job_title       TEXT NOT NULL DEFAULT '',
        recipient_email TEXT NOT NULL,
        recipient_source_url TEXT NOT NULL DEFAULT '',
        subject         TEXT NOT NULL DEFAULT '',
        body            TEXT NOT NULL DEFAULT '',
        resume_filename TEXT NOT NULL DEFAULT '',
        resume_version  TEXT NOT NULL DEFAULT '',
        gmail_message_id TEXT DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'queued',
        error_detail    TEXT DEFAULT '',
        send_ts         TEXT DEFAULT '',
        follow_up_date  TEXT DEFAULT '',
        recruiter_replied INTEGER DEFAULT 0,
        created_at      TEXT NOT NULL,
        UNIQUE(job_key, recipient_email)
    )""",
]


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    """Create tables and run any outstanding migrations."""
    with _connect() as con:
        for stmt in SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                con.execute(s)
        # soft migrations — ignore if column already exists
        for sql in _MIGRATIONS:
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def upsert_jobs(jobs: list[dict]) -> int:
    """Insert or update jobs. Returns count of new rows inserted."""
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    with _connect() as con:
        for j in jobs:
            existed = con.execute(
                "SELECT 1 FROM jobs WHERE job_key=?", (j["job_key"],)
            ).fetchone() is not None
            cur = con.execute(
                """INSERT INTO jobs
                    (job_key,source,company,title,location,posted_at,
                     description,url,first_seen,visa_sponsorship,is_remote,
                     salary_range,tags,required_experience)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_key) DO UPDATE SET
                     title=excluded.title,
                     location=excluded.location,
                     posted_at=excluded.posted_at,
                     description=excluded.description,
                     url=excluded.url,
                     visa_sponsorship=excluded.visa_sponsorship,
                     is_remote=excluded.is_remote,
                     salary_range=excluded.salary_range,
                     tags=excluded.tags,
                     required_experience=excluded.required_experience""",
                (
                    j["job_key"], j["source"], j["company"], j["title"],
                    j.get("location", ""), str(j.get("posted_at", "")),
                    j.get("description", ""), j.get("url", ""),
                    now,
                    int(j.get("visa_sponsorship", 0)),
                    int(j.get("is_remote", 0)),
                    j.get("salary_range", ""),
                    j.get("tags", "[]"),
                    j.get("required_experience", ""),
                ),
            )
            if not existed and cur.rowcount == 1:
                new_count += 1
    return new_count


def get_all_jobs() -> list[dict]:
    with _connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM jobs ORDER BY first_seen DESC"
        )]


def get_job(job_key: str) -> dict | None:
    with _connect() as con:
        row = con.execute("SELECT * FROM jobs WHERE job_key=?", (job_key,)).fetchone()
        return dict(row) if row else None


def update_score(job_key: str, score: int, resume_name: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE jobs SET score=?, matched_resume=? WHERE job_key=?",
            (score, resume_name, job_key),
        )


def backfill_experience_levels() -> int:
    """
    For every job whose required_experience is empty, detect and store it.
    Returns the number of rows updated.
    """
    import scorer as _scorer
    with _connect() as con:
        rows = con.execute(
            "SELECT job_key, title, description FROM jobs WHERE required_experience = ''"
        ).fetchall()
        updated = 0
        for row in rows:
            combined = (row["title"] or "") + " " + (row["description"] or "")
            level = _scorer.detect_experience_level(combined)
            if level:
                con.execute(
                    "UPDATE jobs SET required_experience=? WHERE job_key=?",
                    (level, row["job_key"]),
                )
                updated += 1
    return updated


def job_exists_by_url(url: str) -> bool:
    if not url:
        return False
    with _connect() as con:
        row = con.execute("SELECT 1 FROM jobs WHERE url=?", (url,)).fetchone()
        return row is not None


def job_exists_by_title_company(title: str, company: str) -> bool:
    with _connect() as con:
        row = con.execute(
            "SELECT 1 FROM jobs WHERE lower(title)=lower(?) AND lower(company)=lower(?)",
            (title, company),
        ).fetchone()
        return row is not None


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

APPLICATION_STATUSES = [
    "Discovered",
    "Shortlisted",
    "Ready to apply",
    "Applied",
    "Rejected",
    "Interview",
    "Offer",
    "Withdrawn",
]


def get_application(job_key: str) -> dict | None:
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM applications WHERE job_key=?", (job_key,)
        ).fetchone()
        return dict(row) if row else None


def get_status(job_key: str) -> str:
    app = get_application(job_key)
    return app["status"] if app else "Discovered"


def set_status(job_key: str, status: str, notes: str = "", draft_path: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    submitted_at = now if status == "Applied" else ""
    with _connect() as con:
        con.execute(
            """INSERT INTO applications
                (job_key,status,notes,updated_at,submitted_at,draft_path)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(job_key) DO UPDATE SET
                 status=excluded.status,
                 notes=CASE WHEN excluded.notes='' THEN notes ELSE excluded.notes END,
                 updated_at=excluded.updated_at,
                 submitted_at=CASE WHEN excluded.submitted_at='' THEN submitted_at
                              ELSE excluded.submitted_at END,
                 draft_path=CASE WHEN excluded.draft_path='' THEN draft_path
                            ELSE excluded.draft_path END""",
            (job_key, status, notes, now, submitted_at, draft_path),
        )
    audit(f"STATUS:{status}", job_key, notes)


def is_already_applied(job_key: str) -> bool:
    app = get_application(job_key)
    return app is not None and app["status"] in ("Applied", "Interview", "Offer")


def get_all_applications() -> list[dict]:
    with _connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC"
        )]


def get_jobs_with_status() -> list[dict]:
    """Return jobs joined with their application status."""
    with _connect() as con:
        rows = con.execute("""
            SELECT j.*, COALESCE(a.status,'Discovered') as app_status,
                   COALESCE(a.notes,'') as notes,
                   COALESCE(a.updated_at,'') as status_updated_at,
                   COALESCE(a.draft_path,'') as draft_path
            FROM jobs j
            LEFT JOIN applications a ON j.job_key = a.job_key
            ORDER BY j.score DESC, j.first_seen DESC
        """).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Daily Queue
# ---------------------------------------------------------------------------

def get_queue(date_str: str) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """SELECT q.*, j.title, j.company, j.location, j.score,
                      j.url, j.matched_resume,
                      COALESCE(a.status,'Discovered') as app_status
               FROM daily_queue q
               JOIN jobs j ON q.job_key=j.job_key
               LEFT JOIN applications a ON q.job_key=a.job_key
               WHERE q.queue_date=?
               ORDER BY q.priority DESC""",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_to_queue(date_str: str, job_key: str, priority: int = 0) -> bool:
    """Returns True if added, False if duplicate."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as con:
            con.execute(
                "INSERT INTO daily_queue(queue_date,job_key,priority,added_at) VALUES(?,?,?,?)",
                (date_str, job_key, priority, now),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def queue_count(date_str: str) -> int:
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM daily_queue WHERE queue_date=?", (date_str,)
        ).fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def add_alert(job_key: str, alert_type: str, message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            "INSERT INTO alerts(created_at,job_key,alert_type,message) VALUES(?,?,?,?)",
            (now, job_key, alert_type, message),
        )


def get_active_alerts() -> list[dict]:
    with _connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM alerts WHERE dismissed=0 ORDER BY created_at DESC"
        )]


def dismiss_alert(alert_id: int) -> None:
    with _connect() as con:
        con.execute("UPDATE alerts SET dismissed=1 WHERE id=?", (alert_id,))


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def audit(event: str, job_key: str = "", detail: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            "INSERT INTO audit_log(ts,event,job_key,detail) VALUES(?,?,?,?)",
            (now, event, job_key, detail),
        )


def get_audit_log(limit: int = 100) -> list[dict]:
    with _connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        )]


# ---------------------------------------------------------------------------
# Outreach tracking
# ---------------------------------------------------------------------------

OUTREACH_STATUSES = ["queued", "sent", "failed", "bounced", "replied", "follow_up_due"]


def create_outreach(
    job_key: str,
    company: str,
    job_title: str,
    recipient_email: str,
    recipient_source_url: str,
    subject: str,
    body: str,
    resume_filename: str,
    resume_version: str = "",
) -> int | None:
    """
    Queue an outreach email record. Returns the new row id, or None if
    a duplicate (same job_key + recipient_email) already exists.

    The caller is responsible for:
    - Ensuring recipient_email was explicitly published by the employer.
    - Never guessing or inferring email addresses.
    """
    now = datetime.now(timezone.utc).isoformat()
    recipient_email = recipient_email.strip().casefold()
    new_id = None
    try:
        with _connect() as con:
            cur = con.execute(
                """INSERT INTO outreach
                   (job_key,company,job_title,recipient_email,recipient_source_url,
                    subject,body,resume_filename,resume_version,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'queued',?)""",
                (job_key, company, job_title, recipient_email, recipient_source_url,
                 subject, body, resume_filename, resume_version, now),
            )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate blocked
    # Audit outside the connection block to avoid nested lock
    if new_id is not None:
        audit("OUTREACH:QUEUED", job_key, f"to=[REDACTED] subject={subject[:40]}")
    return new_id



def mark_outreach_sent(
    outreach_id: int,
    gmail_message_id: str,
    follow_up_days: int = 5,
) -> None:
    """Record a successful send. Never claims delivery unless confirmed by API."""
    now = datetime.now(timezone.utc).isoformat()
    from datetime import timedelta
    follow_up_dt = (datetime.now(timezone.utc) + timedelta(days=follow_up_days))
    follow_up_date = follow_up_dt.strftime("%Y-%m-%d")
    with _connect() as con:
        con.execute(
            """UPDATE outreach SET status='sent', gmail_message_id=?,
               send_ts=?, follow_up_date=? WHERE id=?""",
            (gmail_message_id, now, follow_up_date, outreach_id),
        )
    audit("OUTREACH:SENT", detail=f"id={outreach_id} msg_id=[REDACTED]")


def mark_outreach_failed(outreach_id: int, error_summary: str) -> None:
    """Record a failed send. Sensitive details must be redacted by the caller."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            """UPDATE outreach SET status='failed', error_detail=?,
               send_ts=? WHERE id=?""",
            (error_summary[:500], now, outreach_id),
        )
    audit("OUTREACH:FAILED", detail=f"id={outreach_id}")


def get_outreach_records(status: str | None = None) -> list[dict]:
    with _connect() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM outreach WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM outreach ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def is_already_contacted(job_key: str, recipient_email: str) -> bool:
    """Return True if we have already sent/queued for this job+email pair."""
    with _connect() as con:
        row = con.execute(
            "SELECT id FROM outreach WHERE job_key=? AND lower(recipient_email)=?",
            (job_key, recipient_email.strip().casefold()),
        ).fetchone()
        return row is not None


def get_daily_outreach_count(date_str: str) -> int:
    """Count sent or queued outreach records for a given date."""
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM outreach WHERE DATE(created_at)=? AND status IN ('sent','queued')",
            (date_str,),
        ).fetchone()
        return row[0] if row else 0


def get_follow_up_due() -> list[dict]:
    """Return sent outreach records whose follow-up date is today or past."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM outreach
               WHERE status='sent' AND recruiter_replied=0
               AND follow_up_date != '' AND follow_up_date <= ?
               ORDER BY follow_up_date""",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_recruiter_replied(outreach_id: int) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE outreach SET recruiter_replied=1, status='replied' WHERE id=?",
            (outreach_id,),
        )
    audit("OUTREACH:REPLIED", detail=f"id={outreach_id}")
