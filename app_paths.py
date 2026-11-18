"""Persistent data paths shared by the application."""

import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("JOB_HUNTER_DATA_DIR", str(APP_DIR))).expanduser()
SOURCE_CONFIG = DATA_DIR / "sources.json"


def ensure_source_config() -> Path:
    """Initialize the writable source config from the bundled defaults once."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bundled_config = APP_DIR / "sources.json"
    if not SOURCE_CONFIG.exists() and bundled_config.exists():
        shutil.copyfile(bundled_config, SOURCE_CONFIG)
    return SOURCE_CONFIG
