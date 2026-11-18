"""
pages/1_Pipeline.py — Full job pipeline view with filtering.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import db
from ui_helpers import fmt_date as _fmt_date, render_job_badges as _render_badges

st.set_page_config(page_title="Job Pipeline · Job Hunter Agent", page_icon="📋", layout="wide")
from app_security import require_app_auth

require_app_auth()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.score-high { background:#16a34a; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-mid  { background:#d97706; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-low  { background:#475569; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.badge { border-radius:6px; padding:2px 8px; font-size:0.78rem; font-weight:600; }
.badge-blue   { background:#1d4ed8; color:#fff; }
.badge-green  { background:#15803d; color:#fff; }
.badge-orange { background:#b45309; color:#fff; }
.badge-purple { background:#7e22ce; color:#fff; }
</style>
""", unsafe_allow_html=True)

db.init_db()
st.markdown("# 📋 Job Pipeline")
st.caption("All discovered jobs — filter, review, and set application status.")

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
jobs = db.get_jobs_with_status()

f1, f2, f3, f4, f5, f6 = st.columns([2, 2, 1, 1, 1, 1])
query = f1.text_input("🔍 Search title / company", placeholder="e.g. Python, Backend…")
location_filter = f2.selectbox(
    "📍 Location",
    ["All", "Bengaluru", "Mysuru", "Mumbai", "Pune", "Remote", "International"],
)
status_filter = f3.selectbox(
    "Status",
    ["All"] + db.APPLICATION_STATUSES,
)
min_score = f4.slider("Min score", 0, 100, 20)
source_filter = f5.selectbox(
    "Source",
    ["All"] + sorted({j["source"] for j in jobs}),
)
experience_filter = f6.selectbox(
    "🎓 Experience",
    ["All", "Fresher", "Junior", "Mid", "Senior", "Unknown"],
)

show_visa = st.checkbox("🛂 Visa sponsorship only", value=False)
show_fresher = st.checkbox("🎓 Fresher-friendly only", value=False)

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
def passes_filters(j: dict) -> bool:
    loc = (j.get("location") or "").lower()
    title_co = (j.get("title", "") + " " + j.get("company", "")).lower()
    desc = (j.get("description") or "").lower()

    if query and query.lower() not in title_co and query.lower() not in desc:
        return False
    if status_filter != "All" and j.get("app_status") != status_filter:
        return False
    if source_filter != "All" and j.get("source") != source_filter:
        return False
    if int(j.get("score") or 0) < min_score:
        return False
    if show_visa and not j.get("visa_sponsorship"):
        return False
    if experience_filter != "All":
        exp = (j.get("required_experience") or "").lower()
        if experience_filter == "Unknown":
            if exp:            # has a detected level → exclude
                return False
        elif exp != experience_filter.lower():
            return False

    if location_filter == "Bengaluru":
        if not any(x in loc for x in ["bengaluru", "bangalore"]):
            return False
    elif location_filter == "Mysuru":
        if not any(x in loc for x in ["mysuru", "mysore"]):
            return False
    elif location_filter == "Mumbai":
        if "mumbai" not in loc:
            return False
    elif location_filter == "Pune":
        if "pune" not in loc:
            return False
    elif location_filter == "Remote":
        if not j.get("is_remote"):
            return False
    elif location_filter == "International":
        india_kws = ["india", "bengaluru", "bangalore", "mysuru", "mysore", "mumbai", "pune"]
        if any(kw in loc for kw in india_kws):
            return False

    if show_fresher:
        from scorer import detect_fresher_friendly
        if not detect_fresher_friendly((j.get("title") or "") + " " + (j.get("description") or "")):
            return False

    return True


filtered = [j for j in jobs if passes_filters(j)]
filtered.sort(key=lambda j: (int(j.get("score") or 0), str(j.get("posted_at") or "")), reverse=True)

st.caption(f"Showing **{len(filtered)}** of **{len(jobs)}** jobs")

if not filtered:
    st.warning("No jobs match your filters. Try widening your search or running a scan first.")
    st.stop()

# ---------------------------------------------------------------------------
# Job cards
# ---------------------------------------------------------------------------
STATUS_COLORS = {
    "Discovered": "badge-slate",
    "Shortlisted": "badge-blue",
    "Ready to apply": "badge-orange",
    "Applied": "badge-green",
    "Rejected": "badge-red",
    "Interview": "badge-purple",
    "Offer": "badge-green",
    "Withdrawn": "badge-slate",
}

for j in filtered:
    score = int(j.get("score") or 0)
    score_class = "score-high" if score >= 60 else "score-mid" if score >= 40 else "score-low"
    app_status = j.get("app_status", "Discovered")
    status_css = STATUS_COLORS.get(app_status, "badge-slate")

    with st.container(border=True):
        col_main, col_side = st.columns([5, 1])

        with col_main:
            exp_level = (j.get("required_experience") or "").strip()
            exp_colors = {
                "fresher": "badge-green",
                "junior":  "badge-blue",
                "mid":     "badge-orange",
                "senior":  "badge-red",
            }
            exp_badge = (
                f' &nbsp;<span class="badge {exp_colors.get(exp_level, "badge-slate")}">'
                f'🎓 {exp_level.title()}</span>'
                if exp_level else ""
            )
            st.markdown(
                f"**{j['title']}** &nbsp;·&nbsp; {j['company'].title()} &nbsp;"
                f'<span class="{score_class}">{score}/100</span> &nbsp;'
                f'<span class="badge {status_css}">{app_status}</span>'
                f'{exp_badge}',
                unsafe_allow_html=True,
            )
            posted = _fmt_date(j.get("posted_at") or "")
            loc = j.get("location") or "Location not listed"
            st.caption(
                f"📍 {loc} &nbsp;·&nbsp; Source: {j['source']} &nbsp;·&nbsp; "
                f"Posted: {posted} &nbsp;·&nbsp; First seen: {_fmt_date(j.get('first_seen',''))}"
            )
            _render_badges(j)

            desc = (j.get("description") or "")
            if desc:
                with st.expander("Description (first 600 chars)"):
                    st.write(desc[:600] + ("…" if len(desc) > 600 else ""))

            if j.get("salary_range"):
                st.caption(f"💰 {j['salary_range']}")
            if j.get("matched_resume"):
                st.caption(f"📄 Best resume: **{j['matched_resume']}**")
            if j.get("url"):
                st.markdown(f"[🔗 Open official application page]({j['url']})")

        with col_side:
            st.markdown(f"**Score:** {score}/100")
            options = db.APPLICATION_STATUSES
            current_idx = options.index(app_status) if app_status in options else 0
            new_status = st.selectbox(
                "Update status",
                options,
                index=current_idx,
                key=f"status_{j['job_key']}",
            )
            notes_key = f"notes_{j['job_key']}"
            notes = st.text_input("Notes", value=j.get("notes", ""), key=notes_key, label_visibility="collapsed", placeholder="Notes…")

            if st.button("Save", key=f"save_{j['job_key']}", use_container_width=True):
                db.set_status(j["job_key"], new_status, notes=notes)
                st.success("Saved!")
                st.rerun()

            if new_status == "Applied" and db.is_already_applied(j["job_key"]):
                st.error("⛔ Already marked Applied — duplicate submission prevented.")
