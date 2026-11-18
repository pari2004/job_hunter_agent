"""
pages/3_Queue.py — Daily application queue management.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from datetime import datetime, timezone

import db
import queue_manager as qm

st.set_page_config(page_title="Daily Queue · Job Hunter Agent", page_icon="📬", layout="wide")
from app_security import require_app_auth

require_app_auth()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.score-high { background:#16a34a; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-mid  { background:#d97706; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-low  { background:#475569; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.badge { border-radius:6px; padding:2px 8px; font-size:0.78rem; font-weight:600; }
.badge-green  { background:#15803d; color:#fff; }
.badge-orange { background:#b45309; color:#fff; }
.badge-blue   { background:#1d4ed8; color:#fff; }
.badge-slate  { background:#334155; color:#e2e8f0; }
</style>
""", unsafe_allow_html=True)

db.init_db()

st.markdown("# 📬 Daily Application Queue")
st.caption(
    "Target: up to 50 relevant applications per day. "
    "**Applications are never submitted automatically.** "
    "Open the official page, review your prepared pack, then mark as Applied."
)

today = qm.today_str()
st.markdown(f"**Queue date:** {today}")

# ---------------------------------------------------------------------------
# Build / refresh queue
# ---------------------------------------------------------------------------
col_build, col_settings = st.columns([1, 2])
with col_settings:
    max_q = st.slider("Max queue size", 10, 50, 50)
    min_s = st.slider("Min score for queue", 10, 80, 30)

with col_build:
    if st.button("🔄 Build / Refresh Queue", type="primary", use_container_width=True):
        result = qm.build_queue(today, max_size=max_q, min_score=min_s)
        st.success(result["message"])
        st.caption(
            f"Added: {result['added']} · "
            f"Skipped (applied): {result['skipped_applied']} · "
            f"Skipped (low score): {result['skipped_low_score']}"
        )

# ---------------------------------------------------------------------------
# Today's queue
# ---------------------------------------------------------------------------
stats = qm.queue_stats(today)
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total in Queue", stats["total"])
s2.metric("Applied", stats["applied"])
s3.metric("Ready to Apply", stats["ready"])
s4.metric("Shortlisted", stats["shortlisted"])

st.divider()

queue = qm.get_todays_queue()

if not queue:
    st.warning(
        "Queue is empty. Click **Build / Refresh Queue** above after running a scan. "
        "Jobs with score ≥ 30 and status Discovered/Shortlisted/Ready will be added."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Queue cards
# ---------------------------------------------------------------------------
for entry in queue:
    score = int(entry.get("score") or 0)
    score_class = "score-high" if score >= 60 else "score-mid" if score >= 40 else "score-low"
    app_status = entry.get("app_status", "Discovered")
    job_key = entry["job_key"]
    loc = entry.get("location") or "Location not listed"

    with st.container(border=True):
        c1, c2 = st.columns([5, 1])

        with c1:
            st.markdown(
                f"**{entry['title']}** &nbsp;·&nbsp; {entry['company'].title()} &nbsp;"
                f'<span class="{score_class}">{score}/100</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"📍 {loc} &nbsp;·&nbsp; Status: **{app_status}**")
            if entry.get("matched_resume"):
                st.caption(f"📄 Resume: {entry['matched_resume']}")
            if entry.get("url"):
                st.markdown(f"[🔗 Open official application page]({entry['url']})")

        with c2:
            # Open + mark ready
            if app_status in ("Discovered", "Shortlisted") and entry.get("url"):
                if st.button("📂 Open & Mark Ready", key=f"open_{job_key}", use_container_width=True):
                    qm.mark_opened(job_key)
                    import webbrowser
                    # Can't open browser from server-side; show link
                    st.success("Status set to Ready to apply. Use the link above to open the application.")
                    st.rerun()

            # Mark applied (requires user confirmation)
            if app_status in ("Ready to apply", "Shortlisted", "Discovered"):
                if not db.is_already_applied(job_key):
                    notes = st.text_input("Confirmation note", key=f"cnote_{job_key}",
                                          placeholder="e.g. Applied via official site", label_visibility="collapsed")
                    if st.button("✅ Mark Applied", key=f"apply_{job_key}", use_container_width=True):
                        if notes.strip():
                            qm.mark_submitted(job_key, notes)
                            st.success("✅ Marked as Applied. Confirmation logged.")
                            st.rerun()
                        else:
                            st.warning("Add a confirmation note before marking as applied.")
                else:
                    st.success("✅ Already Applied")

            if app_status == "Applied":
                st.success("✅ Applied")

st.divider()
st.info(
    "**Submission policy:** This tool never auto-submits applications. "
    "It prepares your materials and opens the official employer page. "
    "You confirm submission manually. Duplicate applications are blocked automatically."
)

# ---------------------------------------------------------------------------
# Audit log snippet
# ---------------------------------------------------------------------------
with st.expander("📋 Recent audit log"):
    log = db.get_audit_log(limit=30)
    for entry in log:
        st.caption(f"`{entry['ts'][:16]}` · **{entry['event']}** · {entry['job_key']} · {entry['detail']}")
