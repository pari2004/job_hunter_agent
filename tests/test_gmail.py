"""
tests/test_gmail.py — Gmail integration tests (fully mocked, NO real sends).

All Gmail API calls are intercepted by unittest.mock.
No real emails are sent during these tests.
No real credentials.json or token.json are read.

Run: python -m pytest tests/test_gmail.py -v
"""

import sys
import os
import json
import stat
import tempfile
import base64
import email
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import db
import gmail_sender
import gmail_auth


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Each test gets a fresh in-memory DB."""
    original = db.DB
    db.DB = tmp_path / "test.db"
    db.init_db()
    yield
    db.DB = original


@pytest.fixture
def sample_job():
    job = {
        "job_key": "gh:testcorp:999",
        "source": "Greenhouse",
        "company": "testcorp",
        "title": "Software Engineer",
        "location": "Bangalore, India",
        "posted_at": "2024-10-01",
        "description": "Python Django backend, REST APIs, PostgreSQL.",
        "url": "https://boards.greenhouse.io/testcorp/jobs/999",
        "visa_sponsorship": 0,
        "is_remote": 0,
        "salary_range": "",
        "tags": "[]",
    }
    db.upsert_jobs([job])
    return job


@pytest.fixture
def sample_resume():
    return (
        "Jane Doe\njane@example.com\n\n"
        "EDUCATION\nB.E. Computer Science, VTU, 2024\n\n"
        "SKILLS\nPython, Django, PostgreSQL, REST APIs, Docker, Git\n\n"
        "EXPERIENCE\nSoftware Developer Intern — Sansera Engineering, 2024"
    )


def _write_pdf(path: Path) -> None:
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    pdf = Canvas(buffer)
    pdf.drawString(72, 720, "Test resume")
    pdf.save()
    path.write_bytes(buffer.getvalue())


MOCK_CREDS = MagicMock()
MOCK_CREDS.valid = True
MOCK_CREDS.expired = False


# ---------------------------------------------------------------------------
# gmail_auth tests (no file system access)
# ---------------------------------------------------------------------------

class TestGmailAuth:
    def test_credentials_file_missing_returns_false(self, tmp_path):
        original = gmail_auth.CREDENTIALS_FILE
        gmail_auth.CREDENTIALS_FILE = tmp_path / "nonexistent.json"
        assert not gmail_auth.credentials_file_exists()
        gmail_auth.CREDENTIALS_FILE = original

    def test_token_file_missing_returns_false(self, tmp_path):
        original = gmail_auth.TOKEN_FILE
        gmail_auth.TOKEN_FILE = tmp_path / "nonexistent.json"
        assert not gmail_auth.token_file_exists()
        gmail_auth.TOKEN_FILE = original

    def test_write_token_secure_creates_file(self, tmp_path):
        original = gmail_auth.TOKEN_FILE
        gmail_auth.TOKEN_FILE = tmp_path / "token.json"
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = json.dumps({"access_token": "MOCK", "client_id": "test"})
        gmail_auth._write_token_secure(mock_creds)
        assert gmail_auth.TOKEN_FILE.exists()
        gmail_auth.TOKEN_FILE = original

    def test_revoke_deletes_token(self, tmp_path):
        original = gmail_auth.TOKEN_FILE
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")
        gmail_auth.TOKEN_FILE = token_path
        result = gmail_auth.revoke_credentials()
        assert result is True
        assert not token_path.exists()
        gmail_auth.TOKEN_FILE = original

    def test_revoke_missing_returns_false(self, tmp_path):
        original = gmail_auth.TOKEN_FILE
        gmail_auth.TOKEN_FILE = tmp_path / "nonexistent.json"
        result = gmail_auth.revoke_credentials()
        assert result is False
        gmail_auth.TOKEN_FILE = original

    def test_auth_status_no_credentials_file(self, tmp_path):
        original_cred = gmail_auth.CREDENTIALS_FILE
        original_tok  = gmail_auth.TOKEN_FILE
        gmail_auth.CREDENTIALS_FILE = tmp_path / "no_creds.json"
        gmail_auth.TOKEN_FILE       = tmp_path / "no_token.json"
        status = gmail_auth.auth_status()
        assert status["connected"] is False
        assert status["credentials_file_present"] is False
        gmail_auth.CREDENTIALS_FILE = original_cred
        gmail_auth.TOKEN_FILE       = original_tok

    def test_auth_status_connected_with_valid_creds(self, tmp_path):
        original_cred = gmail_auth.CREDENTIALS_FILE
        original_tok  = gmail_auth.TOKEN_FILE
        cred_path = tmp_path / "credentials.json"
        cred_path.write_text(json.dumps({"installed": {}}))
        tok_path = tmp_path / "token.json"
        tok_path.write_text(json.dumps({"access_token": "MOCK"}))
        gmail_auth.CREDENTIALS_FILE = cred_path
        gmail_auth.TOKEN_FILE       = tok_path

        with patch("gmail_auth.get_credentials", return_value=MOCK_CREDS):
            status = gmail_auth.auth_status()

        assert status["connected"] is True
        assert status["token_valid"] is True
        gmail_auth.CREDENTIALS_FILE = original_cred
        gmail_auth.TOKEN_FILE       = original_tok

    def test_auth_status_does_not_expose_provider_error_details(self, tmp_path):
        original_cred = gmail_auth.CREDENTIALS_FILE
        original_tok = gmail_auth.TOKEN_FILE
        cred_path = tmp_path / "credentials.json"
        cred_path.write_text('{"installed": {}}')
        token_path = tmp_path / "token.json"
        token_path.write_text('{"access_token": "placeholder"}')
        gmail_auth.CREDENTIALS_FILE = cred_path
        gmail_auth.TOKEN_FILE = token_path

        with patch("gmail_auth.get_credentials", side_effect=RuntimeError("access_token=secret-value")):
            status = gmail_auth.auth_status()

        assert status["connected"] is False
        assert "secret-value" not in status["error"]
        assert "RuntimeError" in status["error"]
        gmail_auth.CREDENTIALS_FILE = original_cred
        gmail_auth.TOKEN_FILE = original_tok

    def test_authorized_email_is_never_guessed_from_oauth_client_id(self):
        assert gmail_auth.get_authorized_email() is None

    def test_run_auth_flow_no_credentials_raises(self, tmp_path):
        original = gmail_auth.CREDENTIALS_FILE
        gmail_auth.CREDENTIALS_FILE = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            gmail_auth.run_auth_flow()
        gmail_auth.CREDENTIALS_FILE = original


# ---------------------------------------------------------------------------
# gmail_sender validation tests
# ---------------------------------------------------------------------------

class TestEmailValidation:
    def test_valid_email(self):
        assert gmail_sender.is_valid_email("recruiter@company.com")
        assert gmail_sender.is_valid_email("hr.team+jobs@startup.io")

    def test_invalid_email_no_at(self):
        assert not gmail_sender.is_valid_email("notanemail")

    def test_invalid_email_no_domain(self):
        assert not gmail_sender.is_valid_email("user@")

    def test_invalid_email_empty(self):
        assert not gmail_sender.is_valid_email("")

    def test_redact_email_hides_local(self):
        result = gmail_sender._redact_email("recruiter@company.com")
        assert "recruiter" not in result
        assert "@company.com" in result

    def test_redact_short_email(self):
        result = gmail_sender._redact_email("a@b.com")
        assert "@b.com" in result


# ---------------------------------------------------------------------------
# send_test_email — dry_run=True (no API call)
# ---------------------------------------------------------------------------

class TestSendTestEmailDryRun:
    def test_dry_run_succeeds(self):
        result = gmail_sender.send_test_email("test@example.com", dry_run=True)
        assert result["success"] is True
        assert result["message_id"] == "DRY_RUN_TEST"
        assert result["error"] == ""

    def test_dry_run_invalid_email(self):
        result = gmail_sender.send_test_email("notvalid", dry_run=True)
        assert result["success"] is False
        assert "Invalid" in result["error"]

    def test_dry_run_missing_attachment(self, tmp_path):
        missing = tmp_path / "nonexistent.pdf"
        result = gmail_sender.send_test_email("test@example.com",
                                               attachment_path=missing, dry_run=True)
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_dry_run_with_existing_attachment(self, tmp_path):
        real_pdf = tmp_path / "resume.pdf"
        _write_pdf(real_pdf)
        result = gmail_sender.send_test_email("test@example.com",
                                               attachment_path=real_pdf, dry_run=True)
        assert result["success"] is True

    def test_invalid_pdf_attachment_rejected(self, tmp_path):
        invalid_pdf = tmp_path / "resume.pdf"
        invalid_pdf.write_bytes(b"%PDF-1.4 not really a PDF")

        result = gmail_sender.send_test_email(
            "test@example.com", attachment_path=invalid_pdf, dry_run=True
        )

        assert result["success"] is False
        assert "readable pdf" in result["error"].lower()

    def test_test_email_requires_self_confirmation(self):
        with patch("gmail_sender.get_gmail_service") as mock_service:
            result = gmail_sender.send_test_email(
                "owner@example.com", own_address_confirmed=False
            )
        assert result["success"] is False
        assert "own configured email address" in result["error"].lower()
        mock_service.assert_not_called()

    def test_test_email_uses_send_scope_without_profile_read(self):
        mock_service = MagicMock()
        mock_send = MagicMock()
        mock_send.execute.return_value = {"id": "test-message-id"}
        mock_service.users.return_value.messages.return_value.send.return_value = mock_send

        with patch("gmail_sender.get_gmail_service", return_value=mock_service):
            result = gmail_sender.send_test_email(
                "owner@example.com", own_address_confirmed=True
            )

        assert result["success"] is True
        assert result["message_id"] == "test-message-id"
        mock_service.users.return_value.getProfile.assert_not_called()

    def test_test_email_requires_gmail_message_id(self):
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {}

        with patch("gmail_sender.get_gmail_service", return_value=mock_service):
            result = gmail_sender.send_test_email(
                "owner@example.com", own_address_confirmed=True
            )

        assert result["success"] is False
        assert "not confirmed" in result["error"].lower()


# ---------------------------------------------------------------------------
# send_outreach_email — mocked Gmail API
# ---------------------------------------------------------------------------

class TestSendOutreachEmail:
    def test_invalid_email_rejected(self, sample_job):
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="notvalid",
            recipient_source_url="https://example.com/careers",
            resume_text="Jane Doe\nPython Django",
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert result["success"] is False
        assert "Invalid" in result["error"]

    def test_missing_source_url_rejected(self, sample_job):
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="",  # empty
            resume_text="Jane Doe\nPython",
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert result["success"] is False
        assert "source_url" in result["error"].lower() or "required" in result["error"].lower()

    def test_non_https_source_url_rejected(self, sample_job):
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="http://testcorp.com/careers",
            resume_text="Jane Doe\nPython",
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert result["success"] is False
        assert "https" in result["error"].lower()

    def test_dry_run_successful_send(self, sample_job, sample_resume):
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers/contact",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert result["success"] is True
        assert result["message_id"] == "DRY_RUN"
        assert result["outreach_id"] is not None

    def test_duplicate_blocked(self, sample_job, sample_resume):
        # First send
        r1 = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert r1["success"] is True

        # Duplicate attempt
        r2 = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="HR@TestCorp.COM",
            recipient_source_url="https://testcorp.com/careers",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=True,
        )
        assert r2["success"] is False
        assert "already contacted" in r2["error"].lower() or "duplicate" in r2["error"].lower()

    def test_daily_limit_enforced(self, sample_resume):
        # Insert 2 different jobs and send to same address on day limit=2
        for i in range(2):
            job = {
                "job_key": f"test:limit:{i}",
                "source": "test", "company": "co", "title": "SDE",
                "location": "Bangalore", "posted_at": "", "description": "",
                "url": f"https://example.com/{i}",
                "visa_sponsorship": 0, "is_remote": 0, "salary_range": "", "tags": "[]",
            }
            db.upsert_jobs([job])
            gmail_sender.send_outreach_email(
                job=job,
                recipient_email=f"hr{i}@co.com",
                recipient_source_url="https://co.com/careers",
                resume_text=sample_resume,
                sender_name="Jane Doe",
                resume_filename="resume.pdf",
                attachment_path=None,
                daily_limit=2,
                dry_run=True,
            )

        # Third attempt should be blocked
        job3 = {
            "job_key": "test:limit:3",
            "source": "test", "company": "co", "title": "SDE",
            "location": "Bangalore", "posted_at": "", "description": "",
            "url": "https://example.com/3",
            "visa_sponsorship": 0, "is_remote": 0, "salary_range": "", "tags": "[]",
        }
        db.upsert_jobs([job3])
        result = gmail_sender.send_outreach_email(
            job=job3,
            recipient_email="hr3@co.com",
            recipient_source_url="https://co.com/careers",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            daily_limit=2,
            dry_run=True,
        )
        assert result["success"] is False
        assert "limit" in result["error"].lower()

    def test_missing_attachment_rejected(self, sample_job, sample_resume, tmp_path):
        missing_pdf = tmp_path / "nonexistent_resume.pdf"
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=missing_pdf,
            dry_run=True,
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower() or "pdf" in result["error"].lower()

    def test_real_send_requires_attachment(self, sample_job, sample_resume):
        result = gmail_sender.send_outreach_email(
            job=sample_job,
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers",
            resume_text=sample_resume,
            sender_name="Jane Doe",
            resume_filename="resume.pdf",
            attachment_path=None,
            dry_run=False,
        )
        assert result["success"] is False
        assert "attachment is required" in result["error"].lower()
        assert db.get_outreach_records() == []

    def test_outreach_requires_gmail_message_id(self, sample_job, sample_resume, tmp_path):
        attachment = tmp_path / "resume.pdf"
        _write_pdf(attachment)
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {}

        with patch("gmail_sender.get_gmail_service", return_value=mock_service), \
             patch("gmail_sender.time.sleep"):
            result = gmail_sender.send_outreach_email(
                job=sample_job,
                recipient_email="hr@testcorp.com",
                recipient_source_url="https://testcorp.com/careers",
                resume_text=sample_resume,
                sender_name="Jane Doe",
                resume_filename="resume.pdf",
                attachment_path=attachment,
                dry_run=False,
            )

        assert result["success"] is False
        assert "not confirmed" in result["error"].lower()
        assert db.get_outreach_records("failed")[0]["status"] == "failed"

    def test_real_send_uses_mocked_api(self, sample_job, sample_resume, tmp_path):
        """Verify that a non-dry-run send calls the Gmail API (mocked) exactly once."""
        attachment = tmp_path / "resume.pdf"
        _write_pdf(attachment)
        mock_service    = MagicMock()
        mock_messages   = MagicMock()
        mock_send       = MagicMock()
        mock_send.execute.return_value = {"id": "mock_msg_id_123"}
        mock_messages.send.return_value = mock_send
        mock_service.users.return_value.messages.return_value = mock_messages
        mock_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "sender@gmail.com"
        }

        with patch("gmail_sender.get_gmail_service", return_value=mock_service), \
             patch("gmail_sender.time.sleep"):
            result = gmail_sender.send_outreach_email(
                job=sample_job,
                recipient_email="hr@testcorp.com",
                recipient_source_url="https://testcorp.com/careers",
                resume_text=sample_resume,
                sender_name="Jane Doe",
                resume_filename="resume.pdf",
                attachment_path=attachment,
                dry_run=False,
            )

        assert result["success"] is True
        assert result["message_id"] == "mock_msg_id_123"
        mock_messages.send.assert_called_once()
        raw = mock_messages.send.call_args.kwargs["body"]["raw"]
        message = email.message_from_bytes(base64.urlsafe_b64decode(raw))
        pdf_parts = [part for part in message.walk() if part.get_content_type() == "application/pdf"]
        assert len(pdf_parts) == 1
        assert pdf_parts[0].get_payload(decode=True).startswith(b"%PDF-")

    def test_revoked_auth_returns_error(self, sample_job, sample_resume, tmp_path):
        """Verify that a revoked token produces a clear error without crashing."""
        attachment = tmp_path / "resume.pdf"
        _write_pdf(attachment)
        with patch("gmail_sender.get_gmail_service",
                   side_effect=PermissionError("Gmail not authorized.")):
            result = gmail_sender.send_outreach_email(
                job=sample_job,
                recipient_email="hr@testcorp.com",
                recipient_source_url="https://testcorp.com/careers",
                resume_text=sample_resume,
                sender_name="Jane Doe",
                resume_filename="resume.pdf",
                attachment_path=attachment,
                dry_run=False,
            )
        assert result["success"] is False
        assert "authorized" in result["error"].lower() or "permission" in result["error"].lower()


# ---------------------------------------------------------------------------
# compose_outreach_email
# ---------------------------------------------------------------------------

class TestComposeEmail:
    def test_subject_contains_title(self, sample_job, sample_resume):
        subject, body = gmail_sender.compose_outreach_email(
            sample_job, sample_resume, "Jane Doe", "resume.pdf"
        )
        assert "Software Engineer" in subject
        assert "Jane Doe" in subject

    def test_body_contains_company(self, sample_job, sample_resume):
        _, body = gmail_sender.compose_outreach_email(
            sample_job, sample_resume, "Jane Doe", "resume.pdf"
        )
        assert "Testcorp" in body or "testcorp" in body.lower()

    def test_body_no_invented_content(self, sample_job, sample_resume):
        _, body = gmail_sender.compose_outreach_email(
            sample_job, sample_resume, "Jane Doe", "resume.pdf"
        )
        # Should not contain skills not in the job description or resume
        assert "blockchain" not in body.lower()
        assert "quantum" not in body.lower()
        assert "i was excited" not in body.lower()

    def test_body_contains_sender_name(self, sample_job, sample_resume):
        _, body = gmail_sender.compose_outreach_email(
            sample_job, sample_resume, "Jane Doe", "resume.pdf"
        )
        assert "Jane Doe" in body


# ---------------------------------------------------------------------------
# DB outreach functions
# ---------------------------------------------------------------------------

class TestOutreachDB:
    def test_create_outreach_returns_id(self, sample_job):
        oid = db.create_outreach(
            job_key=sample_job["job_key"],
            company="testcorp",
            job_title="SDE",
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers",
            subject="Application for SDE",
            body="Dear hiring team...",
            resume_filename="resume.pdf",
        )
        assert oid is not None
        assert isinstance(oid, int)

    def test_duplicate_outreach_returns_none(self, sample_job):
        kwargs = dict(
            job_key=sample_job["job_key"], company="testcorp", job_title="SDE",
            recipient_email="hr@testcorp.com",
            recipient_source_url="https://testcorp.com/careers",
            subject="Application", body="body", resume_filename="resume.pdf",
        )
        db.create_outreach(**kwargs)
        oid2 = db.create_outreach(**kwargs)
        assert oid2 is None

    def test_is_already_contacted(self, sample_job):
        db.create_outreach(
            job_key=sample_job["job_key"], company="tc", job_title="SDE",
            recipient_email="hr@tc.com", recipient_source_url="https://tc.com",
            subject="App", body="body", resume_filename="r.pdf",
        )
        assert db.is_already_contacted(sample_job["job_key"], "hr@tc.com")
        assert not db.is_already_contacted(sample_job["job_key"], "other@tc.com")

    def test_mark_sent_updates_status(self, sample_job):
        oid = db.create_outreach(
            job_key=sample_job["job_key"], company="tc", job_title="SDE",
            recipient_email="hr@tc.com", recipient_source_url="https://tc.com",
            subject="App", body="body", resume_filename="r.pdf",
        )
        db.mark_outreach_sent(oid, "gmail_msg_abc")
        records = db.get_outreach_records("sent")
        assert len(records) == 1
        assert records[0]["status"] == "sent"
        # gmail_message_id should be stored
        assert records[0]["gmail_message_id"] == "gmail_msg_abc"

    def test_mark_failed_updates_status(self, sample_job):
        oid = db.create_outreach(
            job_key=sample_job["job_key"], company="tc", job_title="SDE",
            recipient_email="hr@tc.com", recipient_source_url="https://tc.com",
            subject="App", body="body", resume_filename="r.pdf",
        )
        db.mark_outreach_failed(oid, "SMTP timeout")
        records = db.get_outreach_records("failed")
        assert len(records) == 1
        assert records[0]["error_detail"] == "SMTP timeout"

    def test_daily_count(self, sample_job):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert db.get_daily_outreach_count(today) == 0

        db.create_outreach(
            job_key=sample_job["job_key"], company="tc", job_title="SDE",
            recipient_email="hr@tc.com", recipient_source_url="https://tc.com",
            subject="App", body="body", resume_filename="r.pdf",
        )
        assert db.get_daily_outreach_count(today) == 1

    def test_mark_recruiter_replied(self, sample_job):
        oid = db.create_outreach(
            job_key=sample_job["job_key"], company="tc", job_title="SDE",
            recipient_email="hr@tc.com", recipient_source_url="https://tc.com",
            subject="App", body="body", resume_filename="r.pdf",
        )
        db.mark_outreach_sent(oid, "msg123")
        db.mark_recruiter_replied(oid)
        records = db.get_outreach_records("replied")
        assert len(records) == 1
        assert records[0]["recruiter_replied"] == 1
