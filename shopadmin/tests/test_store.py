"""Tests for the local SQLite store (internal admin users, settings, audit)."""
from __future__ import annotations

import pytest

from app.store import SECRET_SETTING_KEYS, Store


def test_schema_is_created_on_a_fresh_file(tmp_path):
    path = tmp_path / "nested" / "fresh.db"
    store = Store(path)
    try:
        assert path.exists()
        assert store.count_admin_users() == 0
        # Defaults must be present so the wizard and settings page have values.
        assert store.get_setting("shopapi_base_url").startswith("http")
        assert store.get_setting("wizard_completed") is False
        assert store.get_int_setting("session_timeout_minutes", 30) == 30
    finally:
        store.close()


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
    store.configure_connection("http://127.0.0.1:8000/", "  secret-key  ")
    assert store.base_url == "http://127.0.0.1:8000"
    assert store.api_key == "secret-key"


def test_is_configured_requires_wizard_completion(store):
    assert store.is_configured() is False
    store.configure_connection("http://127.0.0.1:8000", "k")
    assert store.is_configured() is False
    store.set_setting("wizard_completed", True)
    assert store.is_configured() is True


def test_api_key_is_not_logged_in_plain_text(store, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="shopadmin"):
        store.set_setting("shopapi_api_key", "super-secret-value")
    assert "super-secret-value" not in caplog.text
    assert "chars" in caplog.text


def test_audit_redacts_the_api_key(store):
    store.set_setting("shopapi_api_key", "super-secret-value")
    store.audit("owner", "test", "key is super-secret-value for sure")
    rows = store.list_audit()
    assert rows
    assert "super-secret-value" not in rows[0]["detail"]
    assert "<secret>" in rows[0]["detail"]


def test_admin_user_crud(store):
    user = store.create_admin_user("operator1", "اپراتور یک", "hash", "operator")
    assert user["username"] == "operator1"
    assert user["is_active"] == 1
    assert store.count_admin_users() == 1

    updated = store.update_admin_user(user["id"], full_name="نام تازه")
    assert updated["full_name"] == "نام تازه"

    store.update_admin_user(user["id"], is_active=False)
    assert store.get_admin_user(user["id"])["is_active"] == 0

    store.delete_admin_user(user["id"])
    assert store.count_admin_users() == 0


def test_username_lookup_is_case_insensitive(store):
    store.create_admin_user("Owner", "مالک", "hash", "super_admin")
    assert store.get_admin_user_by_username("owner") is not None
    assert store.get_admin_user_by_username("OWNER") is not None
    assert store.get_admin_user_by_username("nobody") is None


def test_duplicate_username_is_rejected_by_the_database(store):
    import sqlite3

    store.create_admin_user("dup", "یک", "hash", "operator")
    with pytest.raises(sqlite3.IntegrityError):
        store.create_admin_user("dup", "دو", "hash", "operator")


def test_failed_attempt_locking_flow(store):
    user = store.create_admin_user("locked", "قفل", "hash", "operator")
    for _ in range(5):
        store.register_failed_attempt(user["id"], max_attempts=5, lock_minutes=15)
    after = store.get_admin_user(user["id"])
    assert after["failed_attempts"] == 5
    assert after["locked_until"] is not None
    store.clear_failed_attempts(user["id"])
    cleared = store.get_admin_user(user["id"])
    assert cleared["failed_attempts"] == 0
    assert cleared["locked_until"] is None
    assert cleared["last_login_at"] is not None


def test_remembered_user_is_single_row(store):
    store.save_remembered_user("owner", "token-1")
    store.save_remembered_user("owner2", "token-2")
    remembered = store.get_remembered_user()
    assert remembered["username"] == "owner2"
    store.clear_remembered_user()
    assert store.get_remembered_user() is None


def test_count_active_super_admins(store):
    first = store.create_admin_user("a", "الف", "hash", "super_admin")
    store.create_admin_user("b", "ب", "hash", "super_admin")
    store.create_admin_user("c", "ج", "hash", "viewer")
    assert store.count_active_super_admins() == 2
    assert store.count_active_super_admins(exclude_user_id=first["id"]) == 1
    store.update_admin_user(first["id"], is_active=False)
    assert store.count_active_super_admins() == 1


def test_secret_settings_are_declared():
    assert "shopapi_api_key" in SECRET_SETTING_KEYS


def test_in_memory_store_works():
    store = Store(":memory:")
    try:
        store.set_setting("auto_refresh_seconds", 10)
        assert store.get_setting("auto_refresh_seconds") == 10
    finally:
        store.close()
