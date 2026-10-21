"""Phase 4: health notices in the tray, the «سازه حساب» reminder, autostart,
server page rows for the Telegram worker and the health monitor."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app import autostart, sazeh_watch  # noqa: E402
from app.notifications import KIND_ORDER, Notice, TrayNotifier, notice_for  # noqa: E402
from app.ui.pages.server import health_text, telegram_text  # noqa: E402


# ---- notices -------------------------------------------------------------------
def test_health_notices():
    down = notice_for({"kind": "health_sql_down"})
    assert down.warning and down.is_server and "SQL" in down.body
    up = notice_for({"kind": "health_bot_up"})
    assert not up.warning and "دوباره" in up.body
    assert notice_for({"kind": "health_nope_down"}) is None
    assert notice_for({"kind": "health_sql_sideways"}) is None


def test_server_warnings_open_the_price_list():
    held = notice_for({"kind": "pricelist_held", "ref_id": 4})
    assert held.warning and held.target == ("pricelist", "")
    assert notice_for({"kind": "proxies_all_dead"}).warning


@pytest.fixture
def notifier(store, admin_qapp, monkeypatch):
    import app.notifications as module

    monkeypatch.setattr(module, "play_notification_sound", lambda: None)
    tray = TrayNotifier(store)
    shown = []
    monkeypatch.setattr(tray, "show_notice", lambda n, _o=tray.show_notice: (shown.append(n), _o(n)))
    tray.shown = shown
    yield tray
    tray.hide()


def test_server_problem_wins_the_balloon_and_is_not_counted(notifier):
    counts = []
    notifier.counts_changed.connect(counts.append)
    notifier.handle_events([{"kind": KIND_ORDER, "ref_id": 1}, {"kind": "health_bale_down"}])
    assert notifier.shown[-1].kind == "health_bale_down"
    assert notifier.unread[KIND_ORDER] == 1
    assert "health_bale_down" not in notifier.unread
    assert notifier.total_unread() == 1


def test_health_only_does_not_touch_counters(notifier):
    counts = []
    notifier.counts_changed.connect(counts.append)
    notifier.handle_events([{"kind": "health_tg_down"}])
    assert counts == [] and notifier.total_unread() == 0
    assert notifier.shown[-1].warning


# ---- «سازه حساب» watcher ---------------------------------------------------------------
def test_prefix_matching():
    prefixes = sazeh_watch.parse_prefixes(sazeh_watch.DEFAULT_PREFIXES)
    assert sazeh_watch.is_running(["explorer.exe", "Sazeh Hesab Integrated 1405.06.05.exe"], prefixes)
    assert sazeh_watch.is_running(["SAZEHHESAB.EXE"], prefixes)
    assert not sazeh_watch.is_running(["Telegram_Bot.exe", "sqlservr.exe"], prefixes)


def test_watcher_fires_only_on_start(admin_qapp):
    names = [["Sazeh Hesab Integrated 1405.06.05.exe"]]
    watcher = sazeh_watch.SazehWatcher(lister=lambda: names[0], run_in_thread=False)
    fired = []
    watcher.started.connect(lambda: fired.append(1))
    watcher.check()                       # already open when we start: no reminder
    assert fired == []
    names[0] = ["explorer.exe"]
    watcher.check()
    names[0] = ["Sazeh Hesab Integrated 1405.06.05.exe"]
    watcher.check()                       # opened now
    watcher.check()                       # still open: once only
    assert fired == [1]


def test_watcher_ignores_a_failed_listing(admin_qapp):
    def boom():
        raise OSError("tasklist missing")

    watcher = sazeh_watch.SazehWatcher(lister=boom, run_in_thread=False)
    watcher.check()
    assert watcher.was_running is None


def test_custom_prefixes_and_empty_falls_back(admin_qapp):
    assert sazeh_watch.SazehWatcher("MyAcc", lister=list).prefixes == ["myacc"]
    assert sazeh_watch.SazehWatcher("  ", lister=list).prefixes == ["sazeh hesab", "sazehhesab"]


def test_pending_summary_and_text(api, fake_api):
    orders, customers = sazeh_watch.pending_summary(api)
    assert orders >= 0 and customers >= 0
    assert sazeh_watch.summary_text(3, 2) == "۳ سفارش جدید، ۲ مشتری در انتظار تأیید. برای دیدن، اینجا را بزنید."
    assert sazeh_watch.summary_text(0, 1).startswith("۱ مشتری")
    assert "منتظری" in sazeh_watch.summary_text(0, 0)


def test_sazeh_notice_targets():
    assert Notice("sazeh_orders", "", "", None).target == ("orders", "awaiting_payment")
    assert Notice("sazeh_customers", "", "", None).target == ("customers", "pending")


# ---- autostart -------------------------------------------------------------------------
class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_autostart_round_trip():
    reg = FakeRegistry()
    assert not autostart.is_enabled(reg)
    autostart.set_enabled(True, reg)
    assert autostart.is_enabled(reg)
    assert reg.values["ShopAdmin"].endswith("--tray")
    autostart.set_enabled(False, reg)
    assert not autostart.is_enabled(reg) and reg.values == {}
    reg.values["ShopAdmin"] = r"C:\old\ShopAdmin.exe"   # without --tray: not ours
    assert not autostart.is_enabled(reg)


def test_store_defaults(store):
    assert store.get_setting("sazeh_watch") is True
    assert "Sazeh Hesab" in store.get_setting("sazeh_process_names")


# ---- server page rows ---------------------------------------------------------------------
def test_telegram_row():
    assert telegram_text(None)[1].startswith("روشن نشده")      # v2.9.0: bundled, off by default
    key, text, color = telegram_text({"connected": True, "proxy": "1.2.3.4:443 (faketls)",
                                      "at": "2026-10-12T08:00:00+00:00"})
    assert key == "telegram" and "1.2.3.4:443" in text and color is not None
    assert "ورود به حساب تلگرام" in telegram_text({"login_required": True, "at": None})[1]
    assert "قطع" in telegram_text({"connected": False, "error": "TimeoutError"})[1]


def test_health_row():
    assert "هنوز" in health_text(None)[1]
    _, text, _ = health_text({"checked_at": "2026-10-12T08:00:00+00:00", "checks": {
        "sql": {"ok": True, "down": False, "fails": 0},
        "bot": {"ok": False, "down": True, "fails": 3},
        "bale": {"ok": None, "down": False, "fails": 0},
        "tg": {"ok": None, "down": False, "fails": 0},
    }})
    assert "SQL حسابداری: سالم" in text and "ربات بله: از کار افتاده" in text
    assert "اتصال به بله" not in text and "آخرین بررسی" in text
