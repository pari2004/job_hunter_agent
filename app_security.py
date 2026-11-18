"""Single-user password gate for hosted deployments."""

import hmac
import os

import streamlit as st


def is_app_password_valid(candidate: str, configured: str) -> bool:
    """Compare the supplied password without leaking timing information."""
    return bool(configured) and hmac.compare_digest(candidate, configured)


def require_app_auth() -> None:
    """Require a shared password when the app is deployed in production."""
    if os.environ.get("APP_ENV", "").lower() != "production":
        return

    configured = os.environ.get("APP_PASSWORD", "")
    if not configured:
        st.error("Hosted access is disabled: configure the APP_PASSWORD environment variable.")
        st.stop()

    if st.session_state.get("_app_authenticated"):
        return

    st.title("Private Job Hunter Agent")
    with st.form("app_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if is_app_password_valid(password, configured):
            st.session_state["_app_authenticated"] = True
            st.rerun()
        st.error("Incorrect app password.")
    st.stop()
