"""
gmail_auth.py — Gmail OAuth 2.0 authentication for Job Hunter Agent.

Uses the official Google API Python client library with the installed-app
(desktop) OAuth flow.

SECURITY RULES enforced here:
- credentials.json and token.json are NEVER logged or printed.
- Token data is written with mode 0o600 (owner read/write only).
- Only the minimum scope (gmail.send) is requested.
- Tokens are refreshed automatically; revocation is handled cleanly.
- No passwords, OTPs, or cookies are ever requested from the user.

SETUP (one-time, done by the user):
1. Go to https://console.cloud.google.com/
2. Create a project → Enable Gmail API.
3. Credentials → Create OAuth client ID → Desktop application.
4. Download as credentials.json and place in this project directory.
5. Run this app and click "Connect Gmail" — the browser will open Google's
   consent screen. Sign in and approve. token.json is saved automatically.

REFRESH TOKEN EXPIRY NOTE:
Gmail send scope is classified as a sensitive scope. When the OAuth app is
in "Testing" mode on Google Cloud Console, refresh tokens expire after 7 days.
To get non-expiring tokens, publish the app (OAuth consent screen → Publish).
Instructions to reauthorize: delete token.json and click "Connect Gmail" again.
"""

import os
import stat
from pathlib import Path
from typing import Optional

# Lazy imports — only fail at call time if not installed
_IMPORT_ERROR: Optional[str] = None
try:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError as e:
    _IMPORT_ERROR = str(e)

BASE = Path(__file__).parent
CREDENTIALS_FILE = BASE / "credentials.json"
TOKEN_FILE = BASE / "token.json"

# Minimum scope: send email only — no inbox reading.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _check_imports() -> None:
    """Raise ImportError with install instructions if deps are missing."""
    if _IMPORT_ERROR:
        raise ImportError(
            f"Google Auth packages not installed: {_IMPORT_ERROR}\n"
            "Run: pip install google-auth google-auth-oauthlib google-api-python-client"
        )


def credentials_file_exists() -> bool:
    """Return True if credentials.json exists and is non-empty."""
    return CREDENTIALS_FILE.exists() and CREDENTIALS_FILE.stat().st_size > 10


def token_file_exists() -> bool:
    """Return True if token.json exists."""
    return TOKEN_FILE.exists() and TOKEN_FILE.stat().st_size > 10


def _write_token_secure(creds: "Credentials") -> None:
    """Write token.json with restrictive file permissions (owner r/w only)."""
    token_data = creds.to_json()
    TOKEN_FILE.write_text(token_data, encoding="utf-8")
    # Set 0o600 (owner read+write only) on POSIX; on Windows this is best-effort
    try:
        TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (AttributeError, NotImplementedError, OSError):
        pass  # Windows may not support POSIX chmod — acceptable


def get_credentials() -> Optional["Credentials"]:
    """
    Return valid Gmail credentials, refreshing if expired.

    Returns None if:
    - credentials.json is missing (user hasn't set up OAuth yet)
    - token.json is missing (user hasn't authorized yet)
    - Authorization has been revoked and refresh fails

    Raises ImportError if Google Auth packages are not installed.
    """
    _check_imports()

    creds: Optional[Credentials] = None

    # Load existing token
    if token_file_exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None  # Corrupted token — will re-authorize

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _write_token_secure(creds)
                return creds
            except RefreshError:
                # Token revoked or expired beyond refresh — need full re-auth
                TOKEN_FILE.unlink(missing_ok=True)
                return None
        # No valid creds — caller must run the authorization flow
        return None

    return creds


def run_auth_flow() -> "Credentials":
    """
    Run the OAuth desktop authorization flow.

    Opens the system browser to Google's consent screen.
    Saves token.json on success.

    Raises:
        FileNotFoundError: if credentials.json is missing.
        ImportError: if Google Auth packages not installed.
        Exception: if the OAuth flow fails or is cancelled.
    """
    _check_imports()

    if not credentials_file_exists():
        raise FileNotFoundError(
            "credentials.json not found.\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials.\n"
            f"Expected path: {CREDENTIALS_FILE}"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    # run_local_server opens a browser tab at Google's consent screen
    creds = flow.run_local_server(
        port=0,           # OS picks a free port
        open_browser=True,
        prompt="consent", # Always show consent to ensure refresh_token is issued
    )
    _write_token_secure(creds)
    return creds


def get_authorized_email() -> Optional[str]:
    """
    Return None: the Gmail account address must be fetched from the Gmail API.

    OAuth client IDs are not account addresses and must never be presented as
    an authorized identity.
    """
    return None


def revoke_credentials() -> bool:
    """
    Delete the local token.json to disconnect Gmail.
    Does not call Google's revoke endpoint (user must revoke at myaccount.google.com).
    Returns True if token was deleted.
    """
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        return True
    return False


def auth_status() -> dict:
    """
    Return a status dictionary safe for display (no credential values).

    Keys:
        connected: bool
        credentials_file_present: bool
        token_file_present: bool
        token_valid: bool
        token_expired: bool
        error: str or None
    """
    _check_imports_safe = _IMPORT_ERROR is None

    status = {
        "connected": False,
        "credentials_file_present": credentials_file_exists(),
        "token_file_present": token_file_exists(),
        "token_valid": False,
        "token_expired": False,
        "error": None,
        "packages_installed": _check_imports_safe,
    }

    if not _check_imports_safe:
        status["error"] = (
            "Google Auth packages not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-api-python-client"
        )
        return status

    try:
        creds = get_credentials()
        if creds and creds.valid:
            status["connected"] = True
            status["token_valid"] = True
        elif creds and creds.expired:
            status["token_expired"] = True
            status["error"] = (
                "Token expired and could not be refreshed. "
                "This may happen if the OAuth app is in Testing mode (7-day limit). "
                "Delete token.json and re-authorize."
            )
        else:
            status["error"] = (
                "Not authorized. Click 'Connect Gmail' to begin the OAuth flow."
                if credentials_file_exists()
                else "credentials.json missing. See Settings for setup instructions."
            )
    except Exception as exc:
        status["error"] = (
            f"Auth error ({type(exc).__name__}). Reconnect Gmail and check the OAuth setup."
        )

    return status
