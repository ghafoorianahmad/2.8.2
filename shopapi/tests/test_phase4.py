"""Phase 4: health monitor, direct owner alerts, server status additions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import control, monitor, owner_alerts
from app.db_own import OwnDB

from .conftest import FakeReader
from .test_staff_auth import bearer, owner_token

T0 = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_control():
    control.reset()
    monitor.CURRENT = None
    yield
    control.reset()
    monitor.CURRENT = None


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def make_monitor(settings, db, reader, *, threshold=2):
    settings.health_fail_threshold = threshold
    sent: list[str] = []
    clock = Clock()

    def sender(text):
        sent.append(text)
        return 1

    mon = monitor.HealthMonitor(settings, lambda: db, lambda: reader, sender=sender, clock=clock)
    return mon, sent, clock


def bots(running=True, errors=0, last_ok=T0, configured=True):
    control.register_status_provider("bots", lambda: {
        "configured": ["bale"] if configured else [],
        "platforms": {"bale": {"running": running, "consecutive_errors": errors,
                               "last_ok_at": last_ok.isoformat() if last_ok else None}},
    })


def kinds(db: OwnDB) -> list[str]:
    return [e["kind"] for e in db.list_events(0)]


# ---- monitor -----------------------------------------------------------------
def test_sql_down_after_threshold_then_up_once(settings, db):
    reader = FakeReader()
    mon, sent, _ = make_monitor(settings, db, reader)
    assert mon.tick() == []
    reader.down = True
    assert mon.tick() == []                      # 1 bad check: not yet
    assert mon.tick() == ["health_sql_down"]     # 2nd: down
    assert mon.tick() == []                      # stays down, no repeat
    reader.down = False
    assert mon.tick() == ["health_sql_up"]
    assert mon.tick() == []
    assert len(sent) == 2 and "SQL" in sent[0]
    assert kinds(db) == ["health_sql_down", "health_sql_up"]


def test_no_launcher_means_bot_checks_not_applicable(settings, db):
    mon, sent, _ = make_monitor(settings, db, FakeReader(), threshold=1)
    assert mon.tick() == []
    snap = mon.snapshot()["checks"]
    assert snap["bot"]["ok"] is None and snap["bale"]["ok"] is None and snap["tg"]["ok"] is None
    assert snap["sql"]["ok"] is True and sent == []


def test_bot_stopped_alerts_directly(settings, db):
    mon, sent, _ = make_monitor(settings, db, FakeReader(), threshold=1)
    bots(running=False)
    assert mon.tick() == ["health_bot_down"]
    assert "ربات بله" in sent[0]
    bots(running=True)
    assert mon.tick() == ["health_bot_up"]


def test_bale_unreachable_needs_errors_and_silence(settings, db):
    mon, _, clock = make_monitor(settings, db, FakeReader(), threshold=1)
    bots(errors=5, last_ok=T0)
    clock.now = T0 + timedelta(minutes=1)
    assert mon.tick() == []                      # recent success: still fine
    clock.now = T0 + timedelta(minutes=10)
    assert mon.tick() == ["health_bale_down"]
    bots(errors=0, last_ok=clock.now)
    assert mon.tick() == ["health_bale_up"]


def test_bale_without_token_is_ignored(settings, db):
    mon, _, _ = make_monitor(settings, db, FakeReader(), threshold=1)
    bots(running=False, configured=False)
    assert mon.tick() == []


def test_tg_worker_stale_status(settings, db):
    mon, _, clock = make_monitor(settings, db, FakeReader(), threshold=1)
    settings.tg_status_stale_minutes = 20
    assert mon.tick() == []                      # never reported: not installed
    db.set_state(monitor.TG_STATUS_KEY, json.dumps({"connected": True, "at": T0.isoformat()}), "w")
    clock.now = T0 + timedelta(minutes=5)
    assert mon.tick() == []
    clock.now = T0 + timedelta(minutes=30)
    assert mon.tick() == ["health_tg_down"]
    db.set_state(monitor.TG_STATUS_KEY, json.dumps({"at": clock.now.isoformat()}), "w")
    assert mon.tick() == ["health_tg_up"]


def test_sender_failure_does_not_break_tick(settings, db):
    reader = FakeReader()
    reader.down = True

    def boom(_text):
        raise RuntimeError("no network")

    mon = monitor.HealthMonitor(settings, lambda: db, lambda: reader, sender=boom)
    settings.health_fail_threshold = 1
    mon.threshold = 1
    assert mon.tick() == ["health_sql_down"]


# ---- owner alerts --------------------------------------------------------------
def test_owner_chat_ids_parsing():
    assert owner_alerts.owner_chat_ids("123, bale:456;telegram:789 -100") == ["123", "456", "-100"]
    assert owner_alerts.owner_chat_ids("") == []


def test_send_owner_alert_posts_without_leaking(monkeypatch, caplog):
    monkeypatch.setenv("BALE_TOKEN", "111:SECRETTOKENSECRETTOKENxx")
    monkeypatch.setenv("ADMIN_CHAT_IDS", "bale:5,6")
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200 if json.loads(request.content)["chat_id"] == "5" else 500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert owner_alerts.send_owner_alert("سلام", client=client) == 1
    assert [body["chat_id"] for _, body in seen] == ["5", "6"]
    assert seen[0][0].endswith("/sendMessage")
    assert "SECRETTOKEN" not in caplog.text


def test_send_owner_alert_unconfigured(monkeypatch):
    monkeypatch.delenv("BALE_TOKEN", raising=False)
    assert owner_alerts.send_owner_alert("x") == 0


# ---- status endpoint -------------------------------------------------------------
def test_status_includes_health_and_tg_worker(client, db, settings, reader):
    owner = owner_token(client)
    body = client.get("/admin/server/status", headers=bearer(owner)).json()
    assert body["health"] is None and body["telegram_worker"] is None

    db.set_state(monitor.TG_STATUS_KEY, json.dumps({
        "connected": True, "proxy": "1.2.3.4:443 (faketls)", "proxy_id": 3,
        "login_required": False, "error": "", "at": T0.isoformat(), "extra": "dropped"}), "w")
    mon, _, _ = make_monitor(settings, db, reader)
    mon.tick()
    monitor.CURRENT = mon
    body = client.get("/admin/server/status", headers=bearer(owner)).json()
    assert body["telegram_worker"]["connected"] is True
    assert "extra" not in body["telegram_worker"] and "proxy_id" not in body["telegram_worker"]
    assert body["health"]["checks"]["sql"]["ok"] is True


def test_health_settings_are_editable():
    assert "HEALTH_CHECK_SECONDS" in control.EDITABLE
    assert control.validate_settings({"HEALTH_FAIL_THRESHOLD": "3"}) == {}
    assert control.validate_settings({"HEALTH_FAIL_THRESHOLD": "0"})
