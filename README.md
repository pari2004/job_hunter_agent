# Job Hunter Agent

A local Python dashboard for software engineering job discovery, resume matching, and application tracking. Built for graduate/fresher candidates targeting **SDE, Backend, Python, Java, Full Stack, Frontend, and AI/ML** roles in **Bengaluru, Mysuru, Mumbai, Pune**, and remote positions with visa sponsorship.

---

## Quick Start (Windows)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

App opens at **http://localhost:8501**

## Hosted Deployment (Render)

This is a Streamlit server, not a Vercel Function app. The current UI relies on
Streamlit sessions and long-lived server connections; SQLite and uploaded resume
text also need persistent/private storage. Use a host that runs a persistent
Python web service and provides a mounted persistent disk. The included Render
Blueprint provisions a Docker service and a disk for the SQLite database,
source settings, and generated drafts.

1. This workspace currently has no Git repository. Create a **private** GitHub
   repository and push the project files. Do not include
   `.env`, `credentials.json`, `token.json`, resumes, or `jobs.db`.
2. In Render, create a Blueprint from that repository and review the paid
   Starter service and persistent-disk plan (1 GB) before confirming creation.
3. Set `APP_PASSWORD` in the Render service environment to a strong unique
   password. The hosted app will block access if this is not configured.
4. Deploy and wait for the `/_stcore/health` check to pass.
5. Sign in with the app password, upload your resume PDFs for the current
   session, run a scan, and review each job before applying on its official
   employer page.

The mounted disk must remain attached to this service. Do not scale the
single-user SQLite deployment to multiple instances. Keep resumes local and
upload only the profiles needed for a session. The existing Gmail integration
uses desktop OAuth and is intentionally disabled on hosted deployments; a
separate web OAuth implementation is required before hosted Gmail sending can
be enabled. Applications are never submitted automatically.

---

## Project Structure

```
job_hunter_agent/
├── app.py                  ← Dashboard home + scan control
├── db.py                   ← SQLite data layer (all schema & CRUD)
├── scorer.py               ← Deterministic job scoring engine
├── drafts.py               ← Resume & cover letter draft generator
├── queue_manager.py        ← Daily application queue (max 50/day)
├── adapters/
│   ├── greenhouse.py       ← Greenhouse Boards API (public, no auth)
│   ├── lever.py            ← Lever Postings API (public, no auth)
│   └── remoteok.py         ← RemoteOK JSON feed (disabled by default)
├── pages/
│   ├── 1_Pipeline.py       ← Full job list with filters & status
│   ├── 2_Drafts.py         ← Generate resume drafts & cover letters
│   ├── 3_Queue.py          ← Daily application queue management
│   └── 4_Settings.py       ← Sources, live tester, alerts, DB stats
├── resumes/                ← Original PDFs go here (gitignored)
├── drafts_output/          ← Generated draft files (gitignored)
├── sources.json            ← Configured job board sources
├── .env.example            ← Environment variable template (no secrets)
├── requirements.txt
└── tests/
    ├── test_scorer.py
    ├── test_db.py
    └── test_adapters.py    ← Live API tests (skipped if offline)
```

---

## How Job Discovery Works

### Sources (configured in `sources.json`)

| Source | Auth Required | Notes |
|--------|---------------|-------|
| Greenhouse Boards API | ❌ None | Public board API; use board token |
| Lever Postings API | ❌ None | Public v0 API; use site slug |
| RemoteOK JSON feed | ❌ None | Disabled by default; may time out |

**Verified Greenhouse tokens** (tested live, return jobs):
`airbnb`, `stripe`, `twilio`, `gitlab`, `figma`, `vercel`, `datadog`, `cloudflare`, `reddit`, `discord`, `brex`, `gusto`, `asana`, `pagerduty`, `mixpanel`, `netlify`, `airtable`

**Verified Lever slugs:** `cred`, `fly`

### Adding sources
1. Go to **Settings → Greenhouse Tokens** and add one token per line.
2. To find a Greenhouse token: look at the company's careers URL  
   `https://boards.greenhouse.io/TOKEN` → the `TOKEN` is what you enter.
3. To find a Lever slug: look at `https://jobs.lever.co/SLUG`.
4. Use the **Live Source Tester** in Settings to verify before adding.

---

## Configuring Sources

Edit `sources.json` directly or use the Settings page:

```json
{
  "greenhouse": ["airbnb", "stripe", "twilio"],
  "lever": ["cred"],
  "remoteok": false
}
```

---

## Resume Matching

1. Upload up to 4 PDF resumes in the sidebar (Dashboard page).
2. After a scan, each job is scored 0–100 against all uploaded resumes.
3. The best-matching resume is shown for each job.
4. Resume text remains in the current Streamlit session; upload the files again in a new session.

**Score breakdown:**
- Token overlap (job description ↔ resume): up to 40 pts
- Skill keyword match (Python, Java, React, etc.): up to 20 pts
- Target role title match: +15 pts
- Location bonus (Bengaluru +20, Mysuru +15, Mumbai/Pune +10, India +5)
- Fresher-friendly keywords: +5 pts
- Visa/sponsorship mention: +5 pts
- Senior-only role penalty: −25 pts

---

## Resume & Cover Letter Drafts

- Go to **Drafts** page, select a job and a resume profile.
- Click **Generate Resume Draft** or **Generate Cover Letter**.
- Resume draft content is preserved from the selected uploaded resume; generated text does not add qualifications or achievements.
- Cover-letter output is a template with explicit placeholders for details you must personally verify.
- No employers, dates, qualifications, or skills are invented.
- `[BRACKET]` placeholders must be filled in by you before submitting.
- Download the `.txt` draft and edit in Word or Google Docs.
- Original PDFs are never modified.

---

## Daily Application Queue

- The queue targets up to **50 relevant jobs per day** (configurable).
- Only jobs scoring ≥ 30 and with eligible status are queued.
- **Applications are NEVER submitted automatically.**
- Workflow: Open official page → review draft → confirm submission manually.
- Duplicate submissions are blocked: marking "Applied" twice is prevented.

## Gmail (Optional, Manual)

- The Gmail page uses Google's official desktop OAuth flow and requests only `gmail.send`.
- Put the downloaded Desktop OAuth client file at `credentials.json` in the project root. The local `token.json` is ignored by Git.
- The connection is shown as tested only after the Gmail API confirms a test message. The least-privilege `gmail.send` scope cannot read the Gmail account profile, so the test address is self-confirmed rather than inferred from Google.
- Send test messages only to your own configured address. Recruiter emails require a manually verified HTTPS source and an explicit opt-in each session.
- A valid generated PDF resume is required for recruiter messages. Duplicate job/contact pairs and the daily outreach limit are enforced.
- **Recruiter outreach is manually initiated, not automated.** The 50-job application queue is separate; required employer portal applications still need to be completed manually.
- In Google OAuth Testing mode, refresh tokens for sensitive Gmail scopes can expire after seven days. Delete `token.json`, then reconnect from the Gmail page to authorize again.
- No real Gmail test was run unless you supply OAuth credentials and complete authorization. Automated tests mock the Gmail API and send no real email.

---

## Running Tests

```powershell
# Unit tests only (no network required)
.venv\Scripts\python.exe -m pytest tests/test_scorer.py tests/test_db.py -v

# All tests including live API calls
.venv\Scripts\python.exe -m pytest tests/ -v

# With coverage
pip install pytest-cov
.venv\Scripts\python.exe -m pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Acceptance Test — Run a Scan

1. Start the app: `streamlit run app.py`
2. Upload a resume PDF in the sidebar.
3. Click **Run Scan** on the Dashboard.
4. Observe the **per-source diagnostic report** (green = success, red = failure).
5. Browse matched jobs in the **Job Pipeline** page.
6. Filter by location (Bengaluru first), minimum score, and role type.
7. Shortlist a job, generate a draft, download it, and open the application page.

If zero jobs are found:
- Check the diagnostics panel — each source shows HTTP status and error reason.
- Verify your `sources.json` tokens using the **Live Source Tester** in Settings.
- Ensure internet connectivity (the app queries public APIs).

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| Greenhouse scanning | ✅ Functional | 17 verified tokens |
| Lever scanning | ✅ Functional | `cred` verified |
| RemoteOK scanning | ⚠️ Network-dependent | Enable in Settings if accessible |
| Resume PDF upload | ✅ Functional | Up to 4 profiles |
| Job scoring | ✅ Functional | Deterministic, 0–100 |
| Duplicate job prevention | ✅ Functional | By job_key |
| Resume draft generation | ✅ Functional | Template-based |
| Cover letter generation | ✅ Functional | Template-based |
| Daily queue | ✅ Functional | Max 50/day |
| Duplicate submission guard | ✅ Functional | Blocks re-applying |
| Gmail OAuth and manual outreach | ⚠️ Setup required | Requires local `credentials.json`; manual sending only |
| Automatic recruiter outreach | ❌ Not implemented | No background/automatic sender |
| Per-source diagnostics | ✅ Functional | HTTP status + error hint |
| Visa sponsorship detection | ✅ Functional | Keyword-based |
| Fresher-friendly detection | ✅ Functional | Keyword-based |
| Auto-submission | ❌ Not implemented | Intentional; user confirms manually |
| LLM resume rewriting | ❌ Requires API key | Add OPENAI_API_KEY to .env |
| Email/Slack alerts | ❌ Not implemented | Future feature |
| Scheduled scans | ❌ Not implemented | Use Windows Task Scheduler |
| LinkedIn/Indeed | ❌ Excluded | Violates their Terms of Service |

---

## Safety & Accuracy

- **Never bypasses CAPTCHA, MFA, or platform restrictions.**
- **Never stores passwords, OTPs, or session cookies.**
- **Never auto-submits through unsupported or prohibited workflows.**
- **Never invents qualifications, employers, dates, or experience** in drafts.
- Greenhouse and Lever APIs are accessed within their public, rate-limit guidelines.
- Match scores are heuristic indicators — not hiring probability estimates.
- Verify job freshness on the employer's own page before applying.

---

## Data & Privacy

- All data is stored locally in `jobs.db` (SQLite).
- Resume text is held only in session memory (not persisted to disk).
- Generated drafts are saved in `drafts_output/` locally.
- Job-board requests use public APIs. Gmail is contacted only after OAuth and a user-triggered send.
- OAuth client credentials, tokens, uploaded resumes, and generated PDFs are excluded from Git by `.gitignore`.

---

## Future Roadmap

- [ ] LLM-powered resume tailoring (opt-in, with user-provided API key)
- [ ] Scheduled automatic scans (Windows Task Scheduler integration)
- [ ] Email/Slack alerts for high-match new jobs
- [ ] Work authorisation eligibility checker for international roles
- [ ] ATS keyword density analyser
- [ ] Application analytics dashboard (response rate, pipeline velocity)
