"""Tests for truthful, resume-grounded draft generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import drafts


JOB = {
    "job_key": "gh:example:123",
    "title": "Python Developer",
    "company": "Example Co",
    "description": "Python and Django experience preferred.",
    "url": "https://example.com/jobs/123",
}


def test_resume_draft_preserves_source_without_synthesized_claims(tmp_path, monkeypatch):
    source = "Jane Doe\nSKILLS\nPython, Django\nEDUCATION\nComputer Science"
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)

    result = drafts.generate_resume_draft(JOB, source, "python.pdf")

    assert source in result
    assert "recent graduate" not in result.lower()
    assert "track record" not in result.lower()
    assert "strong foundation" not in result.lower()


def test_cover_letter_uses_resume_skills_and_marks_personal_claims(tmp_path, monkeypatch):
    source = "Jane Doe\nSKILLS\nPython, Django"
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)

    result = drafts.generate_cover_letter(JOB, source, "python.pdf")

    assert "my resume lists skills including django, python" in result.lower()
    assert "[Add one specific example from your resume" in result
    assert "recent computer science graduate" not in result.lower()
    assert "makes me a strong candidate" not in result.lower()
