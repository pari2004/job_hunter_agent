"""Shared Streamlit presentation helpers."""

from datetime import datetime

import streamlit as st


def fmt_date(raw: str) -> str:
    """Format an ISO date string for display without inventing a date."""
    if not raw or str(raw).strip() in ("", "0", "None"):
        return "Date not provided"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except ValueError:
        value = str(raw)
        return value[:10] if len(value) >= 10 else value


def render_job_badges(job: dict) -> None:
    """Render visa, remote, and priority-location badges for a job."""
    badges = []
    if job.get("visa_sponsorship"):
        badges.append('<span class="badge badge-blue">🛂 Visa Sponsorship</span>')
    if job.get("is_remote"):
        badges.append('<span class="badge badge-purple">🌐 Remote</span>')
    location = (job.get("location") or "").lower()
    if any(value in location for value in ("bengaluru", "bangalore")):
        badges.append('<span class="badge badge-green">📍 Bengaluru</span>')
    elif any(value in location for value in ("mysuru", "mysore")):
        badges.append('<span class="badge badge-green">📍 Mysuru</span>')
    elif "mumbai" in location:
        badges.append('<span class="badge badge-orange">📍 Mumbai</span>')
    elif "pune" in location:
        badges.append('<span class="badge badge-orange">📍 Pune</span>')
    if badges:
        st.markdown(" ".join(badges), unsafe_allow_html=True)
