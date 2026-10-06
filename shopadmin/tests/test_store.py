"""Tests for the local SQLite store (settings, remembered username, local audit).

Staff accounts are NOT stored locally any more; that is asserted here too.
"""
from __future__ import annotations

import sqlite3

from app.store import Store


def test_schema_is_created_on_a_fresh_file(tmp_path):
    path = tmp_path / "nested" / "fresh.db"
    store = Store(path)
    try:
        assert path.exists()
        # Defaults must be present so the wizard and settings page have values.
        assert store.get_setting("shopapi_base_url").startswith("http")
        assert store.get_setting("wizard_completed") is False
        assert store.get_int_setting("session_timeout_minutes", 30) == 30
        assert store.get_setting("notify_desktop") is True
    finally:
        store.close()


def test_no_local_account_tables(store):
    tables = {r["name"] for r in store._all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "admin_users" not in tables
    assert "remembered_sessions" not in tables


def test_legacy_accounts_and_api_key_are_removed_on_open(tmp_path):
    """An older version kept staff hashes and the shared admin key on every PC."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);"
        "INSERT INTO admin_users VALUES (1, 'owner', '$2b$12$hash');"
        "CREATE TABLE remembered_sessions (user_id INTEGER PRIMARY KEY, token_hash TEXT);"
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO settings VALUES ('shopapi_api_key', '\"old-admin-key\"', 'x');"
    )
    conn.commit()
    conn.close()

    store = Store(path)
    try:
        tables = {r["name"] for r in store._all("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "admin_users" not in tables and "remembered_sessions" not in tables
        assert store.get_setting("shopapi_api_key") is None
    finally:
        store.close()
    # VACUUM rewrites the file, so the old values are not left in free pages.
    raw = path.read_bytes()
    assert b"old-admin-key" not in raw and b"$2b$12$hash" not in raw


def test_settings_roundtrip_and_types(store):
    store.set_setting("auto_refresh_seconds", 45)
    store.set_setting("shopapi_base_url", "http://example.test/")
    assert store.get_setting("auto_refresh_seconds") == 45
    assert isinstance(store.get_setting("auto_refresh_seconds"), int)
    assert store.get_setting("missing_key", "fallback") == "fallback"


def test_all_settings_snapshot(store):
    snapshot = store.all_settings()
    assert "shopapi_base_url" in snapshot
    assert "session_timeout_minutes" in snapshot


def test_get_int_setting_clamps_values(store):
    store.set_setting("auto_refresh_seconds", 999999)
    assert store.get_int_setting("auto_refresh_seconds", 30, minimum=5, maximum=600) == 600
    store.set_setting("auto_refresh_seconds", "not a number")
    assert store.get_int_setting("auto_refresh_seconds", 30, minimum=5, maximum=600) == 30


def test_configure_connection_trims_trailing_slash(store):
    store.configure_connection("http://127.0.0.1:8000/")
    assert store.base_url == "http://127.0.0.1:8000"


def test_is_configured_requires_wizard_completion(store):
    assert store.is_configured() is False
    store.configure_connection("http://127.0.0.1:8000")
    assert store.is_configured() is False
    store.set_setting("wizard_completed", True)
    assert store.is_configured() is True


def test_audit_trail(store):
    store.audit("owner", "test", "something happened")
    rows = store.list_audit()
    assert rows and rows[0]["action"] == "test"


def test_remembered_user_is_single_row_and_holds_no_token(store):
    store.save_remembered_user("owner")
    store.save_remembered_user("owner2")
    remembered = store.get_remembered_user()
    assert remembered["username"] == "owner2"
    assert "token" not in remembered
    store.clear_remembered_user()
    assert store.get_remembered_user() is None


def test_in_memory_store_works():
    store = Store(":memory:")
    try:
        store.set_setting("auto_refresh_seconds", 10)
        assert store.get_setting("auto_refresh_seconds") == 10
    finally:
        store.close()
