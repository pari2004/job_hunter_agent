"""
app.py — Job Hunter Agent: Main Dashboard (Streamlit entry point).

Multi-page app. This page is the Home / Scan Control / Dashboard.
Other pages live in pages/.

Run: streamlit run app.py

Presentation helpers are kept in ui_helpers.py so multipage screens can
reuse them without importing and executing this dashboard module.
"""

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))

import db
import scorer
from app_paths import ensure_source_config
from app_security import require_app_auth
from queue_manager import build_queue, today_str
from ui_helpers import fmt_date as _fmt_date, render_job_badges as _render_badges

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Job Hunter Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)
require_app_auth()

# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

[data-testid="metric-container"] {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    color: #f1f5f9;
}
[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; color: #38bdf8; }
[data-testid="stMetricLabel"] { color: #94a3b8; font-size: 0.8rem; }

.score-high { background:#16a34a; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-mid  { background:#d97706; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }
.score-low  { background:#475569; color:#fff; border-radius:6px; padding:2px 8px; font-weight:600; }

.badge { border-radius:6px; padding:2px 8px; font-size:0.78rem; font-weight:600; }
.badge-blue   { background:#1d4ed8; color:#fff; }
.badge-green  { background:#15803d; color:#fff; }
.badge-orange { background:#b45309; color:#fff; }
.badge-red    { background:#b91c1c; color:#fff; }
.badge-purple { background:#7e22ce; color:#fff; }
.badge-slate  { background:#334155; color:#e2e8f0; }

.diag-ok   { border-left: 4px solid #22c55e; padding: 6px 12px; margin: 4px 0;
             border-radius: 0 6px 6px 0; background:#052e16; }
.diag-fail { border-left: 4px solid #ef4444; padding: 6px 12px; margin: 4px 0;
             border-radius: 0 6px 6px 0; background:#1c0505; }

#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------
db.init_db()

BASE = Path(__file__).parent
CONFIG = ensure_source_config()

# ===========================================================================
# HELPER FUNCTIONS — all defined here, before any call site
# ===========================================================================

def _http_hint(error_str: str) -> str:
    """Return a human-readable hint for common HTTP errors."""
    if "404" in error_str:
        return "→ Board token not found. Verify the slug."
    if "403" in error_str:
        return "→ Access forbidden. Board may be private."
    if "429" in error_str:
        return "→ Rate limited. Wait before retrying."
    if "timeout" in error_str.lower() or "timed out" in error_str.lower():
        return "→ Request timed out. Check network."
    if "connection" in error_str.lower():
        return "→ Connection error. Check internet."
    return ""


def _render_diagnostics(rows: list[dict]):
    """Render per-source diagnostic rows."""
    st.markdown("#### 📊 Per-Source Diagnostics")
    for r in rows:
        css = "diag-ok" if r["status"] == "ok" else "diag-fail"
        icon = "✅" if r["status"] == "ok" else "❌"
        detail = f" — {r['detail']}" if r["detail"] else ""
        match_text = (
            f"{r['matching']} matching"
            if r["matching"] is not None else "matching unavailable (upload a resume)"
        )
        st.markdown(
            f'<div class="{css}">'
            f'{icon} <strong>{r["source"]}</strong> — {r["request_status"]}; '
            f'<strong>{r["jobs"]}</strong> fetched, {match_text}, '
            f'{r["duplicates"]} duplicate(s) ({r["elapsed"]}s){detail}'
            f'</div>',
            unsafe_allow_html=True,
        )


def _run_scan(gh_tokens: list, lv_sites: list, remoteok_enabled: bool):
    """Execute a full scan across all configured sources."""
    from adapters import greenhouse as gh_adapter
    from adapters import lever as lv_adapter

    resumes = st.session_state.get("resumes", {})
    total_sources = len(gh_tokens) + len(lv_sites) + (1 if remoteok_enabled else 0)
    progress = st.progress(0, text="Starting scan…")
    diag_rows: list[dict] = []
    all_found: list[dict] = []
    done = 0

    # ── Greenhouse ──────────────────────────────────────────────────────────
    for token in gh_tokens:
        progress.progress(done / max(total_sources, 1), text=f"Greenhouse: {token}…")
        t0 = time.time()
        try:
            jobs = gh_adapter.fetch(token)
            elapsed = round(time.time() - t0, 1)
            all_found.extend(jobs)
            diag_rows.append({"status": "ok", "source": f"Greenhouse/{token}",
                               "jobs": len(jobs), "elapsed": elapsed, "detail": "",
                               "request_status": "HTTP 200", "_job_keys": [j["job_key"] for j in jobs]})
        except Exception as exc:
            elapsed = round(time.time() - t0, 1)
            code = re.search(r"\b([45]\d\d)\b", str(exc))
            diag_rows.append({"status": "fail", "source": f"Greenhouse/{token}",
                               "jobs": 0, "elapsed": elapsed,
                               "detail": f"{exc} {_http_hint(str(exc))}",
                               "request_status": f"HTTP {code.group(1)}" if code else "Request failed",
                               "_job_keys": []})
        done += 1

    # ── Lever ────────────────────────────────────────────────────────────────
    for site in lv_sites:
        progress.progress(done / max(total_sources, 1), text=f"Lever: {site}…")
        t0 = time.time()
        try:
            jobs = lv_adapter.fetch(site)
            elapsed = round(time.time() - t0, 1)
            all_found.extend(jobs)
            diag_rows.append({"status": "ok", "source": f"Lever/{site}",
                               "jobs": len(jobs), "elapsed": elapsed, "detail": "",
                               "request_status": "HTTP 200", "_job_keys": [j["job_key"] for j in jobs]})
        except Exception as exc:
            elapsed = round(time.time() - t0, 1)
            code = re.search(r"\b([45]\d\d)\b", str(exc))
            diag_rows.append({"status": "fail", "source": f"Lever/{site}",
                               "jobs": 0, "elapsed": elapsed,
                               "detail": f"{exc} {_http_hint(str(exc))}",
                               "request_status": f"HTTP {code.group(1)}" if code else "Request failed",
                               "_job_keys": []})
        done += 1

    # ── RemoteOK ─────────────────────────────────────────────────────────────
    if remoteok_enabled:
        from adapters import remoteok as ro_adapter
        progress.progress(done / max(total_sources, 1), text="RemoteOK…")
        t0 = time.time()
        try:
            jobs = ro_adapter.fetch()
            elapsed = round(time.time() - t0, 1)
            all_found.extend(jobs)
            diag_rows.append({"status": "ok", "source": "RemoteOK",
                               "jobs": len(jobs), "elapsed": elapsed, "detail": "",
                               "request_status": "HTTP 200", "_job_keys": [j["job_key"] for j in jobs]})
        except Exception as exc:
            elapsed = round(time.time() - t0, 1)
            code = re.search(r"\b([45]\d\d)\b", str(exc))
            diag_rows.append({"status": "fail", "source": "RemoteOK",
                               "jobs": 0, "elapsed": elapsed, "detail": str(exc),
                               "request_status": f"HTTP {code.group(1)}" if code else "Request failed",
                               "_job_keys": []})
        done += 1

    # ── Dedup & save ─────────────────────────────────────────────────────────
    progress.progress(1.0, text="Saving to database…")
    existing_keys = {j["job_key"] for j in db.get_all_jobs()}
    seen_keys: set[str] = set()
    deduped: list[dict] = []
    for j in all_found:
        if j["job_key"] not in seen_keys:
            seen_keys.add(j["job_key"])
            deduped.append(j)
    new_count = db.upsert_jobs(deduped) if deduped else 0

    # ── Score + experience detection ──────────────────────────────────────────
    all_db_jobs = db.get_all_jobs()
    if resumes:
        progress.progress(1.0, text="Scoring against resumes…")
        for job in all_db_jobs:
            best_score, best_name = scorer.best_resume_match(job, resumes)
            db.update_score(job["job_key"], best_score, best_name)
            if best_score >= 70 and job["job_key"] not in existing_keys:
                db.add_alert(job["job_key"], "HIGH MATCH",
                             f"{job['title']} @ {job['company']} scored {best_score}/100 "
                             f"(matched: {best_name})")
    # Backfill required_experience for all jobs (cheap — pure regex, no network)
    db.backfill_experience_levels()

    scan_seen = set(existing_keys)
    jobs_by_key = {job["job_key"]: job for job in all_found}
    for row in diag_rows:
        row["duplicates"] = 0
        row["matching"] = 0 if resumes else None
        for key in row.pop("_job_keys"):
            if key in scan_seen:
                row["duplicates"] += 1
            else:
                scan_seen.add(key)
            if resumes and key in jobs_by_key:
                score, _ = scorer.best_resume_match(jobs_by_key[key], resumes)
                if score >= 30:
                    row["matching"] += 1

    progress.empty()
    db.audit("SCAN:COMPLETE", detail=f"found={len(all_found)} deduped={len(deduped)}")
    qr = build_queue() if resumes else {"added": 0}

    ok_count = sum(1 for r in diag_rows if r["status"] == "ok")
    fail_count = len(diag_rows) - ok_count
    total_fetched = sum(r["jobs"] for r in diag_rows)

    if total_sources == 0:
        st.error("Scan not run: no job sources are configured. Add a public Greenhouse or Lever board in Settings.")
    elif total_fetched == 0 and fail_count:
        st.error(f"No jobs fetched: {fail_count} of {total_sources} source requests failed.")
    elif total_fetched == 0:
        st.warning("No jobs fetched: configured sources responded but returned no current postings.")
    elif new_count == 0:
        st.info(f"Scan fetched {total_fetched} postings, but all were already in the database. No new jobs were found.")
    else:
        st.success(
            f"Scan found {total_fetched} postings, including {new_count} new jobs "
            f"from {ok_count} responding sources. {qr['added']} jobs added to today's queue."
        )
    if fail_count:
        st.warning(f"⚠️ {fail_count} source(s) failed — see diagnostics below.")
    if total_fetched and not resumes:
        st.info("Resume matching was not run. Upload your resume PDFs to score jobs and build a relevant queue.")
    _render_diagnostics(diag_rows)


def load_sources() -> dict:
    defaults = {"greenhouse": [], "lever": [], "remoteok": False}
    if not CONFIG.exists():
        return {
            **defaults,
            "_error": f"Source configuration is missing: {CONFIG.name}. Save valid sources in Settings.",
        }
    try:
        sources = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(sources, dict):
            raise ValueError("The JSON root must be an object.")
        for key in ("greenhouse", "lever"):
            values = sources.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError(f"'{key}' must be a list of strings.")
        if not isinstance(sources.get("remoteok", False), bool):
            raise ValueError("'remoteok' must be true or false.")
        return {**defaults, **sources, "_error": ""}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            **defaults,
            "_error": f"Cannot read {CONFIG.name}: {exc}. Correct it in Settings before scanning.",
        }


def read_resume_pdf(uploaded_file) -> str:
    reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ===========================================================================
# SIDEBAR
# ===========================================================================
with st.sidebar:
    st.markdown("## Job Hunter Agent")
    st.caption("Fresh-job discovery · Resume matching · Application queue")
    st.divider()

    st.markdown("### 📄 Resume Profiles")
    uploaded = st.file_uploader(
        "Upload resume PDFs (up to 4)",
        type=["pdf"],
        accept_multiple_files=True,
        key="resume_uploader",
    )
    st.caption("Upload your SDE, Java, Python, and AI resumes. All claims must be accurate.")

    if "resumes" not in st.session_state:
        st.session_state.resumes = {}

    if uploaded:
        for f in uploaded:
            if f.name not in st.session_state.resumes:
                try:
                    st.session_state.resumes[f.name] = read_resume_pdf(f)
                except Exception as e:
                    st.warning(f"⚠️ Could not read {f.name}: {e}")
        uploaded_names = {f.name for f in uploaded}
        st.session_state.resumes = {
            k: v for k, v in st.session_state.resumes.items() if k in uploaded_names
        }

    if st.session_state.resumes:
        for name in st.session_state.resumes:
            st.success(f"✅ {name}")
    else:
        st.info("No resumes loaded. Upload PDFs above.")

    st.divider()
    st.markdown("### 🗺 Navigation")
    st.page_link("app.py",               label="🏠 Dashboard & Scan")
    st.page_link("pages/1_Pipeline.py",   label="📋 Job Pipeline")
    st.page_link("pages/2_Drafts.py",     label="📝 Resume Drafts")
    st.page_link("pages/3_Queue.py",      label="📬 Daily Queue")
    st.page_link("pages/4_Settings.py",   label="⚙️ Settings")
    st.page_link("pages/5_Gmail.py",      label="📧 Gmail Outreach")

# ===========================================================================
# MAIN CONTENT
# ===========================================================================
st.markdown("# 🎯 Job Hunter Agent")
st.caption(
    "Scans public Greenhouse and Lever career-board APIs · "
    "Scores jobs against your resumes · "
    "Tracks applications · Never submits without your review."
)

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------
all_jobs = db.get_jobs_with_status()
total     = len(all_jobs)
high_match = sum(1 for j in all_jobs if int(j.get("score") or 0) >= 60)
applied    = sum(1 for j in all_jobs if j.get("app_status") == "Applied")
interview  = sum(1 for j in all_jobs if j.get("app_status") == "Interview")
india_jobs = sum(1 for j in all_jobs if any(
    x in (j.get("location") or "").lower()
    for x in ["bengaluru", "bangalore", "mysuru", "mysore", "mumbai", "pune", "india"]
))

alerts = db.get_active_alerts()
if alerts:
    for a in alerts[:3]:
        st.warning(f"🔔 **{a['alert_type']}**: {a['message']}", icon="🔔")
    if len(alerts) > 3:
        st.caption(f"… and {len(alerts) - 3} more alerts. See Settings page.")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Jobs",      total,      help="All jobs in database")
m2.metric("High Match (≥60)", high_match, help="Score ≥ 60 out of 100")
m3.metric("India Postings",  india_jobs, help="Jobs in India")
m4.metric("Applied",         applied,    help="Status = Applied")
m5.metric("Interviews",      interview,  help="Status = Interview")

st.divider()

# ---------------------------------------------------------------------------
# Scan control
# ---------------------------------------------------------------------------
st.markdown("## 🔎 Scan Job Boards")

sources        = load_sources()
gh_tokens      = [t for t in sources.get("greenhouse", []) if t and not t.startswith("_")]
lv_sites       = [s for s in sources.get("lever", [])       if s and not s.startswith("_")]
remoteok_enabled = bool(sources.get("remoteok", False))

if sources.get("_error"):
    st.error(sources["_error"])

col_info, col_btn = st.columns([3, 1])
with col_info:
    st.info(
        f"**{len(gh_tokens)} Greenhouse** boards · "
        f"**{len(lv_sites)} Lever** sites · "
        f"**RemoteOK**: {'enabled' if remoteok_enabled else 'disabled'}\n\n"
        "Uses only official public APIs. No CAPTCHA bypass, no scraping, no login automation."
    )
with col_btn:
    do_scan = st.button(
        "🔎 Run Scan",
        type="primary",
        use_container_width=True,
        disabled=bool(sources.get("_error")),
    )

if do_scan:
    _run_scan(gh_tokens, lv_sites, remoteok_enabled)

# ---------------------------------------------------------------------------
# Top matches preview
# ---------------------------------------------------------------------------
if all_jobs:
    st.divider()
    st.markdown("## 🏆 Top Matches")

    top = [j for j in all_jobs if int(j.get("score") or 0) >= 50][:10]
    if not top:
        top = sorted(all_jobs, key=lambda j: int(j.get("score") or 0), reverse=True)[:5]

    for j in top:
        score      = int(j.get("score") or 0)
        score_class = "score-high" if score >= 60 else "score-mid" if score >= 40 else "score-low"
        loc        = j.get("location") or "Location not listed"
        posted     = j.get("posted_at") or ""
        app_status = j.get("app_status", "Discovered")

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f"**{j['title']}** &nbsp;·&nbsp; {j['company'].title()} &nbsp;"
                    f'<span class="{score_class}">{score}/100</span>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"📍 {loc} &nbsp;·&nbsp; Source: {j['source']} &nbsp;·&nbsp; "
                    f"Posted: {_fmt_date(posted)}"
                )
                _render_badges(j)
                if j.get("url"):
                    st.markdown(f"[🔗 Open application page]({j['url']})")
            with c2:
                st.markdown(f"**Status:** {app_status}")
                if j.get("matched_resume"):
                    st.caption(f"Resume: {j['matched_resume']}")
else:
    st.info(
        "No jobs in the database yet.\n\n"
        "**To get started:**\n"
        "1. Upload your resume PDFs in the sidebar\n"
        "2. Click **Run Scan** above\n"
        "3. Browse results in the **Job Pipeline** page"
    )
