"""
drafts.py — Resume draft and cover letter generator for Job Hunter Agent.

IMPORTANT RULES:
  - Only uses facts extracted from the uploaded resume PDF text.
  - Never invents employers, dates, job titles, projects, or qualifications.
  - Generated text is clearly marked as a DRAFT for user review.
  - Original PDFs are never modified.
  - Output is plain text (ATS-safe); user downloads and polishes.
"""

import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
import os

BASE = Path(__file__).parent
DRAFTS_DIR = Path(os.environ.get("JOB_HUNTER_DATA_DIR", str(BASE))) / "drafts_output"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Resume text parsing helpers
# ---------------------------------------------------------------------------

def _extract_section(text: str, *headers: str) -> str:
    """
    Extract the text block under any of the given section headers.
    Stops at the next ALL-CAPS or Title-Case header line.
    """
    pattern = "|".join(re.escape(h) for h in headers)
    m = re.search(
        rf"(?i)^\s*(?:{pattern})\s*[:\-]?\s*\n(.*?)(?=\n\s*[A-Z][A-Z\s]{{3,}}|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _extract_skills(resume_text: str) -> list[str]:
    """Pull skill tokens from the Skills / Technical Skills section."""
    section = _extract_section(
        resume_text,
        "SKILLS", "TECHNICAL SKILLS", "TECHNOLOGIES", "TECH STACK",
        "Skills", "Technical Skills", "Technologies",
    )
    if not section:
        # Fallback: grab all known skill keywords from the full text
        from scorer import SKILL_KEYWORDS
        found = SKILL_KEYWORDS & set(re.findall(r"[a-zA-Z][a-zA-Z0-9+#._]{1,}", resume_text.lower()))
        return sorted(found)
    # Split on commas, bullets, pipes, newlines
    raw = re.split(r"[,|\n•·\-]+", section)
    skills = [s.strip() for s in raw if 2 < len(s.strip()) < 40]
    return [s for s in skills if s]


def _extract_name(resume_text: str) -> str:
    """Best-effort: first non-blank line is usually the candidate name."""
    for line in resume_text.splitlines():
        line = line.strip()
        if line and not re.match(r"(http|www|@|\+)", line, re.I):
            return line
    return "Candidate"


def _extract_contact_block(resume_text: str) -> str:
    """Extract lines containing email / phone / LinkedIn from top of resume."""
    lines = resume_text.splitlines()[:15]
    contact = []
    for line in lines:
        if re.search(r"[@\+linkedin\.com]", line, re.I):
            contact.append(line.strip())
    return " | ".join(contact) if contact else ""


def _extract_education(resume_text: str) -> str:
    return _extract_section(
        resume_text,
        "EDUCATION", "ACADEMIC", "Education", "Academic Background",
    )


def _extract_experience(resume_text: str) -> str:
    return _extract_section(
        resume_text,
        "EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT", "INTERNSHIP",
        "Experience", "Work Experience", "Employment History", "Internships",
    )


def _extract_projects(resume_text: str) -> str:
    return _extract_section(
        resume_text,
        "PROJECTS", "PROJECT", "PERSONAL PROJECTS", "ACADEMIC PROJECTS",
        "Projects", "Project Work",
    )


def _matched_skills_for_job(resume_text: str, job: dict) -> tuple[list[str], list[str]]:
    """
    Returns (matched_skills, missing_skills) relative to the job description.
    Only uses skills actually present in the resume.
    """
    from scorer import SKILL_KEYWORDS, _tokenize
    resume_skills = SKILL_KEYWORDS & _tokenize(resume_text)
    job_skills = SKILL_KEYWORDS & _tokenize(
        (job.get("title") or "") + " " + (job.get("description") or "")
    )
    matched = sorted(resume_skills & job_skills)
    missing = sorted(job_skills - resume_skills)
    return matched, missing


# ---------------------------------------------------------------------------
# Draft generators
# ---------------------------------------------------------------------------

def generate_resume_draft(job: dict, resume_text: str, resume_filename: str) -> str:
    """
    Build an ATS-optimised plain-text resume draft for a specific job.
    All content is sourced from resume_text; nothing is invented.

    Returns the draft as a string and also saves it to drafts_output/.
    """
    matched, missing = _matched_skills_for_job(resume_text, job)

    job_title = job.get("title", "")
    company = job.get("company", "")
    job_url = job.get("url", "")

    lines = [
        "=" * 72,
        f"[DRAFT — Review before sending — Do not submit without editing]",
        "=" * 72,
        "",
        f"TAILORED FOR: {job_title} @ {company}",
        f"SOURCE: {resume_filename}",
        f"MATCHED SKILLS (already present in source resume): {', '.join(matched) if matched else 'None detected'}",
        f"SKILLS IN JOB DESCRIPTION NOT FOUND IN SOURCE: {', '.join(missing[:8]) if missing else 'None'}",
        f"JOB URL: {job_url}",
        "",
        "SOURCE RESUME CONTENT (preserved without adding claims):",
        "",
        resume_text.strip(),
        "",
        "─" * 72,
        f"GENERATED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "[END DRAFT — Proofread, adjust formatting, and verify all claims before submitting]",
    ]

    draft_text = "\n".join(lines)
    _save_draft(job["job_key"], "resume", draft_text)
    return draft_text


def generate_cover_letter(job: dict, resume_text: str, resume_filename: str) -> str:
    """
    Generate a tailored cover letter template grounded in the resume.
    Placeholders are marked with [BRACKETS] for the user to personalise.

    Returns the draft as a string.
    """
    name = _extract_name(resume_text)
    contact = _extract_contact_block(resume_text)
    skills = _extract_skills(resume_text)
    matched, missing = _matched_skills_for_job(resume_text, job)

    job_title = job.get("title", "")
    company = job.get("company", "")
    job_url = job.get("url", "")
    today = datetime.now().strftime("%B %d, %Y")

    top_skills = matched[:4] if matched else skills[:4]
    skill_sentence = (
        f"My resume lists skills including {', '.join(top_skills)}"
        if len(top_skills) > 1
        else (f"My resume lists {top_skills[0]}" if top_skills else
              "My background is described in the attached resume")
    )

    draft = textwrap.dedent(f"""\
        ======================================================================
        [DRAFT COVER LETTER — Review all placeholders before sending]
        ======================================================================

        {today}

        Hiring Team
        {company.title()}
        [Company Address — optional]

        Re: Application for {job_title}

        Dear Hiring Manager,

        I am writing to apply for the {job_title} position at {company.title()}.

        {skill_sentence}. [Add one specific example from your resume that is relevant
        to this role. Use only real, verifiable experience.]

        [Write one sentence about what specifically interests you about {company.title()} —
        mention a real product, engineering blog post, or company mission that resonates
        with you. Do not invent details about the company.]

        I am particularly interested in this role because [describe an aspect of the
        published job description that genuinely interests you].

        I would welcome the opportunity to discuss how my skills align with your
        team's needs. Thank you for your time and consideration.

        Sincerely,
        {name}
        {contact}

        ======================================================================
        TAILORED FOR: {job_title} @ {company}
        SOURCE RESUME: {resume_filename}
        MATCHED SKILLS: {', '.join(matched) if matched else 'None auto-detected'}
        SKILLS IN JD NOT IN RESUME: {', '.join(missing[:6]) if missing else 'None'}
        JOB URL: {job_url}
        GENERATED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
        ======================================================================
        [END DRAFT — All bracketed text MUST be replaced with real, accurate content.
         Never submit without personalising and verifying every claim.]
    """)

    _save_draft(job["job_key"], "cover_letter", draft)
    return draft


def _safe_filename(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:max_len]


def _save_draft(job_key: str, draft_type: str, content: str) -> Path:
    """Save draft to drafts_output/ and return the path."""
    safe_key = _safe_filename(job_key)
    filename = f"{draft_type}_{safe_key}.txt"
    path = DRAFTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path


def draft_path(job_key: str, draft_type: str) -> Path | None:
    """Return the path to a saved draft, or None if it doesn't exist."""
    safe_key = _safe_filename(job_key)
    path = DRAFTS_DIR / f"{draft_type}_{safe_key}.txt"
    return path if path.exists() else None
