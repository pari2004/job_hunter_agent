"""
pages/2_Drafts.py — Resume draft and cover letter generator.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import db
import drafts as drafter
import scorer

st.set_page_config(page_title="Resume Drafts · Job Hunter Agent", page_icon="📝", layout="wide")
from app_security import require_app_auth

require_app_auth()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.score-high { background:#16a34a; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-mid  { background:#d97706; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.skill-match { background:#164e63; color:#e0f2fe; border-radius:4px; padding:1px 6px; margin:2px; display:inline-block; font-size:0.8rem; }
.skill-miss  { background:#7f1d1d; color:#fee2e2; border-radius:4px; padding:1px 6px; margin:2px; display:inline-block; font-size:0.8rem; }
</style>
""", unsafe_allow_html=True)

db.init_db()

st.markdown("# 📝 Resume Drafts & Cover Letters")
st.caption(
    "Drafts are generated from your uploaded resume text only. "
    "No qualifications, employers, dates, or skills are invented. "
    "**Always review before submitting.**"
)

resumes = st.session_state.get("resumes", {})
if not resumes:
    st.warning("⚠️ No resumes loaded. Upload PDF(s) in the sidebar on the Dashboard page first.")
    st.stop()

jobs = db.get_jobs_with_status()
if not jobs:
    st.warning("No jobs in the database. Run a scan from the Dashboard first.")
    st.stop()

# ---------------------------------------------------------------------------
# Job selector
# ---------------------------------------------------------------------------
shortlisted = [j for j in jobs if j.get("app_status") in ("Shortlisted", "Ready to apply", "Discovered")]
shortlisted.sort(key=lambda j: int(j.get("score") or 0), reverse=True)

job_labels = {
    f"{j['title']} @ {j['company'].title()} (score: {j.get('score', 0)})": j
    for j in shortlisted[:50]
}

selected_label = st.selectbox("Select a job to generate drafts for:", list(job_labels.keys()))
selected_job = job_labels[selected_label]

# Resume selector
resume_name = st.selectbox("Which resume profile to use?", list(resumes.keys()))
resume_text = resumes[resume_name]

# ---------------------------------------------------------------------------
# Skills analysis panel
# ---------------------------------------------------------------------------
matched, missing = drafter._matched_skills_for_job(resume_text, selected_job)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**✅ Matched skills**")
    if matched:
        st.markdown(" ".join(f'<span class="skill-match">{s}</span>' for s in matched), unsafe_allow_html=True)
    else:
        st.caption("None auto-detected — check your resume PDF has selectable text.")

with c2:
    st.markdown("**⚠️ Skills in JD not in resume**")
    if missing:
        st.markdown(" ".join(f'<span class="skill-miss">{s}</span>' for s in missing), unsafe_allow_html=True)
        st.caption("Consider highlighting adjacent experience for these if you genuinely have it.")
    else:
        st.caption("None missing — great fit!")

st.divider()

# ---------------------------------------------------------------------------
# Generate buttons
# ---------------------------------------------------------------------------
g1, g2 = st.columns(2)

with g1:
    if st.button("📄 Generate Resume Draft", use_container_width=True, type="primary"):
        with st.spinner("Generating resume draft…"):
            try:
                draft_text = drafter.generate_resume_draft(selected_job, resume_text, resume_name)
                st.success("Resume draft generated!")
                st.text_area("Resume Draft (copy or download)", draft_text, height=500)
                st.download_button(
                    "⬇️ Download Resume Draft (.txt)",
                    data=draft_text,
                    file_name=f"resume_draft_{drafter._safe_filename(selected_job['job_key'])}.txt",
                    mime="text/plain",
                )
                # Update DB with draft path
                path = drafter.draft_path(selected_job["job_key"], "resume")
                if path:
                    db.set_status(selected_job["job_key"], db.get_status(selected_job["job_key"]), draft_path=str(path))
            except Exception as e:
                st.error(f"Error generating draft: {e}")

with g2:
    if st.button("✉️ Generate Cover Letter", use_container_width=True, type="primary"):
        with st.spinner("Generating cover letter…"):
            try:
                cl_text = drafter.generate_cover_letter(selected_job, resume_text, resume_name)
                st.success("Cover letter generated!")
                st.text_area("Cover Letter Draft (review all [BRACKETS])", cl_text, height=500)
                st.download_button(
                    "⬇️ Download Cover Letter (.txt)",
                    data=cl_text,
                    file_name=f"cover_letter_{drafter._safe_filename(selected_job['job_key'])}.txt",
                    mime="text/plain",
                )
            except Exception as e:
                st.error(f"Error generating cover letter: {e}")

# ---------------------------------------------------------------------------
# Existing drafts
# ---------------------------------------------------------------------------
st.divider()
st.markdown("### 📁 Saved Drafts")
resume_p = drafter.draft_path(selected_job["job_key"], "resume")
cl_p = drafter.draft_path(selected_job["job_key"], "cover_letter")

if resume_p:
    content = resume_p.read_text(encoding="utf-8")
    st.download_button("⬇️ Resume Draft (saved)", data=content,
                       file_name=resume_p.name, mime="text/plain")
if cl_p:
    content = cl_p.read_text(encoding="utf-8")
    st.download_button("⬇️ Cover Letter (saved)", data=content,
                       file_name=cl_p.name, mime="text/plain")
if not resume_p and not cl_p:
    st.caption("No drafts saved yet for this job.")

st.divider()
st.info(
    "**Integrity notice:** Drafts are built exclusively from your uploaded resume text. "
    "All [BRACKET] placeholders must be filled in by you with accurate, verifiable information. "
    "Never add fake employers, dates, skills, or projects. "
    "Original PDFs are never modified."
)
