"""
pages/4_Settings.py — Source configuration, diagnostics, and app settings.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import db
from app_paths import ensure_source_config

st.set_page_config(page_title="Settings · Job Hunter Agent", page_icon="⚙️", layout="wide")
from app_security import require_app_auth

require_app_auth()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.diag-ok   { border-left: 4px solid #22c55e; padding: 6px 12px; margin: 4px 0; border-radius: 0 6px 6px 0; background:#052e16; }
.diag-fail { border-left: 4px solid #ef4444; padding: 6px 12px; margin: 4px 0; border-radius: 0 6px 6px 0; background:#1c0505; }
</style>
""", unsafe_allow_html=True)

db.init_db()

BASE = Path(__file__).parent.parent
CONFIG = ensure_source_config()

st.markdown("# ⚙️ Settings")
st.caption("Configure job sources, view diagnostics, manage alerts, and review system status.")

# ---------------------------------------------------------------------------
# Sources editor
# ---------------------------------------------------------------------------
st.markdown("## 🌐 Job Sources")

tab1, tab2, tab3 = st.tabs(["Greenhouse Tokens", "Lever Sites", "Other Sources"])

with tab1:
    st.markdown("""
    **How to find Greenhouse board tokens:**
    - Company careers URL: `https://boards.greenhouse.io/YOUR-TOKEN`
    - API test: `https://boards-api.greenhouse.io/v1/boards/YOUR-TOKEN/jobs`
    - No authentication required for public boards.
    """)

    source_error = ""
    try:
        sources = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
        if not isinstance(sources, dict):
            raise ValueError("The JSON root must be an object.")
        for key in ("greenhouse", "lever"):
            values = sources.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError(f"'{key}' must be a list of strings.")
        if not isinstance(sources.get("remoteok", False), bool):
            raise ValueError("'remoteok' must be true or false.")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        source_error = f"Cannot read {CONFIG.name}: {exc}. Saving valid settings below will replace it."
        sources = {}
    if source_error:
        st.error(source_error)
    gh_current = "\n".join(t for t in sources.get("greenhouse", []) if not t.startswith("_"))
    gh_new = st.text_area(
        "Greenhouse board tokens (one per line):",
        value=gh_current,
        height=200,
        help="Add company board tokens. Verify each one returns jobs at boards-api.greenhouse.io/v1/boards/TOKEN/jobs",
    )

    st.markdown("""
    **Verified working tokens** (as of last test run):
    `airbnb` · `stripe` · `twilio` · `gitlab` · `figma` · `vercel` · `datadog` · 
    `cloudflare` · `reddit` · `discord` · `brex` · `gusto` · `asana` · 
    `pagerduty` · `mixpanel` · `netlify` · `airtable`
    """)

with tab2:
    st.markdown("""
    **How to find Lever site slugs:**
    - Company job page: `https://jobs.lever.co/YOUR-SLUG`
    - API test: `https://api.lever.co/v0/postings/YOUR-SLUG`
    - No authentication required for public postings.
    """)

    lv_current = "\n".join(s for s in sources.get("lever", []) if not s.startswith("_"))
    lv_new = st.text_area(
        "Lever site slugs (one per line):",
        value=lv_current,
        height=150,
        help="Add Lever company slugs. Verify at api.lever.co/v0/postings/SLUG",
    )

    st.markdown("**Verified working slugs:** `cred` · `fly`")

with tab3:
    ro_enabled = bool(sources.get("remoteok", False))
    ro_new = st.checkbox(
        "Enable RemoteOK (public JSON feed — may be blocked by some networks)",
        value=ro_enabled,
    )
    st.caption("RemoteOK: `https://remoteok.com/api` — no auth required. "
               "Rate-limited to 1 request per scan with a 2s delay.")

# Save sources
if st.button("💾 Save Sources", type="primary"):
    new_sources = {
        "greenhouse": [t.strip() for t in gh_new.splitlines() if t.strip() and not t.strip().startswith("#")],
        "lever": [s.strip() for s in lv_new.splitlines() if s.strip() and not s.strip().startswith("#")],
        "remoteok": ro_new,
        "_notes": sources.get("_notes", {}),
    }
    CONFIG.write_text(json.dumps(new_sources, indent=2), encoding="utf-8")
    st.success(f"✅ Saved {len(new_sources['greenhouse'])} Greenhouse + {len(new_sources['lever'])} Lever sources.")
    st.rerun()

# ---------------------------------------------------------------------------
# Live source tester
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 🧪 Live Source Tester")
st.caption("Test a single source before adding it to your list.")

test_source = st.text_input("Enter a Greenhouse token or Lever slug to test:")
test_type = st.radio("Source type:", ["Greenhouse", "Lever"], horizontal=True)

if st.button("🔬 Test Source", disabled=not test_source.strip()):
    import time
    import requests

    slug = test_source.strip().lower()
    if test_type == "Greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    else:
        url = f"https://api.lever.co/v0/postings/{slug}"

    try:
        t0 = time.time()
        r = requests.get(url, timeout=15, headers={"User-Agent": "JobHunterPersonal/2.0"})
        elapsed = round(time.time() - t0, 1)
        r.raise_for_status()
        data = r.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        count = len(jobs) if isinstance(jobs, list) else len(data.get("jobs", []))
        st.markdown(
            f'<div class="diag-ok">✅ <strong>{slug}</strong> — {count} jobs found ({elapsed}s) · HTTP {r.status_code}</div>',
            unsafe_allow_html=True,
        )
    except requests.HTTPError as e:
        hint = {
            404: "Board/slug not found. Check the identifier.",
            403: "Access forbidden (private board).",
            429: "Rate limited. Wait before retrying.",
        }.get(e.response.status_code if e.response else 0, "Unexpected HTTP error.")
        st.markdown(
            f'<div class="diag-fail">❌ <strong>{slug}</strong> — HTTP {e.response.status_code if e.response else "?"}: {hint}</div>',
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.markdown(
            f'<div class="diag-fail">❌ <strong>{slug}</strong> — {e}</div>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# Alerts management
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 🔔 Active Alerts")

alerts = db.get_active_alerts()
if not alerts:
    st.success("No active alerts.")
else:
    for a in alerts:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{a['alert_type']}** · {a['message']}")
            c1.caption(f"Created: {a['created_at'][:16]} · Job: {a['job_key']}")
            if c2.button("Dismiss", key=f"dismiss_{a['id']}"):
                db.dismiss_alert(a["id"])
                st.rerun()

# ---------------------------------------------------------------------------
# DB stats
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 📊 Database Stats")
all_j = db.get_all_jobs()
all_a = db.get_all_applications()
statuses = {}
for app in all_a:
    statuses[app["status"]] = statuses.get(app["status"], 0) + 1

dc1, dc2, dc3, dc4 = st.columns(4)
dc1.metric("Total Jobs", len(all_j))
dc2.metric("Applications Tracked", len(all_a))
dc3.metric("Sources Configured",
           len([t for t in sources.get("greenhouse",[]) if not t.startswith("_")]) +
           len([s for s in sources.get("lever",[]) if not s.startswith("_")]))
dc4.metric("Applied", statuses.get("Applied", 0))

st.markdown("**Status breakdown:**")
for status, count in sorted(statuses.items()):
    st.caption(f"  {status}: {count}")

# Audit log
with st.expander("📋 Full audit log (last 50)"):
    log = db.get_audit_log(limit=50)
    for e in log:
        st.caption(f"`{e['ts'][:16]}` · **{e['event']}** · {e['job_key']} · {e['detail']}")

st.divider()
st.markdown("## ℹ️ Feature Status")
st.markdown("""
| Feature | Status | Notes |
|---------|--------|-------|
| Greenhouse board scanning | ✅ Functional | 17 verified tokens configured |
| Lever board scanning | ✅ Functional | `cred` verified; add more slugs |
| RemoteOK scanning | ⚠️ Network-dependent | Disabled by default; enable in settings |
| Resume matching | ✅ Functional | Upload PDFs on Dashboard |
| Job deduplication | ✅ Functional | By job_key (source:company:id) |
| Resume draft generation | ✅ Functional | Template-based, no LLM |
| Cover letter generation | ✅ Functional | Template with real resume data |
| Daily application queue | ✅ Functional | Up to 50 jobs/day |
| Duplicate submission guard | ✅ Functional | Blocks re-applying same job |
| Visa sponsorship detection | ✅ Functional | Keyword-based from JD text |
| Auto-submission | ❌ Not implemented | Only authorised platforms; user opens page |
| LLM-powered resume rewrite | ❌ Not implemented | Requires API key (future feature) |
| Email/Slack alerts | ❌ Not implemented | Future feature |
| Scheduled scans | ❌ Not implemented | Run manually or via Task Scheduler |
| LinkedIn/Indeed integration | ❌ Intentionally excluded | Violates their terms of service |
""")
