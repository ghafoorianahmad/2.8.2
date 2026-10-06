"""Notifications: server event feed → tray balloon, sound, unread badges."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.notifications import (  # noqa: E402
    KIND_CUSTOMER,
    KIND_ORDER,
    KIND_RECEIPT,
    EventWatcher,
    TrayNotifier,
    notice_for,
    summarize,
)

from .conftest import make_client  # noqa: E402


def _pump(app, ms: int = 5000) -> None:
    from PySide6.QtCore import QThreadPool

    for _ in range(10):
        app.processEvents()
    QThreadPool.globalInstance().waitForDone(ms)
    for _ in range(30):
        app.processEvents()


# ---- texts -----------------------------------------------------------------------
def test_notice_texts_are_persian_and_carry_no_personal_data():
    for kind in (KIND_CUSTOMER, KIND_ORDER, KIND_RECEIPT):
        notice = notice_for({"kind": kind, "ref_id": 12})
        assert notice is not None
        assert "۱۲" in notice.body or kind == KIND_CUSTOMER
        assert not any(ch.isascii() and ch.isalpha() for ch in notice.title + notice.body)


def test_decisions_do_not_notify():
    assert notice_for({"kind": "payment_approved", "ref_id": 1}) is None
    assert notice_for({"kind": "customer_rejected", "ref_id": 1}) is None


def test_notice_targets():
    assert notice_for({"kind": KIND_CUSTOMER}).target == ("customers", "pending")
    assert notice_for({"kind": KIND_RECEIPT, "ref_id": 1}).target == ("orders", "receipt_uploaded")


def test_a_burst_becomes_one_summary():
    notices = [notice_for({"kind": k, "ref_id": 1})
               for k in (KIND_CUSTOMER, KIND_CUSTOMER, KIND_RECEIPT)]
    summary = summarize(notices)
    assert "۲ مشتری جدید" in summary.body
    assert "۱ فیش جدید" in summary.body


# ---- tray notifier ---------------------------------------------------------------
@pytest.fixture
def notifier(store, admin_qapp, monkeypatch):
    import app.notifications as module

    sounds = []
    monkeypatch.setattr(module, "play_notification_sound", lambda: sounds.append(1))
    tray = TrayNotifier(store)
    tray.sounds = sounds
    yield tray
    tray.hide()


def test_unread_counters_and_mark_seen(notifier):
    seen = []
    notifier.counts_changed.connect(seen.append)
    notifier.handle_events([
        {"kind": KIND_CUSTOMER, "ref_id": 1},
        {"kind": KIND_RECEIPT, "ref_id": 5},
        {"kind": "payment_approved", "ref_id": 5},
    ])
    assert notifier.unread[KIND_CUSTOMER] == 1
    assert notifier.unread[KIND_RECEIPT] == 1
    assert notifier.total_unread() == 2
    assert seen[-1][KIND_CUSTOMER] == 1
    notifier.mark_seen(KIND_CUSTOMER)
    assert notifier.unread[KIND_CUSTOMER] == 0
    assert notifier.total_unread() == 1


def test_sound_follows_the_setting(notifier, store):
    notifier.handle_events([{"kind": KIND_ORDER, "ref_id": 3}])
    assert notifier.sounds == [1]
    store.set_setting("notify_sound", False)
    notifier.handle_events([{"kind": KIND_ORDER, "ref_id": 4}])
    assert notifier.sounds == [1]


def test_only_decision_events_make_no_noise(notifier):
    assert notifier.handle_events([{"kind": "payment_rejected", "ref_id": 1}]) == []
    assert notifier.sounds == []
    assert notifier.total_unread() == 0


def test_clicking_a_balloon_opens_the_right_page(notifier):
    opened = []
    notifier.open_requested.connect(lambda page, f: opened.append((page, f)))
    notifier.handle_events([{"kind": KIND_RECEIPT, "ref_id": 9}])
    notifier._on_message_clicked()
    assert opened == [("orders", "receipt_uploaded")]


# ---- event watcher -----------------------------------------------------------------
def test_watcher_skips_history_then_reports_new_events(fake_api, admin_qapp):
    fake_api.add_event(KIND_CUSTOMER, 1)  # happened before the app started
    client = make_client(fake_api)
    watcher = EventWatcher("http://shopapi.test", "owner-token", client=client)
    got = []
    watcher.events_arrived.connect(got.append)
    try:
        watcher.poll()
        _pump(admin_qapp)
        assert got == [] and watcher.last_id == 1

        fake_api.add_event(KIND_RECEIPT, 7)
        watcher.poll()
        _pump(admin_qapp)
        assert [e["kind"] for e in got[0]] == [KIND_RECEIPT]
        assert watcher.last_id == 2

        watcher.poll()
        _pump(admin_qapp)
        assert len(got) == 1  # nothing new, nothing emitted
    finally:
        watcher.stop()
        client.close()


def test_watcher_stops_when_the_session_is_gone(fake_api, admin_qapp):
    client = make_client(fake_api)
    watcher = EventWatcher("http://shopapi.test", "owner-token", client=client)
    lost = []
    watcher.session_lost.connect(lambda: lost.append(True))
    try:
        watcher.start()
        _pump(admin_qapp)
        fake_api.tokens.clear()
        watcher.poll()
        _pump(admin_qapp)
        assert lost == [True]
        assert watcher.running is False
    finally:
        watcher.stop()
        client.close()


def test_watcher_reports_an_unreachable_server(fake_api, admin_qapp):
    client = make_client(fake_api)
    watcher = EventWatcher("http://shopapi.test", "owner-token", client=client)
    states = []
    watcher.reachability_changed.connect(states.append)
    try:
        fake_api.offline = True
        watcher.poll()
        _pump(admin_qapp)
        fake_api.offline = False
        watcher.poll()
        _pump(admin_qapp)
        assert states == [False, True]
    finally:
        watcher.stop()
        client.close()


# ---- main window integration ----------------------------------------------------------
def test_sidebar_badges_and_close_to_tray(tmp_path, fake_api, notifier, admin_qapp):
    from app.auth import AuthService
    from app.store import Store
    from app.ui.context import AppContext
    from app.ui.main_window import MainWindow

    store = Store(tmp_path / "mw.db")
    store.configure_connection("http://shopapi.test")
    client = make_client(fake_api)
    auth = AuthService(store, client)
    principal = auth.authenticate("owner", "Secret123").principal
    context = AppContext(store=store, auth=auth, api=client, principal=principal,
                         notifier=notifier)
    window = MainWindow(context)
    try:
        notifier.handle_events([{"kind": KIND_RECEIPT, "ref_id": 1},
                                {"kind": KIND_ORDER, "ref_id": 2}])
        assert "(۲)" in window._nav_buttons["orders"].text()
        window.navigate("orders")
        assert "(" not in window._nav_buttons["orders"].text()
        assert notifier.unread[KIND_RECEIPT] == 0

        closes = []
        window.close_requested.connect(lambda: closes.append(True))
        assert window.allow_close is False
        window.close()
        assert closes == [True]
        window.allow_close = True
    finally:
        window.close()
        client.close()
        store.close()
