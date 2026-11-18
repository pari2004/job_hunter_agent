"""
gmail_sender.py — Gmail API email sender for Job Hunter Agent.

SAFETY RULES enforced here:
- Never sends to guessed/inferred email addresses.
- Requires explicit recipient_source_url (where the email was found).
- Checks daily limit before every send.
- Blocks duplicate sends (same job_key + recipient).
- Validates attachment exists and is a readable PDF before attaching.
- Never logs full email body or recipient email in plain text.
- Gmail message ID is stored for tracking; body is stored locally only.
- Never sends during automated tests (caller must pass dry_run=True in tests).

RATE LIMITING:
- Gmail API free tier: 100 quota units/user/second; 1B/day.
- We default to max 10 outreach emails/day (configurable).
- 2-second inter-send delay to avoid quota bursts.
"""

import base64
import email
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import io
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import db
import gmail_auth

# Default daily outreach limit — user can override in Settings.
DEFAULT_DAILY_LIMIT = 10

# Minimum seconds between consecutive sends.
INTER_SEND_DELAY = 2.0


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def is_valid_email(address: str) -> bool:
    """Basic structural email validation. Does NOT verify deliverability."""
    return bool(_EMAIL_RE.match(address.strip()))


def _redact_email(address: str) -> str:
    """Return a partially redacted email safe for logging."""
    parts = address.split("@")
    if len(parts) != 2:
        return "[REDACTED]"
    local, domain = parts
    hidden_local = local[:2] + "***" if len(local) > 2 else "***"
    return f"{hidden_local}@{domain}"


def _build_message(
    sender_email: Optional[str],
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None,
) -> dict:
    """
    Build a Gmail API-compatible base64url-encoded message dict.
    Raises ValueError if the attachment is missing or unreadable.
    """
    msg = email.mime.multipart.MIMEMultipart()
    msg["to"]      = to_email
    if sender_email:
        msg["from"] = sender_email
    msg["subject"] = subject

    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    if attachment_path is not None:
        pdf_data = _read_pdf_attachment(attachment_path)

        part = email.mime.base.MIMEBase("application", "pdf")
        part.set_payload(pdf_data)
        email.encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment_path.name,
        )
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def _read_pdf_attachment(attachment_path: Path) -> bytes:
    """Read and validate a non-empty PDF attachment before any send."""
    if not attachment_path.is_file():
        raise ValueError(
            f"Attachment not found: {attachment_path.name}. "
            "Generate the resume PDF before sending."
        )
    if attachment_path.suffix.lower() != ".pdf":
        raise ValueError("Resume attachment must be a PDF file.")
    try:
        pdf_data = attachment_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read PDF attachment: {attachment_path.name}.") from exc
    if not pdf_data.startswith(b"%PDF-"):
        raise ValueError(f"Attachment is not a valid PDF: {attachment_path.name}.")
    try:
        from pypdf import PdfReader

        if not PdfReader(io.BytesIO(pdf_data), strict=True).pages:
            raise ValueError("PDF contains no pages.")
    except Exception as exc:
        raise ValueError(f"Attachment is not a readable PDF: {attachment_path.name}.") from exc
    return pdf_data


def _redact_sensitive_text(value: str) -> str:
    """Remove email addresses and common credential fields from provider errors."""
    value = re.sub(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        "[REDACTED]",
        value,
    )
    return re.sub(
        r"(?i)\b(access_token|refresh_token|client_secret|authorization)\b"
        r"(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        value,
    )


def _is_https_source_url(source_url: str) -> bool:
    """Check URL structure; publication of the contact must still be verified by the user."""
    parsed = urlsplit(source_url.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def get_gmail_service():
    """Return an authorized Gmail API service object, or raise."""
    creds = gmail_auth.get_credentials()
    if creds is None:
        raise PermissionError(
            "Gmail not authorized. Connect Gmail first on the Gmail Outreach page."
        )
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Test email (always only to own address)
# ---------------------------------------------------------------------------

def send_test_email(
    to_address: str,
    attachment_path: Optional[Path] = None,
    dry_run: bool = False,
    own_address_confirmed: bool = False,
) -> dict:
    """
    Send a test email to to_address ONLY (must be your own address).

    Returns:
        dict with keys: success (bool), message_id (str), error (str)

    Args:
        to_address: The user's configured email address.
        attachment_path: Optional PDF to attach.
        dry_run: If True, build the message but do NOT send it.
                 Used in automated tests.
        own_address_confirmed: User confirms the configured recipient belongs to them.
    """
    if not is_valid_email(to_address):
        return {"success": False, "message_id": "", "error": f"Invalid email address format."}

    subject = "[Job Hunter Agent] Gmail Connection Test"
    body = (
        "This is a test message from Job Hunter Agent.\n\n"
        "If you received this email, your Gmail OAuth integration is working correctly.\n\n"
        "You can now use the outreach feature to send application emails to recruiters.\n\n"
        "--- Job Hunter Agent ---"
    )

    if dry_run:
        # Validate attachment but don't send
        if attachment_path:
            try:
                _read_pdf_attachment(attachment_path)
            except ValueError as exc:
                return {"success": False, "message_id": "", "error": str(exc)}
        return {"success": True, "message_id": "DRY_RUN_TEST", "error": ""}

    if not own_address_confirmed:
        return {
            "success": False,
            "message_id": "",
            "error": "Confirm that the test recipient is your own configured email address.",
        }

    try:
        service = get_gmail_service()
        msg_dict = _build_message(None, to_address, subject, body, attachment_path)
        result = service.users().messages().send(userId="me", body=msg_dict).execute()
        msg_id = result.get("id", "")
        if not msg_id:
            return {
                "success": False,
                "message_id": "",
                "error": "Gmail API did not return a message ID; connection test is not confirmed.",
            }
        db.audit("GMAIL:TEST_SENT", detail="to=[REDACTED] test email")
        return {"success": True, "message_id": msg_id, "error": ""}

    except PermissionError as e:
        return {"success": False, "message_id": "", "error": str(e)}
    except ValueError as e:
        return {"success": False, "message_id": "", "error": str(e)}
    except Exception as e:
        err = _redact_sensitive_text(str(e))
        return {"success": False, "message_id": "", "error": f"Gmail API error: {err}"}


# ---------------------------------------------------------------------------
# Recruiter outreach send
# ---------------------------------------------------------------------------

def compose_outreach_email(
    job: dict,
    resume_text: str,
    sender_name: str,
    resume_filename: str,
) -> tuple[str, str]:
    """
    Generate a professional subject + body for a recruiter outreach email.

    Content is grounded in the job description and resume text.
    No qualifications are invented. Returns (subject, body).

    Args:
        job: Job dict from the database.
        resume_text: Plain text extracted from the chosen resume PDF.
        sender_name: The candidate's name (extracted from resume or entered by user).
        resume_filename: Filename of the attached resume PDF.
    """
    title   = job.get("title", "Software Engineer")
    company = (job.get("company") or "").title()
    loc     = job.get("location") or "the listed location"
    job_url = job.get("url", "")

    # Extract first meaningful line of resume as sender name heuristic
    if not sender_name:
        for ln in resume_text.splitlines():
            ln = ln.strip()
            if ln and len(ln) < 60 and not ln.startswith("SKILL"):
                sender_name = ln
                break
        if not sender_name:
            sender_name = "[Your Name]"

    subject = f"Application for {title} — {sender_name}"
    from scorer import SKILL_KEYWORDS, _tokenize
    resume_skills = sorted(SKILL_KEYWORDS & _tokenize(resume_text))
    skills_line = (
        f"My resume lists skills including {', '.join(resume_skills[:5])}."
        if resume_skills else
        "My background and qualifications are described in the attached resume."
    )

    body_lines = [
        f"Dear Hiring Team at {company},",
        "",
        f"I am writing to express my interest in the {title} role at {company}"
        + (f" ({loc})" if loc and loc != "the listed location" else "")
        + ".",
        "",
        skills_line,
        "Please find my resume attached for your consideration.",
        "",
    ]

    # Add a snippet of the job description context (first sentence of description)
    desc = (job.get("description") or "").strip()
    if desc:
        first_sent = desc.split(".")[0].strip()
        if 20 < len(first_sent) < 200:
            body_lines += [
                f"The job posting describes the role as focused on: {first_sent}.",
                "",
            ]

    body_lines += [
        "I would welcome the opportunity to discuss how my background aligns with your "
        "team's goals. Please feel free to reach out at your convenience.",
        "",
        f"Job reference: {job_url}" if job_url else "",
        "",
        f"Thank you for your time and consideration.",
        "",
        f"Best regards,",
        f"{sender_name}",
    ]

    body = "\n".join(ln for ln in body_lines if ln is not None)
    return subject, body


def send_outreach_email(
    job: dict,
    recipient_email: str,
    recipient_source_url: str,
    resume_text: str,
    sender_name: str,
    resume_filename: str,
    attachment_path: Optional[Path],
    daily_limit: int = DEFAULT_DAILY_LIMIT,
    dry_run: bool = False,
) -> dict:
    """
    Send a recruiter outreach email with PDF resume attachment.

    GUARDS enforced (all raise ValueError or return error if violated):
    1. recipient_email must pass structural validation.
    2. recipient_source_url must be a non-empty verified URL.
    3. Duplicate check: same job_key + recipient never sent twice.
    4. Daily limit: will not exceed daily_limit sends today.
    5. Attachment must exist and be non-empty.
    6. dry_run=True skips actual sending (for tests).

    Returns:
        dict with keys: success, message_id, outreach_id, error
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Guard 1: email validation ─────────────────────────────────────────
    if not is_valid_email(recipient_email):
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": "Invalid recipient email address format."}
    recipient_email = recipient_email.strip().casefold()

    # ── Guard 2: source URL required ─────────────────────────────────────
    if not _is_https_source_url(recipient_source_url):
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": "An https:// contact source URL is required. Verify the contact was published."}

    # ── Guard 3: duplicate check ──────────────────────────────────────────
    if db.is_already_contacted(job["job_key"], recipient_email):
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": f"Already contacted {_redact_email(recipient_email)} for this job."}

    # ── Guard 4: daily limit ──────────────────────────────────────────────
    today_count = db.get_daily_outreach_count(today)
    if today_count >= daily_limit:
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": f"Daily outreach limit reached ({today_count}/{daily_limit}). "
                         "Increase the limit in Settings or try again tomorrow."}

    # ── Compose ───────────────────────────────────────────────────────────
    subject, body = compose_outreach_email(job, resume_text, sender_name, resume_filename)

    # ── Guard 5: attachment validation ────────────────────────────────────
    if attachment_path is None and not dry_run:
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": "A generated PDF resume attachment is required before sending."}
    if attachment_path is not None:
        try:
            _read_pdf_attachment(attachment_path)
        except ValueError as exc:
            return {"success": False, "message_id": "", "outreach_id": None,
                    "error": str(exc)}

    # ── Queue in DB ───────────────────────────────────────────────────────
    outreach_id = db.create_outreach(
        job_key=job["job_key"],
        company=(job.get("company") or "").title(),
        job_title=job.get("title", ""),
        recipient_email=recipient_email,
        recipient_source_url=recipient_source_url,
        subject=subject,
        body=body,
        resume_filename=resume_filename,
    )
    if outreach_id is None:
        return {"success": False, "message_id": "", "outreach_id": None,
                "error": "Outreach record already exists (duplicate blocked by DB)."}

    # ── Dry run ───────────────────────────────────────────────────────────
    if dry_run:
        return {"success": True, "message_id": "DRY_RUN", "outreach_id": outreach_id,
                "error": ""}

    # ── Send via Gmail API ────────────────────────────────────────────────
    time.sleep(INTER_SEND_DELAY)
    try:
        service = get_gmail_service()
        msg_dict = _build_message(None, recipient_email, subject, body, attachment_path)
        result = service.users().messages().send(userId="me", body=msg_dict).execute()
        msg_id = result.get("id", "")
        if not msg_id:
            error = "Gmail API did not return a message ID; send is not confirmed."
            db.mark_outreach_failed(outreach_id, error)
            return {"success": False, "message_id": "", "outreach_id": outreach_id,
                    "error": error}

        db.mark_outreach_sent(outreach_id, msg_id)
        return {"success": True, "message_id": msg_id, "outreach_id": outreach_id, "error": ""}

    except PermissionError as e:
        err = _redact_sensitive_text(str(e))
        db.mark_outreach_failed(outreach_id, err[:200])
        return {"success": False, "message_id": "", "outreach_id": outreach_id, "error": err}
    except ValueError as e:
        err = _redact_sensitive_text(str(e))
        db.mark_outreach_failed(outreach_id, err[:200])
        return {"success": False, "message_id": "", "outreach_id": outreach_id, "error": err}
    except Exception as e:
        err = _redact_sensitive_text(str(e))
        db.mark_outreach_failed(outreach_id, err[:200])
        return {"success": False, "message_id": "", "outreach_id": outreach_id,
                "error": f"Gmail API error: {err}"}
