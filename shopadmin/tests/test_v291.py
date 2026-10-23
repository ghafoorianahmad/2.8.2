"""v2.9.1: the remembered password (DPAPI) and the eye in the login window, a new
look applied at once, the price-list page (corrections, held prices, channel
posts), notifications of the new events, the proxy table, the backup folder."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLineEdit  # noqa: E402

from app import credentials, notifications  # noqa: E402
from app import server_setup as setup  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import appearance  # noqa: E402
from app.ui.pages import pricelist  # noqa: E402

from .conftest import OWNER_PASSWORD, make_client  # noqa: E402

needs_dpapi = pytest.mark.skipif(not credentials.dpapi_available(),
                                 reason="Windows DPAPI only")


# ---- remembered password ---------------------------------------------------------------------
@needs_dpapi
def test_password_is_kept_with_dpapi_only(tmp_path):
    assert credentials.save_password("owner", "S3cret-pass")
    raw = (tmp_path / "data" / credentials.PASSWORD_FILENAME).read_text(encoding="utf-8")
    assert "S3cret-pass" not in raw and credentials.DPAPI_PREFIX in raw
    assert credentials.load_password("owner") == "S3cret-pass"
    assert credentials.load_password("someone-else") is None
    credentials.clear_password()
    assert credentials.load_password("owner") is None


def test_nothing_is_kept_without_dpapi(monkeypatch):
    monkeypatch.setattr(credentials, "_dpapi", lambda data, protect: None)
    assert credentials.save_password("owner", "pw") is False
    assert credentials.load_password("owner") is None


@needs_dpapi
def test_after_logout_only_login_is_needed(tmp_path, admin_qapp, fake_api):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login_saved.db")
    client = make_client(fake_api, token="")
    auth = AuthService(store, client)
    try:
        result = auth.authenticate("owner", OWNER_PASSWORD, remember=True)
        assert result is not None
        auth.remember_user("owner")
        auth.remember_password("owner", OWNER_PASSWORD)
        auth.logout()                                   # «خروج»
        window = LoginWindow(store, auth)
        window._prefill_remembered_username()
        assert window.username_input.text() == "owner"
        assert window.password_input.text() == OWNER_PASSWORD
        assert window.password_input.echoMode() == QLineEdit.EchoMode.Password
        assert not window.eye_action.isEnabled()           # a saved password is never shown
        window._toggle_eye()
        assert window.password_input.echoMode() == QLineEdit.EchoMode.Password
        # typing a new password: only what is typed stays, and the eye works again
        window.password_input.setText(OWNER_PASSWORD + "x")
        window._password_typed(OWNER_PASSWORD + "x")
        assert window.password_input.text() == "x" and window.eye_action.isEnabled()
        window._toggle_eye()
        assert window.password_input.echoMode() == QLineEdit.EchoMode.Normal
        window.close()
        # unticking «مرا به خاطر بسپار» forgets the password too
        auth.forget_remembered()
        assert auth.remembered_password("owner") is None
    finally:
        client.close()
        store.close()


# ---- appearance -------------------------------------------------------------------------------
def test_a_new_look_is_applied_without_a_restart(monkeypatch):
    calls = []

    class Context:
        apply_look = staticmethod(lambda: calls.append("live"))
        restart_app = staticmethod(lambda: calls.append("restart"))

    monkeypatch.setattr("PySide6.QtCore.QTimer.singleShot", lambda _ms, fn: fn())
    appearance.offer_restart(None, Context())
    assert calls == ["live"]


# ---- price list -------------------------------------------------------------------------------
def test_price_cells_show_corrections_and_held_prices():
    corrected = {"price_rial": 705_000_000, "price_flag": "correction",
                 "flag_note": "A17 128-6 70.000", "orig_price_rial": 725_000_000,
                 "raval": 70500, "raval_estimated": 1}
    text, _color, tip = pricelist.price_text(corrected)
    assert "اصلاحیه" in text and "A17 128-6" in tip
    assert "روال تخمینی" in pricelist.raval_text(corrected)
    held = {"price_rial": 795_000_000, "pending_price_rial": 955_000_000,
            "pending_source": "list", "price_flag": "held"}
    text, _color, tip = pricelist.price_text(held)
    assert "منتظر تأیید" in text and "۱۰٪" in tip
    assert pricelist.note_summary({"kind": "correction", "result": {
        "applied": 3, "held": 1, "unmatched": ["Z9 128-4 1.000"]}}).count("؛") == 2
    assert dict(pricelist.FILTERS)["held"] == "قیمت منتظر تأیید"


# ---- notifications ----------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["price_held", "price_correction_unmatched",
                                  "sales_closed_channel"])
def test_problem_events_are_warnings(kind):
    notice = notifications.notice_for({"kind": kind, "ref_id": 3})
    assert notice is not None and notice.warning


def test_new_channel_and_correction_notices():
    assert notifications.notice_for({"kind": "telegram_channel_new", "ref_id": 5}).target == (
        "server", "")
    assert notifications.notice_for({"kind": "pricelist_corrected", "ref_id": 1,
                                     "actor": "worker"}) is not None
    assert "price_held" in notifications.PRICE_EVENT_KINDS
    assert "pricelist_imported" in notifications.PRICE_EVENT_KINDS


# ---- backup folder ----------------------------------------------------------------------------
def test_backup_folder_test_writes_and_cleans_up(tmp_path):
    target = tmp_path / "share"
    result = setup.test_backup_folder(str(target))
    assert result["ok"] and target.is_dir() and not list(target.iterdir())
    assert not setup.test_backup_folder("relative/path")["ok"]
    assert not setup.test_backup_folder("")["ok"]


def test_backup_passphrase_rules():
    phrase = setup.new_backup_passphrase()
    assert len(setup.normalised_passphrase(phrase)) == 32
    assert setup.normalised_passphrase("AB-CD EF") == "ABCDEF"
