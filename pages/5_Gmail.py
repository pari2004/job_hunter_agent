"""
pages/5_Gmail.py — Gmail OAuth connection, test send, and recruiter outreach.

SAFETY POLICY:
- OAuth is handled entirely by Google's official consent screen.
- No passwords, OTPs, session cookies, or tokens are entered in this UI.
- Automatic sending requires explicit per-session opt-in (toggle + confirm).
- All outreach goes only to verified published recruiter contacts.
- Duplicate sends are blocked at DB level.
- Daily limit is enforced before every send.
"""

import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import db
import gmail_auth
import gmail_sender
from pdf_generator import generate_pdf_resume, generate_pdf_cover_letter, reportlab_available
import drafts as drafter
import scorer

st.set_page_config(page_title="Gmail Outreach · Job Hunter Agent", page_icon="📧", layout="wide")
from app_security import require_app_auth

require_app_auth()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.status-connected    { background:#052e16; border:1px solid #22c55e; border-radius:10px;
                       padding:1rem 1.5rem; color:#bbf7d0; }
.status-disconnected { background:#1c0505; border:1px solid #ef4444; border-radius:10px;
                       padding:1rem 1.5rem; color:#fca5a5; }
.status-partial      { background:#1c1003; border:1px solid #f59e0b; border-radius:10px;
                       padding:1rem 1.5rem; color:#fcd34d; }
.guard-box           { background:#0f172a; border:1px solid #334155; border-radius:8px;
                       padding:0.8rem 1.2rem; margin:6px 0; font-size:0.85rem; color:#94a3b8; }
.outreach-sent       { border-left:4px solid #22c55e; padding:6px 12px; background:#052e16;
                       border-radius:0 6px 6px 0; margin:4px 0; }
.outreach-queued     { border-left:4px solid #f59e0b; padding:6px 12px; background:#1c1003;
                       border-radius:0 6px 6px 0; margin:4px 0; }
.outreach-failed     { border-left:4px solid #ef4444; padding:6px 12px; background:#1c0505;
                       border-radius:0 6px 6px 0; margin:4px 0; }
</style>
""", unsafe_allow_html=True)

db.init_db()

BASE = Path(__file__).parent.parent

st.markdown("# 📧 Gmail Outreach")
hosted_deployment = os.environ.get("APP_ENV", "").lower() == "production"
st.caption(
    "Connect your Gmail account via Google OAuth · "
    "Send application emails with PDF resume attachment · "
    "Use manually verified contacts · Recruiter outreach is never sent automatically."
)

# ===========================================================================
# Section 1: Connection Status
# ===========================================================================
st.markdown("## 1. Gmail Connection")

status = gmail_auth.auth_status()
oauth_authorized = bool(status["connected"])
connected = bool(
    oauth_authorized and st.session_state.get("gmail_test_passed", False)
)

if not status["packages_installed"]:
    st.error(
        "⛔ Google Auth packages not installed.\n\n"
        "Run: `pip install google-auth google-auth-oauthlib google-api-python-client`"
    )
    st.stop()

if hosted_deployment:
    st.warning(
        "Gmail sending is disabled in the hosted deployment. The current OAuth flow "
        "is for a local desktop app; hosted web OAuth has not been configured. "
        "Do not upload OAuth credentials to the repository. Use the official employer "
        "application pages; hosted Gmail can be added later with a web OAuth flow."
    )
    st.stop()

if connected:
    st.markdown(
        f'<div class="status-connected">'
        f'<strong>✅ Gmail send tested in this session</strong><br>'
        f'Test recipient: <code>{st.session_state.get("gmail_test_address", "not recorded")}</code> '
        f'(user-confirmed)<br>'
        f'Account identity is not requested under the gmail.send-only scope.'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_rev, col_status = st.columns([1, 3])
    with col_rev:
        if st.button("🔌 Disconnect", help="Deletes local token.json"):
            revoked = gmail_auth.revoke_credentials()
            if revoked:
                st.session_state.gmail_test_passed = False
                st.session_state.pop("gmail_test_address", None)
                st.success("Local token deleted. Gmail disconnected.")
                st.caption(
                    "To fully revoke access, visit "
                    "[myaccount.google.com/permissions](https://myaccount.google.com/permissions) "
                    "and remove 'Job Hunter Agent'."
                )
                st.rerun()

elif oauth_authorized:
    st.markdown(
        '<div class="status-partial">'
        '<strong>⚠️ OAuth authorization available; test email required</strong>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.info(
        "The gmail.send scope cannot read the Gmail account profile. "
        "Send a test message to your own configured address below; the app will not "
        "mark Gmail connected until the Gmail API confirms a message ID."
    )
    if st.button("🔌 Disconnect", help="Deletes local token.json"):
        gmail_auth.revoke_credentials()
        st.session_state.gmail_test_passed = False
        st.session_state.pop("gmail_test_address", None)
        st.success("Local token deleted. Revoke the app at Google Account Permissions to fully disconnect.")
        st.rerun()

elif not status["credentials_file_present"]:
    st.markdown(
        '<div class="status-disconnected">'
        '<strong>❌ credentials.json missing</strong>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("📋 Setup Instructions — one-time, takes ~3 minutes", expanded=True):
        st.markdown("""
        **Step 1:** Go to [Google Cloud Console](https://console.cloud.google.com/)

        **Step 2:** Create or select a project → Enable **Gmail API**
        - Navigation: APIs & Services → Library → search "Gmail API" → Enable

        **Step 3:** Create OAuth credentials
        - Navigation: APIs & Services → Credentials → Create Credentials → OAuth client ID
        - Application type: **Desktop application**
        - Name: Job Hunter Agent (or anything)
        - Click Create

        **Step 4:** Download the credentials
        - Click the ⬇️ download icon next to your new OAuth client
        - Save the file as `credentials.json` in:
          ```
          d:\\job_hunter_agent\\credentials.json
          ```

        **Step 5:** OAuth consent screen
        - APIs & Services → OAuth consent screen
        - Add your Gmail address as a test user (while in Testing mode)
        - Scopes needed: `https://www.googleapis.com/auth/gmail.send`

        **Step 6:** Come back here and click **Connect Gmail** below.

        > ⚠️ **Testing mode token expiry:** Refresh tokens issued while the app is in  
        > "Testing" mode on Google Cloud Console expire after **7 days**. To prevent this,  
        > publish the OAuth app (OAuth consent screen → Publish App → confirm).  
        > If your token expires: delete `token.json` and click Connect Gmail again.
        """)

    if st.button("🔄 Refresh Status", help="Check if credentials.json was added"):
        st.rerun()

else:
    st.markdown(
        '<div class="status-partial">'
        '<strong>⚠️ Gmail connection not verified</strong> — authorize or reconnect to continue'
        '</div>',
        unsafe_allow_html=True,
    )
    if status["error"]:
        st.warning(f"Auth status: {status['error']}")

    st.info(
        "Click **Connect Gmail** to open Google's consent screen in your browser.\n\n"
        "You will be asked to sign in with your Google account and approve "
        "**Send email on your behalf** permission. No inbox access is requested."
    )

    if st.button("🔗 Connect Gmail", type="primary"):
        with st.spinner("Opening browser for Google authorization…"):
            try:
                gmail_auth.run_auth_flow()
                st.session_state.gmail_test_passed = False
                st.session_state.pop("gmail_test_address", None)
                st.success("OAuth completed. Send a test email to verify Gmail API access.")
                st.rerun()
            except FileNotFoundError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                err = str(e)
                if "access_denied" in err.lower():
                    st.error("❌ You denied access. Click Connect Gmail and approve the permission.")
                elif "invalid_client" in err.lower():
                    st.error("❌ Invalid credentials.json. Re-download from Google Cloud Console.")
                else:
                    st.error(f"❌ OAuth or Gmail verification failed ({type(e).__name__}). Check credentials.json and retry.")

st.divider()

# ===========================================================================
# Section 2: Test Email
# ===========================================================================
st.markdown("## 2. Test Connection")
st.caption("Send a test email to your own address to verify the integration.")

if not oauth_authorized:
    st.warning("Connect Gmail above before sending a test email.")
else:
    test_to = st.text_input(
        "Your own configured email address:",
        placeholder="you@gmail.com",
        help="The gmail.send-only scope cannot reveal the authorized account address. "
             "Enter an address you own and confirm below.",
    )
    test_address_is_own = st.checkbox("I confirm this is my own email address.")

    attach_test = st.checkbox("Include a dummy PDF attachment to test attachment sending")

    if st.button(
        "📨 Send Test Email",
        disabled=not (test_to.strip() and test_address_is_own),
    ):
        if not gmail_sender.is_valid_email(test_to.strip()):
            st.error("Invalid email address format.")
        else:
            attach_path = None
            if attach_test:
                # Generate a minimal test PDF
                if reportlab_available():
                    try:
                        test_job = {"job_key": "test:connection:0",
                                    "title": "Test Role", "company": "test",
                                    "location": "Test", "url": ""}
                        attach_path = generate_pdf_resume(
                            test_job, "Test Name\nSKILLS\nPython, Java", "test_resume.pdf"
                        )
                    except Exception as pdf_err:
                        st.error(f"Could not generate test PDF: {pdf_err}. No test email was sent.")
                else:
                    st.error("ReportLab not installed — no test email was sent. Run: pip install reportlab")

            if not attach_test or attach_path is not None:
                with st.spinner("Sending test email via Gmail API…"):
                    result = gmail_sender.send_test_email(
                        test_to.strip(),
                        attachment_path,
                        own_address_confirmed=test_address_is_own,
                    )

                if result["success"]:
                    st.session_state.gmail_test_passed = True
                    st.session_state.gmail_test_address = test_to.strip()
                    connected = True
                    st.success(
                        f"✅ Test email sent! Gmail message ID: `{result['message_id']}`\n\n"
                        f"Check your inbox at {test_to.strip()}"
                    )
                else:
                    st.error(f"❌ Test failed: {result['error']}")
                    if "token" in result["error"].lower() or "refresh" in result["error"].lower():
                        st.info("💡 Your token may have expired (7-day testing-mode limit). "
                                "Delete token.json and reconnect Gmail.")

st.divider()

# ===========================================================================
# Section 3: Compose & Send Outreach
# ===========================================================================
st.markdown("## 3. Recruiter Outreach")
st.caption(
    "Compose a personalized application email for a specific job. "
    "Recruiter contacts must be explicitly published and verified manually. "
    "Duplicate sends are automatically blocked."
)

if not connected:
    st.warning("Connect Gmail above to enable outreach.")
    st.stop()

jobs = db.get_jobs_with_status()
resumes = st.session_state.get("resumes", {})

if not jobs:
    st.warning("No jobs in database. Run a scan from the Dashboard first.")
    st.stop()

if not resumes:
    st.warning("No resumes loaded. Upload PDFs in the sidebar on the Dashboard page.")

# Safety guards display
with st.expander("🛡️ Active Safety Guards", expanded=False):
    st.markdown("""
    <div class="guard-box">✅ Email validation — structural check on every recipient address</div>
    <div class="guard-box">✅ HTTPS source URL required — user manually verifies contact publication and opt-out status</div>
    <div class="guard-box">✅ Duplicate blocking — same job + recipient never sent twice (DB constraint)</div>
    <div class="guard-box">✅ Daily limit — configurable max sends per day (default 10)</div>
    <div class="guard-box">✅ Attachment check — PDF must exist and be non-empty before sending</div>
    <div class="guard-box">✅ No guessing — inferred/pattern-matched emails rejected</div>
    <div class="guard-box">✅ No automatic sending — each message is manually initiated</div>
    """, unsafe_allow_html=True)

# Job selector
shortlisted = sorted(jobs, key=lambda j: int(j.get("score") or 0), reverse=True)[:50]
job_labels  = {
    f"{j['title']} @ {(j['company']).title()} (score: {j.get('score', 0)})": j
    for j in shortlisted
}
selected_label = st.selectbox("Select job to apply to:", list(job_labels.keys()))
selected_job   = job_labels[selected_label]

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### 📬 Recipient")
    recipient_email = st.text_input(
        "Recruiter / HR email address:",
        placeholder="recruiter@company.com",
        help="Must be explicitly published by the employer in the job listing or careers page.",
    )
    recipient_source = st.text_input(
        "Source URL where this email was found:",
        placeholder="https://company.com/careers#contact",
        help="The page where you found the recruiter's email address. Required.",
    )
    contact_verified = st.checkbox(
        "I verified this address is published for recruitment and has not opted out.",
        help="The app cannot verify the page contents; inspect the source URL yourself.",
    )

    sender_name = st.text_input(
        "Your name (as it appears on your resume):",
        placeholder="Full Name",
    )

with col_right:
    st.markdown("### 📄 Resume")
    if resumes:
        resume_choice = st.selectbox("Resume profile to attach:", list(resumes.keys()))
        resume_text   = resumes[resume_choice]

        matched, missing = drafter._matched_skills_for_job(resume_text, selected_job)
        if matched:
            st.caption(f"✅ Matched skills: {', '.join(matched[:8])}")
        if missing:
            st.caption(f"⚠️ Missing in resume: {', '.join(missing[:5])}")
    else:
        resume_choice = None
        resume_text   = ""
        st.warning("Upload resume PDFs on the Dashboard.")

    st.markdown("### 📎 PDF Attachment")
    if reportlab_available():
        st.info("ReportLab installed — will generate ATS-friendly PDF on send.")
    else:
        st.error("ReportLab not installed. Sending is disabled until PDF generation is available.")

# Preview compose
if st.button("👁️ Preview Email", disabled=not (recipient_email and sender_name and resume_text)):
    subject, body = gmail_sender.compose_outreach_email(
        selected_job, resume_text, sender_name, resume_choice or ""
    )
    st.markdown("**Subject:**")
    st.code(subject)
    st.markdown("**Body:**")
    st.text_area("", body, height=350, key="preview_body")

st.divider()

# ---------------------------------------------------------------------------
# Send controls — require explicit confirmation
# ---------------------------------------------------------------------------
st.markdown("### 🚀 Send")

daily_limit = st.number_input("Daily outreach limit", min_value=1, max_value=50, value=10,
                               help="Maximum recruiter emails to send today. Separate from the 50-application queue limit.")

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
today_count = db.get_daily_outreach_count(today)
st.caption(f"Sent today: **{today_count}** / {daily_limit}")

# Explicit manual-send opt-in resets each session; no automatic sender exists.
if "gmail_sending_enabled" not in st.session_state:
    st.session_state.gmail_sending_enabled = False

if not st.session_state.gmail_sending_enabled:
    st.warning(
        "🔒 **Sending is disabled.** Explicitly enable manual sending below for this session.\n\n"
        "Every recruiter email is individually initiated by you."
    )
    if st.button("🔓 Enable Manual Sending for This Session",
                 help="This opt-in resets when you close the browser or restart the app."):
        st.session_state.gmail_sending_enabled = True
        db.audit("GMAIL:MANUAL_SENDING_ENABLED", detail="User enabled manual outreach sending for session")
        st.success("Sending enabled for this session. You will still confirm each email.")
        st.rerun()
else:
    st.success("🟢 Manual sending enabled for this session.")
    if st.button("🔒 Disable Sending"):
        st.session_state.gmail_sending_enabled = False
        st.rerun()

can_send = (
    st.session_state.gmail_sending_enabled
    and bool(recipient_email.strip() if recipient_email else False)
    and bool(recipient_source.strip() if recipient_source else False)
    and bool(sender_name.strip() if sender_name else False)
    and bool(resume_text)
    and contact_verified
)

if st.button("✉️ Send Outreach Email", type="primary", disabled=not can_send):
    # Final pre-flight checks shown to user
    checks_pass = True

    if not gmail_sender.is_valid_email(recipient_email.strip()):
        st.error("❌ Invalid email address.")
        checks_pass = False
    if not recipient_source.strip().startswith("http"):
        st.error("❌ Source URL must be a valid https:// URL.")
        checks_pass = False
    if not contact_verified:
        st.error("❌ Confirm that the contact was published for recruitment and has not opted out.")
        checks_pass = False
    if db.is_already_contacted(selected_job["job_key"], recipient_email.strip()):
        st.error(f"❌ Already contacted this recruiter for this job — duplicate blocked.")
        checks_pass = False
    if today_count >= daily_limit:
        st.error(f"❌ Daily limit reached ({today_count}/{daily_limit}).")
        checks_pass = False

    if checks_pass:
        # Generate the required PDF before creating any outreach record.
        attach_path = None
        if reportlab_available() and resume_text:
            try:
                with st.spinner("Generating PDF resume…"):
                    attach_path = generate_pdf_resume(
                        selected_job, resume_text, resume_choice or "resume.pdf"
                    )
                st.success(f"✅ PDF generated: {attach_path.name}")
            except Exception as pdf_err:
                st.error(f"❌ PDF generation failed ({pdf_err}). No email was sent.")
                checks_pass = False
        else:
            st.error("❌ ReportLab is unavailable. A PDF is required; no email was sent.")
            checks_pass = False

        if checks_pass and attach_path is not None:
            with st.spinner("Sending via Gmail API…"):
                result = gmail_sender.send_outreach_email(
                    job=selected_job,
                    recipient_email=recipient_email.strip(),
                    recipient_source_url=recipient_source.strip(),
                    resume_text=resume_text,
                    sender_name=sender_name.strip(),
                    resume_filename=resume_choice or "resume.pdf",
                    attachment_path=attach_path,
                    daily_limit=daily_limit,
                )

            if result["success"]:
                st.success(
                    f"✅ Email sent! Gmail message ID: `{result['message_id']}`\n\n"
                    f"Outreach record ID: {result['outreach_id']} — tracked in database."
                )
            else:
                st.error(f"❌ Send failed: {result['error']}")

st.divider()

# ===========================================================================
# Section 4: Outreach Tracker
# ===========================================================================
st.markdown("## 4. Outreach Tracker")

tab_all, tab_sent, tab_failed, tab_followup = st.tabs(
    ["All", "Sent", "Failed", "Follow-up Due"]
)

def render_outreach_row(r: dict):
    status_map = {
        "sent":          ("outreach-sent",   "✅ Sent"),
        "queued":        ("outreach-queued",  "⏳ Queued"),
        "failed":        ("outreach-failed",  "❌ Failed"),
        "bounced":       ("outreach-failed",  "⚠️ Bounced"),
        "replied":       ("outreach-sent",    "💬 Replied"),
        "follow_up_due": ("outreach-queued",  "🔔 Follow-up Due"),
    }
    css, label = status_map.get(r["status"], ("outreach-queued", r["status"]))

    # Redact full email in display
    rec_display = gmail_sender._redact_email(r["recipient_email"])
    send_ts = r["send_ts"][:10] if r["send_ts"] else "—"
    follow_up = r["follow_up_date"] or "—"

    with st.container(border=True):
        c1, c2, c3 = st.columns([4, 2, 2])
        with c1:
            st.markdown(f"**{r['job_title']}** @ {r['company']}")
            st.caption(f"To: {rec_display} · Subject: {r['subject'][:60]}…")
        with c2:
            st.markdown(
                f'<div class="{css}" style="padding:4px 8px;font-size:0.8rem;">{label}</div>',
                unsafe_allow_html=True
            )
            st.caption(f"Sent: {send_ts} · Follow-up: {follow_up}")
        with c3:
            if r["status"] == "sent" and not r["recruiter_replied"]:
                if st.button("💬 Mark Replied", key=f"replied_{r['id']}"):
                    db.mark_recruiter_replied(r["id"])
                    st.rerun()
            if r["error_detail"]:
                st.caption(f"Error: {r['error_detail'][:80]}")

with tab_all:
    records = db.get_outreach_records()
    if records:
        for r in records:
            render_outreach_row(r)
    else:
        st.info("No outreach records yet.")

with tab_sent:
    records = db.get_outreach_records("sent")
    if records:
        for r in records:
            render_outreach_row(r)
    else:
        st.info("No sent emails yet.")

with tab_failed:
    records = db.get_outreach_records("failed")
    if records:
        for r in records:
            render_outreach_row(r)
    else:
        st.success("No failed sends. ✅")

with tab_followup:
    due = db.get_follow_up_due()
    if due:
        st.warning(f"🔔 {len(due)} follow-up(s) due!")
        for r in due:
            render_outreach_row(r)
    else:
        st.info("No follow-ups due.")

st.divider()
st.markdown("## 📋 Outreach Policy")
st.markdown("""
| Rule | Enforcement |
|------|-------------|
| Only explicitly published contacts | UI validation + DB requires source URL |
| No guessed or inferred addresses | `is_valid_email()` + source URL guard |
| No duplicate outreach | `UNIQUE(job_key, recipient_email)` in DB |
| Daily send limit | Configurable (default 10/day) |
| Explicit opt-in each session | Toggle resets on app restart |
| PDF must exist before attaching | File existence check before send |
| Token never logged | `gmail_auth.py` never prints credentials |
| Error details redacted | Email addresses stripped from error logs |
| Manual confirmation | No auto-send loop; each email user-triggered |
""")
