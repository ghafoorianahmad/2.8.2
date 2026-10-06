"""Regression tests for «مرا به خاطر بسپار» (persistent auto-login).

Issue 1: the owner ticked "remember me", closed the app, and was asked for the
password again. These tests pin the behaviour down:

* the saved login survives an application restart,
* it does NOT expire with time,
* logging out (or unticking the box) revokes it,
* the password is never stored anywhere,
* a failure in the saved state falls back to the login window, never to an error.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.auth import NO_EXPIRY, AuthService, hash_password
from app.credentials import (
    backend_name,
    clear_token,
    decode_fallback,
    encode_fallback,
    keyring_available,
    load_token,
    save_token,
)
from app.store import Store


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Point the token file fallback at a temp directory and disable keyring."""
    import app.credentials as credentials

    monkeypatch.setattr(credentials, "keyring_available", lambda: False)
    monkeypatch.setattr(credentials, "data_dir", lambda: tmp_path)
    return credentials


@pytest.fixture
def session(tmp_path, vault):
    """A store + auth pair wired to the isolated token vault."""
    store = Store(tmp_path / "session.db")
    store.configure_connection("http://127.0.0.1:8000", "key")
    store.set_setting("wizard_completed", True)
    auth = AuthService(store)
    auth.create_first_super_admin("owner", "مالک فروشگاه", "Secret123")
    yield store, auth
    store.close()


# --------------------------------------------------------------------------
# the token that is saved
# --------------------------------------------------------------------------
def test_remember_user_stores_a_token_and_no_password(session):
    store, auth = session
    backend = auth.remember_user(1)
    assert backend == "file"  # keyring disabled by the fixture

    token = load_token("owner")
    assert token and len(token) > 20

    # The database must contain only a hash, never the token or the password.
    row = store.get_session_token(1)
    assert row is not None
    assert token not in row["token_hash"]
    assert "Secret123" not in str(row)
    assert store.get_remembered_user()["username"] == "owner"


def test_stored_token_file_is_never_plain_text(session, vault):
    _store, auth = session
    auth.remember_user(1)
    token = load_token("owner")
    raw = (vault.data_dir() / "remembered.token").read_text(encoding="utf-8")
    assert token not in raw, "the token must never be written in clear text"
    assert "Secret123" not in raw


def test_password_is_hashed_and_not_recoverable(session):
    store, _auth = session
    row = store.get_admin_user_by_username("owner")
    assert row["password_hash"].startswith("$2")
    assert "Secret123" not in row["password_hash"]


# --------------------------------------------------------------------------
# persistence across a restart
# --------------------------------------------------------------------------
def test_auto_login_survives_a_restart(session):
    """Simulate closing and reopening the app: new Store and new AuthService."""
    store, auth = session
    auth.remember_user(1)

    # ---- "restart" ----
    reopened = Store(store.path)
    reopened_auth = AuthService(reopened)
    try:
        result = reopened_auth.try_auto_login()
        assert result is not None, "the saved login was not restored"
        assert result.principal.username == "owner"
        assert result.principal.role == "super_admin"
    finally:
        reopened.close()


def test_has_saved_session_reports_readiness(session):
    _store, auth = session
    assert auth.has_saved_session() is False
    auth.remember_user(1)
    assert auth.has_saved_session() is True


def test_auto_login_returns_none_when_nothing_was_saved(store, super_admin):
    assert AuthService(store).try_auto_login() is None


# --------------------------------------------------------------------------
# it must NOT expire
# --------------------------------------------------------------------------
def test_token_never_expires_by_default(session):
    store, auth = session
    auth.remember_user(1)
    assert store.get_session_token(1)["expires_at"] == NO_EXPIRY


def test_auto_login_still_works_a_year_later(session, monkeypatch):
    """Mock the clock forward well past the old 7-day limit."""
    store, auth = session
    auth.remember_user(1)

    import app.auth as auth_module

    real_datetime = auth_module.datetime

    class FarFutureDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(days=3650)

    monkeypatch.setattr(auth_module, "datetime", FarFutureDatetime)
    reopened = Store(store.path)
    reopened_auth = AuthService(reopened)
    try:
        # Pin the patched module onto the new service's module too.
        result = reopened_auth.try_auto_login()
        assert result is not None, "a remembered session must not expire with time"
        assert result.principal.username == "owner"
    finally:
        reopened.close()


def test_an_explicitly_dated_token_does_expire(session):
    """The ``days=`` argument still allows a temporary session (used in tests)."""
    store, auth = session
    token = auth.create_remember_token(1, days=7)
    assert store.get_session_token(1)["expires_at"] != NO_EXPIRY

    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
    store.save_session_token(1, store.get_session_token(1)["token_hash"], past)

    from app.auth import AuthError

    with pytest.raises(AuthError):
        auth.authenticate_with_token(1, token)


# --------------------------------------------------------------------------
# revoking
# --------------------------------------------------------------------------
def test_logout_revokes_the_saved_login(session, vault):
    store, auth = session
    auth.remember_user(1)
    assert load_token("owner")

    # This is exactly what ShopAdminApp.logout() does.
    clear_token("owner")
    auth.forget_remembered()

    assert load_token("owner") is None
    assert store.get_remembered_user() is None
    assert store.get_session_token(1) is None
    assert AuthService(store).try_auto_login() is None


def test_unticking_remember_me_revokes_the_login(session, vault):
    store, auth = session
    auth.remember_user(1)
    # Unticking on a later login clears both stores.
    clear_token("owner")
    auth.forget_remembered()
    assert auth.has_saved_session() is False


def test_deleting_the_token_breaks_auto_login_without_an_error(session, vault):
    store, auth = session
    auth.remember_user(1)
    clear_token("owner")  # e.g. the user cleared Credential Manager

    result = auth.try_auto_login()
    assert result is None
    assert store.get_remembered_user() is None, "stale state must be cleaned up"


def test_disabled_account_cannot_auto_login(session, vault):
    store, auth = session
    auth.remember_user(1)
    store.update_admin_user(1, is_active=False)

    assert auth.try_auto_login() is None
    assert load_token("owner") is None


def test_tampered_token_hash_is_rejected(session, vault):
    store, auth = session
    auth.remember_user(1)
    with store._cursor() as cursor:
        cursor.execute("UPDATE remembered_sessions SET token_hash='deadbeef' WHERE user_id=1")

    assert auth.try_auto_login() is None


# --------------------------------------------------------------------------
# the lockout behaviour must be unchanged
# --------------------------------------------------------------------------
def test_lockout_still_applies(session):
    _store, auth = session
    auth.create_user("staff", "کارمند", "Secret123", "operator")
    from app.auth import MAX_FAILED_ATTEMPTS, AuthError

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError) as exc:
            auth.authenticate("staff", "wrong")
        assert exc.value.code == "invalid_credentials"
    with pytest.raises(AuthError) as exc:
        auth.authenticate("staff", "wrong")
    assert exc.value.code == "user_locked"


# --------------------------------------------------------------------------
# storage plumbing
# --------------------------------------------------------------------------
def test_obfuscation_roundtrip_is_not_plain_text():
    secret = "a-very-secret-token-value"
    encoded = encode_fallback(secret)
    assert secret not in encoded
    assert decode_fallback(encoded) == secret


def test_fallback_is_username_scoped(session, vault):
    _store, auth = session
    auth.remember_user(1)
    assert load_token("owner") is not None
    # A different username must not pick up the token.
    assert load_token("someone-else") is None


def test_save_and_clear_token_roundtrip(tmp_path, monkeypatch, vault):
    assert save_token("user1", "tok") == "file"
    assert load_token("user1") == "tok"
    clear_token("user1")
    assert load_token("user1") is None


def test_backend_name_is_reported(vault):
    assert isinstance(backend_name(), str)
    # The `vault` fixture disables the keyring, so the module-level helper that
    # the *production* code calls must report False.
    import app.credentials as credentials

    assert credentials.keyring_available() is False


def test_keyring_round_trip_when_available():
    """If a real keyring exists on this machine, it must actually work.

    Skipped when there is no usable backend (e.g. a headless CI machine).
    """
    if not keyring_available():
        pytest.skip("no usable OS keyring on this machine")
    ok = save_token("__probe_test__", "probe-value")
    try:
        if ok == "keyring":
            assert load_token("__probe_test__") == "probe-value"
    finally:
        clear_token("__probe_test__")


# --------------------------------------------------------------------------
# the startup decision: skip the login window
# --------------------------------------------------------------------------
def test_startup_should_skip_the_login_window(session):
    """The controller's condition for going straight to the dashboard."""
    store, auth = session
    store.set_setting("remember_me", True)
    assert auth.remember_user(1) in ("file", "keyring")

    # This mirrors ShopAdminApp._try_auto_login().
    opted_in = bool(store.get_setting("remember_me", False))
    can_restore = auth.has_saved_session()
    result = auth.try_auto_login() if (opted_in and can_restore) else None

    assert opted_in is True
    assert can_restore is True
    assert result is not None
    assert result.principal.username == "owner"


def test_startup_does_not_auto_login_without_the_setting(session):
    """A saved token alone is not enough: the user must have opted in."""
    store, auth = session
    auth.remember_user(1)
    store.set_setting("remember_me", False)

    opted_in = bool(store.get_setting("remember_me", False))
    assert opted_in is False
    # The controller therefore shows the login window.
    assert (auth.try_auto_login() if opted_in else None) is None


def test_startup_does_not_auto_login_when_the_token_is_gone(session, vault):
    store, auth = session
    store.set_setting("remember_me", True)
    auth.remember_user(1)
    clear_token("owner")

    assert auth.has_saved_session() is False
    assert auth.try_auto_login() is None


def test_auto_login_walks_through_a_restart_without_the_password(session):
    """End-to-end: opt in, 'restart', land signed in — never typing a password."""
    store, auth = session
    store.set_setting("remember_me", True)
    auth.remember_user(1)

    # ---- "close the app, reopen it" ----
    reopened = Store(store.path)
    reopened_auth = AuthService(reopened)
    try:
        opened = reopened.get_setting("remember_me", False)
        assert opened is True
        result = reopened_auth.try_auto_login()
        assert result is not None
        assert result.principal.user_id == 1
        assert result.principal.role == "super_admin"
    finally:
        reopened.close()
