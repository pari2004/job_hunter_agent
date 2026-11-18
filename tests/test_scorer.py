"""
tests/test_scorer.py — Unit tests for the scorer module.
Run: python -m pytest tests/ -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scorer import (
    score_job,
    best_resume_match,
    detect_visa_sponsorship,
    detect_remote,
    detect_senior_only,
    detect_fresher_friendly,
    extract_tags,
    SKILL_KEYWORDS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_JOB_INDIA = {
    "job_key": "test:1",
    "title": "Software Engineer",
    "description": (
        "We are looking for a junior software engineer with Python and Django experience. "
        "Located in Bengaluru, India. Entry-level role, 0-2 years experience."
    ),
    "location": "Bengaluru, India",
}

SAMPLE_JOB_SENIOR = {
    "job_key": "test:2",
    "title": "Senior Staff Engineer",
    "description": "10+ years experience required. Lead distributed systems team.",
    "location": "San Francisco, CA",
}

SAMPLE_JOB_REMOTE_VISA = {
    "job_key": "test:3",
    "title": "Backend Developer",
    "description": (
        "Remote position. We offer visa sponsorship and relocation assistance. "
        "Python, FastAPI, PostgreSQL, Docker required."
    ),
    "location": "Remote",
}

RESUME_PYTHON = (
    "John Doe | john@example.com\n\n"
    "SKILLS\nPython, Django, PostgreSQL, Docker, Git, Linux, REST APIs\n\n"
    "EDUCATION\nB.E. Computer Science, VTU, 2024\n\n"
    "PROJECTS\nBuilt a Django REST API for inventory management system."
)

RESUME_JAVA = (
    "Jane Smith | jane@example.com\n\n"
    "SKILLS\nJava, Spring Boot, MySQL, Maven, JUnit, Git\n\n"
    "EDUCATION\nB.Tech Computer Science, 2024"
)

# ---------------------------------------------------------------------------
# score_job tests
# ---------------------------------------------------------------------------

class TestScoreJob:
    def test_india_entry_level_python_job_high_score(self):
        score = score_job(SAMPLE_JOB_INDIA, RESUME_PYTHON)
        assert score >= 50, f"Expected ≥50 for matching India job, got {score}"

    def test_senior_job_penalised(self):
        score = score_job(SAMPLE_JOB_SENIOR, RESUME_PYTHON)
        # Senior-only should be penalised by -25
        assert score < 40, f"Expected low score for senior-only job, got {score}"

    def test_score_within_range(self):
        score = score_job(SAMPLE_JOB_INDIA, RESUME_PYTHON)
        assert 0 <= score <= 100

    def test_score_is_integer(self):
        score = score_job(SAMPLE_JOB_INDIA, RESUME_PYTHON)
        assert isinstance(score, int)

    def test_empty_job(self):
        empty = {"job_key": "x", "title": "", "description": "", "location": ""}
        score = score_job(empty, RESUME_PYTHON)
        assert score >= 0

    def test_empty_resume(self):
        score = score_job(SAMPLE_JOB_INDIA, "")
        assert score >= 0

    def test_visa_sponsorship_bonus(self):
        with_visa = score_job(SAMPLE_JOB_REMOTE_VISA, RESUME_PYTHON)
        without_visa = {**SAMPLE_JOB_REMOTE_VISA, "description": "Remote backend Python role."}
        without_score = score_job(without_visa, RESUME_PYTHON)
        assert with_visa >= without_score, "Visa sponsorship should not penalise"

    def test_bengaluru_bonus_higher_than_international(self):
        bangalore_job = {**SAMPLE_JOB_INDIA, "location": "Bangalore"}
        intl_job = {**SAMPLE_JOB_INDIA, "location": "New York, USA"}
        # Ensure bangalore has location bonus
        blr_score = score_job(bangalore_job, RESUME_PYTHON)
        intl_score = score_job(intl_job, RESUME_PYTHON)
        assert blr_score >= intl_score, "Bengaluru should score >= international"


# ---------------------------------------------------------------------------
# best_resume_match tests
# ---------------------------------------------------------------------------

class TestBestResumeMatch:
    def test_selects_python_resume_for_python_job(self):
        resumes = {"python_cv.pdf": RESUME_PYTHON, "java_cv.pdf": RESUME_JAVA}
        score, name = best_resume_match(SAMPLE_JOB_INDIA, resumes)
        assert name == "python_cv.pdf", f"Expected Python resume, got {name}"

    def test_selects_java_resume_for_java_job(self):
        java_job = {
            "job_key": "test:java",
            "title": "Java Developer",
            "description": "Spring Boot, Java, JUnit, Maven. Backend microservices.",
            "location": "Pune",
        }
        resumes = {"python_cv.pdf": RESUME_PYTHON, "java_cv.pdf": RESUME_JAVA}
        score, name = best_resume_match(java_job, resumes)
        assert name == "java_cv.pdf", f"Expected Java resume, got {name}"

    def test_empty_resumes_returns_zero(self):
        score, name = best_resume_match(SAMPLE_JOB_INDIA, {})
        assert score == 0
        assert name == ""

    def test_returns_tuple(self):
        result = best_resume_match(SAMPLE_JOB_INDIA, {"cv.pdf": RESUME_PYTHON})
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDetectors:
    def test_visa_sponsorship_detected(self):
        assert detect_visa_sponsorship("We offer visa sponsorship for this role.")
        assert detect_visa_sponsorship("H-1B support available.")
        assert detect_visa_sponsorship("We will sponsor your relocation assistance.")

    def test_no_false_visa_positive(self):
        assert not detect_visa_sponsorship("Standard software engineer role in Bengaluru.")

    def test_remote_detected(self):
        assert detect_remote("Fully remote position, work from home.")
        assert detect_remote("Hybrid role.")
        assert detect_remote("WFH option available.")

    def test_no_false_remote_positive(self):
        assert not detect_remote("Office-based role in Bangalore.")

    def test_senior_only_detected(self):
        assert detect_senior_only("Senior Software Engineer, 10+ years required.")
        assert detect_senior_only("Principal Engineer role.")

    def test_fresher_exempts_senior_detection(self):
        # Even if "senior" appears, "entry level" should cancel it
        assert not detect_senior_only("Senior-Adjacent role, entry level welcome, 0-2 years.")

    def test_fresher_detected(self):
        assert detect_fresher_friendly("Entry-level graduate engineer position.")
        assert detect_fresher_friendly("Fresher applications welcome.")
        assert detect_fresher_friendly("Campus hiring drive 2024.")

    def test_extract_tags_returns_list(self):
        tags = extract_tags("Python Developer", "Django REST API backend role")
        assert isinstance(tags, list)
        assert len(tags) > 0
