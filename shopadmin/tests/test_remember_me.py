"""«مرا به خاطر بسپار»: the server's long-lived session token, kept safely.

* the saved login survives an application restart,
* the server decides whether it is still valid (expired / revoked → login window),
* logging out or unticking the box ends it,
* the password is never stored anywhere, and the token never in clear text,
* an unreachable server keeps the saved login for next time.
"""
from __future__ import annotations

import pytest

from app.auth import AuthService
from app.credentials import (
    DPAPI_PREFIX,
    backend_name,
    clear_token,
    decode_fallback,
    encode_fallback,
    keyring_available,
    load_token,
    save_token,
)
from app.store import Store

from .conftest import OWNER_PASSWORD, make_client


@pytest.fixture
def session(tmp_path, fake_api):
    """Store + auth signed in with «remember me», like a real login."""
    store = Store(tmp_path / "session.db")
    store.configure_connection("http://shopapi.test")
    store.set_setting("wizard_completed", True)
    client = make_client(fake_api, token="")
    auth = AuthService(store, client)
    auth.authenticate("owner", OWNER_PASSWORD, remember=True)
    yield store, auth
    client.close()
    store.close()


def reopen(store, fake_api) -> tuple[Store, AuthService]:
    """Simulate closing and reopening the app: new Store, client and service."""
    reopened = Store(store.path)
    return reopened, AuthService(reopened, make_client(fake_api, token=""))


def test_remember_flag_is_sent_to_the_server(session, fake_api):
    assert fake_api.login_bodies[-1]["remember"] is True


def test_remember_user_stores_the_session_token_only(session, tmp_path):
    store, auth = session
    assert auth.remember_user("owner") == "file"  # keyring disabled by conftest
    assert load_token("owner") == auth.api.token
    assert store.get_remembered_user()["username"] == "owner"
    dump = "\n".join(str(row) for row in store._all("SELECT * FROM remembered_user"))
    assert OWNER_PASSWORD not in dump and auth.api.token not in dump


def test_token_file_is_encrypted(session, tmp_path):
    _store, auth = session
    auth.remember_user("owner")
    raw = (tmp_path / "data" / "remembered.token").read_text(encoding="utf-8")
    assert auth.api.token not in raw
    assert OWNER_PASSWORD not in raw


def test_auto_login_survives_a_restart(session, fake_api):
    store, auth = session
    auth.remember_user("owner")
    reopened, reopened_auth = reopen(store, fake_api)
    try:
        result = reopened_auth.try_auto_login()
        assert result is not None
        assert result.principal.username == "owner"
        assert result.principal.role == "super_admin"
        assert reopened_auth.api.token == auth.api.token
    finally:
        reopened_auth.api.close()
        reopened.close()


def test_has_saved_session(session):
    _store, auth = session
    assert auth.has_saved_session() is False
    auth.remember_user("owner")
    assert auth.has_saved_session() is True


def test_nothing_saved_means_no_auto_login(auth):
    assert auth.try_auto_login() is None


def test_server_revoked_session_is_forgotten(session, fake_api):
    store, auth = session
    auth.remember_user("owner")
    fake_api.tokens.clear()  # expired / password changed / role changed
    assert auth.try_auto_login() is None
    assert load_token("owner") is None
    assert store.get_remembered_user() is None


def test_disabled_account_cannot_auto_login(session, fake_api):
    _store, auth = session
    auth.remember_user("owner")
    fake_api.find_staff("owner")["active"] = False
    assert auth.try_auto_login() is None
    assert load_token("owner") is None


def test_unreachable_server_keeps_the_saved_login(session, fake_api):
    _store, auth = session
    auth.remember_user("owner")
    fake_api.offline = True
    assert auth.try_auto_login() is None
    assert load_token("owner") is not None, "an offline server must not wipe the login"
    fake_api.offline = False
    assert auth.try_auto_login() is not None


def test_logout_revokes_the_saved_login_and_the_server_session(session, fake_api):
    store, auth = session
    auth.remember_user("owner")
    token = auth.api.token
    auth.logout()
    assert load_token("owner") is None
    assert store.get_remembered_user() is None
    assert token not in fake_api.tokens
    assert auth.try_auto_login() is None


def test_unticking_remember_me_forgets(session):
    _store, auth = session
    auth.remember_user("owner")
    auth.forget_remembered()
    assert auth.has_saved_session() is False


def test_deleted_token_falls_back_to_the_login_window(session):
    store, auth = session
    auth.remember_user("owner")
    clear_token("owner")  # e.g. the user cleared Credential Manager
    assert auth.try_auto_login() is None
    assert store.get_remembered_user() is None


def test_remember_without_a_session_stores_nothing(auth):
    assert auth.remember_user("owner") == "none"
    assert auth.has_saved_session() is False


# ---- storage plumbing ----------------------------------------------------------
def test_fallback_encoding_roundtrip_is_not_plain_text():
    secret = "a-very-secret-token-value"
    encoded = encode_fallback(secret)
    assert secret not in encoded
    assert decode_fallback(encoded) == secret


def test_fallback_uses_dpapi_on_windows():
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI is Windows-only")
    assert encode_fallback("x").startswith(DPAPI_PREFIX)


def test_fallback_is_username_scoped():
    assert save_token("owner", "tok-1") == "file"
    assert load_token("owner") == "tok-1"
    assert load_token("someone-else") is None
    clear_token("owner")
    assert load_token("owner") is None


def test_backend_name_is_reported():
    assert isinstance(backend_name(), str)
    import app.credentials as credentials

    assert credentials.keyring_available() is False  # disabled by conftest


def test_keyring_round_trip_when_available(monkeypatch):
    """If a real keyring exists on this machine, it must actually work."""
    monkeypatch.undo()
    if not keyring_available():
        pytest.skip("no usable OS keyring on this machine")
    ok = save_token("__probe_test__", "probe-value")
    try:
        if ok == "keyring":
            assert load_token("__probe_test__") == "probe-value"
    finally:
        clear_token("__probe_test__")


# ---- the startup decision --------------------------------------------------------
def test_startup_skips_the_login_window_when_opted_in(session, fake_api):
    store, auth = session
    store.set_setting("remember_me", True)
    auth.remember_user("owner")
    reopened, reopened_auth = reopen(store, fake_api)
    try:
        # Mirrors ShopAdminApp._try_auto_login().
        opted_in = bool(reopened.get_setting("remember_me", False))
        result = (reopened_auth.try_auto_login()
                  if opted_in and reopened_auth.has_saved_session() else None)
        assert result is not None and result.principal.username == "owner"
    finally:
        reopened_auth.api.close()
        reopened.close()


def test_startup_needs_the_setting(session):
    store, auth = session
    auth.remember_user("owner")
    store.set_setting("remember_me", False)
    assert bool(store.get_setting("remember_me", False)) is False
