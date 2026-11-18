"""Tests for hosted deployment configuration and data paths."""

import json

import app_paths
import app_security
from app_security import is_app_password_valid


def test_app_password_comparison():
    assert is_app_password_valid("correct horse battery staple", "correct horse battery staple")
    assert not is_app_password_valid("wrong", "correct horse battery staple")
    assert not is_app_password_valid("", "")


def test_source_config_is_seeded_once(tmp_path, monkeypatch):
    default_config = tmp_path / "bundled" / "sources.json"
    default_config.parent.mkdir()
    default_config.write_text('{"greenhouse": ["example"]}', encoding="utf-8")
    data_dir = tmp_path / "persistent"
    target_config = data_dir / "sources.json"
    monkeypatch.setattr(app_paths, "APP_DIR", default_config.parent)
    monkeypatch.setattr(app_paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_paths, "SOURCE_CONFIG", target_config)

    assert app_paths.ensure_source_config() == target_config
    assert json.loads(target_config.read_text(encoding="utf-8")) == {
        "greenhouse": ["example"]
    }

    target_config.write_text('{"greenhouse": ["custom"]}', encoding="utf-8")
    app_paths.ensure_source_config()
    assert json.loads(target_config.read_text(encoding="utf-8")) == {
        "greenhouse": ["custom"]
    }


def test_production_fails_closed_without_app_password(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    errors = []
    monkeypatch.setattr(app_security.st, "error", errors.append)

    def stop():
        raise RuntimeError("Streamlit execution stopped")

    monkeypatch.setattr(app_security.st, "stop", stop)
    try:
        app_security.require_app_auth()
    except RuntimeError as exc:
        assert str(exc) == "Streamlit execution stopped"
    else:
        raise AssertionError("Production without a password must stop the app.")

    assert errors == [
        "Hosted access is disabled: configure the APP_PASSWORD environment variable."
    ]
