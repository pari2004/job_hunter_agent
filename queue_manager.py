"""
queue_manager.py — Daily application queue manager for Job Hunter Agent.

Builds a prioritised daily queue of up to MAX_QUEUE_SIZE jobs.
Guards against:
  - Duplicate job entries in the same queue day
  - Re-queuing already applied/interviewed/offered jobs
  - Queuing jobs below the minimum score threshold
"""

from datetime import datetime, timezone

import db

MAX_QUEUE_SIZE = 50
MIN_SCORE_FOR_QUEUE = 30  # configurable via build_queue()

ELIGIBLE_STATUSES = {"Discovered", "Shortlisted", "Ready to apply"}


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_queue(
    date_str: str | None = None,
    max_size: int = MAX_QUEUE_SIZE,
    min_score: int = MIN_SCORE_FOR_QUEUE,
) -> dict:
    """
    Populate the daily queue for the given date with top-scoring eligible jobs.

    Args:
        date_str: ISO date string (YYYY-MM-DD). Defaults to today.
        max_size: Maximum queue entries (default 50).
        min_score: Minimum job score to be queue-eligible (default 30).

    Returns:
        dict with keys: date, added, skipped_duplicate, skipped_applied,
                        skipped_low_score, total_queue_size
    """
    if date_str is None:
        date_str = today_str()

    existing_count = db.queue_count(date_str)
    slots_remaining = max_size - existing_count

    if slots_remaining <= 0:
        return {
            "date": date_str,
            "added": 0,
            "skipped_duplicate": 0,
            "skipped_applied": 0,
            "skipped_low_score": 0,
            "total_queue_size": existing_count,
            "message": f"Queue is already full ({existing_count}/{max_size}).",
        }

    # Get all jobs sorted by score descending
    jobs = db.get_jobs_with_status()
    jobs_sorted = sorted(jobs, key=lambda j: int(j.get("score") or 0), reverse=True)

    stats = {
        "added": 0,
        "skipped_duplicate": 0,
        "skipped_applied": 0,
        "skipped_low_score": 0,
    }

    for job in jobs_sorted:
        if stats["added"] >= slots_remaining:
            break

        job_key = job["job_key"]
        score = int(job.get("score") or 0)
        app_status = job.get("app_status", "Discovered")

        # Guard: too low score
        if score < min_score:
            stats["skipped_low_score"] += 1
            continue

        # Guard: already in terminal or advanced state
        if app_status not in ELIGIBLE_STATUSES:
            stats["skipped_applied"] += 1
            continue

        # Guard: already applied (double-check DB)
        if db.is_already_applied(job_key):
            stats["skipped_applied"] += 1
            continue

        # Add to queue (returns False if already in queue for this date)
        added = db.add_to_queue(date_str, job_key, priority=score)
        if added:
            stats["added"] += 1
            db.audit("QUEUE:ADD", job_key, f"date={date_str} score={score}")
        else:
            stats["skipped_duplicate"] += 1

    total = db.queue_count(date_str)
    db.audit(
        "QUEUE:BUILD",
        detail=(
            f"date={date_str} added={stats['added']} "
            f"skipped_applied={stats['skipped_applied']} "
            f"skipped_low_score={stats['skipped_low_score']} "
            f"total={total}"
        ),
    )

    return {
        "date": date_str,
        "total_queue_size": total,
        "message": f"Queue updated: {stats['added']} jobs added ({total}/{max_size} total).",
        **stats,
    }


def get_todays_queue() -> list[dict]:
    """Return today's queue entries with full job details."""
    return db.get_queue(today_str())


def mark_opened(job_key: str) -> None:
    """Record that the user opened the application page."""
    current = db.get_status(job_key)
    if current in ("Discovered", "Shortlisted"):
        db.set_status(job_key, "Ready to apply", notes="Application page opened by user")


def mark_submitted(job_key: str, notes: str = "") -> None:
    """
    Mark a job as Applied.
    GUARD: Checks for duplicate submission before writing.
    Application is NEVER auto-submitted through an unsupported workflow.
    """
    if db.is_already_applied(job_key):
        return  # silent duplicate guard
    db.set_status(job_key, "Applied", notes=notes or "Submitted by user")
    db.audit("SUBMIT:CONFIRMED", job_key, notes)


def queue_stats(date_str: str | None = None) -> dict:
    """Return statistics for the queue on a given date."""
    if date_str is None:
        date_str = today_str()
    entries = db.get_queue(date_str)
    statuses = [e.get("app_status", "Discovered") for e in entries]
    return {
        "date": date_str,
        "total": len(entries),
        "applied": statuses.count("Applied"),
        "ready": statuses.count("Ready to apply"),
        "shortlisted": statuses.count("Shortlisted"),
        "discovered": statuses.count("Discovered"),
    }
