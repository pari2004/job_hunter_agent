"""
pdf_generator.py — PDF resume and cover letter generator for Job Hunter Agent.

Uses ReportLab to produce ATS-readable, machine-parseable PDFs from
plain resume text. No content is invented — only text extracted from
uploaded resumes plus the job header is included.

The generated PDF uses:
- Standard PDF/A-compatible fonts (Helvetica family — no embedding needed).
- Single-column layout for maximum ATS compatibility.
- Selectable text (not rasterized/image).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    _REPORTLAB_OK = True
except ImportError:
    _REPORTLAB_OK = False

OUTPUT_DIR = Path(__file__).parent / "drafts_output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _safe_filename(s: str) -> str:
    """Convert an arbitrary string to a safe filename component."""
    return re.sub(r"[^a-z0-9_\-]", "_", s.lower())[:50]


def _check_reportlab():
    if not _REPORTLAB_OK:
        raise ImportError(
            "reportlab not installed. Run: pip install reportlab"
        )


def generate_pdf_resume(
    job: dict,
    resume_text: str,
    resume_name: str,
) -> Path:
    """
    Generate an ATS-friendly PDF resume for the given job.

    The PDF contains only text sourced from resume_text.
    No qualifications, dates, employers, or skills are invented.

    Returns the Path to the generated PDF file.
    """
    _check_reportlab()

    safe_key = _safe_filename(job.get("job_key", "job"))
    out_path = OUTPUT_DIR / f"resume_{safe_key}.pdf"

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    style_name  = ParagraphStyle("name",  fontName="Helvetica-Bold", fontSize=16,
                                 spaceAfter=4, alignment=TA_CENTER)
    style_h1    = ParagraphStyle("h1",    fontName="Helvetica-Bold", fontSize=12,
                                 spaceBefore=10, spaceAfter=3,
                                 textColor=HexColor("#1d4ed8"))
    style_body  = ParagraphStyle("body",  fontName="Helvetica",      fontSize=10,
                                 leading=14, spaceAfter=2)
    style_small = ParagraphStyle("small", fontName="Helvetica",      fontSize=8,
                                 textColor=HexColor("#64748b"), spaceAfter=6,
                                 alignment=TA_CENTER)

    elements = []

    # Header: job title being applied for
    company = job.get("company", "").title()
    title   = job.get("title", "Software Engineer")
    loc     = job.get("location") or "Not specified"
    url     = job.get("url", "")

    # Extract candidate name (first non-empty line of resume, if plausible)
    first_lines = [ln.strip() for ln in resume_text.splitlines() if ln.strip()]
    candidate_name = first_lines[0] if first_lines else "[Your Name]"
    # Heuristic: name is usually short and on the first line
    if len(candidate_name) > 60 or candidate_name.startswith("SKILLS"):
        candidate_name = "[Your Name]"

    elements.append(Paragraph(candidate_name, style_name))
    elements.append(Paragraph(
        f"Applying for: <b>{title}</b> at <b>{company}</b>",
        style_small,
    ))
    elements.append(Paragraph(
        f"Location: {loc}" + (f" &nbsp;|&nbsp; {url}" if url else ""),
        style_small,
    ))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(HRFlowable(width="100%", thickness=1,
                                color=HexColor("#1d4ed8"), spaceAfter=6))

    # Body: resume text, parsed into sections
    lines = resume_text.splitlines()
    current_section: list[str] = []
    SECTION_HEADERS = {
        "education", "skills", "experience", "projects", "certifications",
        "internship", "internships", "achievements", "awards", "publications",
        "summary", "objective", "contact", "work experience",
    }

    def flush_section(heading: str, body_lines: list[str]):
        if not body_lines:
            return
        elements.append(Paragraph(heading.upper(), style_h1))
        elements.append(HRFlowable(width="100%", thickness=0.5,
                                    color=HexColor("#94a3b8"), spaceAfter=4))
        for ln in body_lines:
            if ln.strip():
                safe_ln = ln.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                # Bullet points
                if safe_ln.startswith(("•", "-", "*", "·")):
                    safe_ln = "• " + safe_ln.lstrip("•-*· ").strip()
                elements.append(Paragraph(safe_ln, style_body))
        elements.append(Spacer(1, 0.2 * cm))

    current_heading = "Resume"
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        ln_lower = ln.lower().rstrip(":")

        if any(ln_lower == h or ln_lower == h + ":" for h in SECTION_HEADERS):
            flush_section(current_heading, current_section)
            current_heading = ln.rstrip(":")
            current_section = []
        elif ln:
            current_section.append(ln)
        i += 1

    flush_section(current_heading, current_section)

    # Footer disclaimer
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(HRFlowable(width="100%", thickness=0.5,
                                color=HexColor("#cbd5e1"), spaceAfter=4))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elements.append(Paragraph(
        f"Generated {ts} by Job Hunter Agent — "
        "content sourced from uploaded resume only — verify all details before submitting.",
        style_small,
    ))

    doc.build(elements)
    return out_path


def generate_pdf_cover_letter(
    job: dict,
    resume_text: str,
    cover_letter_text: str,
) -> Path:
    """
    Render an existing cover-letter text string as a PDF.

    Accepts the plain-text draft (may contain [BRACKET] placeholders).
    Returns the Path to the generated PDF file.
    """
    _check_reportlab()

    safe_key = _safe_filename(job.get("job_key", "job"))
    out_path = OUTPUT_DIR / f"cover_letter_{safe_key}.pdf"

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    style_body = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=16,
                                spaceAfter=8)
    style_small = ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                 textColor=HexColor("#64748b"), spaceAfter=4,
                                 alignment=TA_CENTER)

    elements = []
    for para in cover_letter_text.split("\n\n"):
        para = para.strip()
        if not para:
            elements.append(Spacer(1, 0.3 * cm))
            continue
        safe_para = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        elements.append(Paragraph(safe_para, style_body))

    elements.append(Spacer(1, 0.5 * cm))
    elements.append(HRFlowable(width="100%", thickness=0.5,
                                color=HexColor("#cbd5e1"), spaceAfter=4))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elements.append(Paragraph(
        f"Generated {ts} — review all [BRACKET] placeholders before sending.",
        style_small,
    ))

    doc.build(elements)
    return out_path


def reportlab_available() -> bool:
    return _REPORTLAB_OK
