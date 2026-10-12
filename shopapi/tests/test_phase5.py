"""Phase 5: suspicious-activity alerts, backup health, sa refused, no Options.ini."""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from app import control, monitor, security_watch
from app.config import Settings

from .conftest import FakeReader, h, register_and_approve, seed_products
from .test_phase4 import T0, make_monitor
from .test_staff_auth import bearer, login, owner_token

APP_DIR = Path(__file__).resolve().parent.parent / "app"


class Sender:
    def __init__(self):
        self.sent: list[str] = []

    def __call__(self, text):
        self.sent.append(text)
        return 1


class Tick:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def watch():
    sender, clock = Sender(), Tick()
    w = security_watch.SecurityWatch(sender=sender, clock=clock, background=False)
    security_watch.reset(w)
    yield w, sender, clock
    security_watch.reset()


@pytest.fixture(autouse=True)
def clean_control():
    control.reset()
    monitor.CURRENT = None
    yield
    control.reset()
    monitor.CURRENT = None


def actions(db) -> list[str]:
    return [row["action"] for row in db.list_audit(100)]


# ---- the watcher ----------------------------------------------------------------
def test_alert_after_threshold_once_per_hour(db, watch):
    w, sender, clock = watch
    for _ in range(2):
        assert not w.report(db, "contact_not_own", "bale:123456789")
    assert w.report(db, "contact_not_own", "bale:123456789")     # 3rd within the hour
    assert not w.report(db, "contact_not_own", "bale:123456789")  # no repeat
    assert len(sender.sent) == 1
    assert "…6789" in sender.sent[0] and "123456789" not in sender.sent[0]
    assert [e["kind"] for e in db.list_events(0)] == ["security_alert"]
    assert actions(db).count("suspicious_contact_not_own") == 4
    clock.now += 3601
    for _ in range(2):
        w.report(db, "contact_not_own", "bale:123456789")
    assert w.report(db, "contact_not_own", "bale:123456789")
    assert len(sender.sent) == 2


def test_window_forgets_old_reports(db, watch):
    w, sender, clock = watch
    w.report(db, "order_probe", "bale:1")
    clock.now += 3601
    for _ in range(4):
        assert not w.report(db, "order_probe", "bale:1")
    assert sender.sent == []


def test_global_cap_and_unknown_kind(db, watch):
    w, sender, _ = watch
    for i in range(security_watch.MAX_PER_HOUR + 3):
        w.report(db, "account_locked", f"10.0.0.{i}")
    assert len(sender.sent) == security_watch.MAX_PER_HOUR
    assert not w.report(db, "anything", "x")


# ---- wiring ---------------------------------------------------------------------
def test_bot_report_endpoint(client, db, watch):
    _, sender, _ = watch
    body = {"kind": "rate_limited", "platform": "bale", "chat_id": "555"}
    for _ in range(3):
        assert client.post("/security/report", json=body, headers=h("bot")).status_code == 204
    assert len(sender.sent) == 1
    assert client.post("/security/report", json=body, headers=h("site")).status_code == 403
    bad = dict(body, kind="login_failed")   # not a bot kind
    assert client.post("/security/report", json=bad, headers=h("bot")).status_code == 422
    assert client.post("/security/report", json=body).status_code == 401


def test_order_probe_is_reported(client, db, reader, watch):
    _, sender, _ = watch
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", json={"platform": "bale", "chat_id": "111",
                                         "items": [{"kala_code": 101, "qty": 1}]},
                        headers=h("bot")).json()
    for _ in range(5):
        r = client.get(f"/orders/{order['id']}", params={"platform": "bale", "chat_id": "999"},
                       headers=h("bot"))
        assert r.status_code == 404
    assert "suspicious_order_probe" in actions(db)
    assert len(sender.sent) == 1
    # the owner's own lookups are not suspicious
    assert client.get(f"/orders/{order['id']}", params={"platform": "bale", "chat_id": "111"},
                      headers=h("bot")).status_code == 200


def test_staff_lockout_alerts(client, db, watch):
    _, sender, _ = watch
    owner_token(client)
    for _ in range(5):
        login(client, password="wrong-password-1")
    assert "suspicious_account_locked" in actions(db)
    assert any("قفل" in text for text in sender.sent)


# ---- backup health ----------------------------------------------------------------
def write_backup_status(tmp_path, **status):
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")
    control.set_files(env_file=env)
    folder = tmp_path / "backups"
    folder.mkdir(exist_ok=True)
    (folder / "status.json").write_text(json.dumps(status), encoding="utf-8")


def test_backup_probe(settings, db, tmp_path):
    mon, sent, clock = make_monitor(settings, db, FakeReader(), threshold=1)
    assert mon.probe_backup() is None                       # no launcher
    good = {"at": T0.isoformat(), "ok": True, "last_success_at": T0.isoformat()}
    write_backup_status(tmp_path, **good)
    assert mon.probe_backup() is True
    clock.now = T0 + timedelta(hours=monitor.BACKUP_OVERDUE_HOURS + 1)
    assert mon.probe_backup() is False                      # overdue
    assert mon.tick() == ["health_backup_down"]
    assert "پشتیبان" in sent[-1]
    write_backup_status(tmp_path, at=clock.now.isoformat(), ok=True,
                        last_success_at=clock.now.isoformat())
    assert mon.tick() == ["health_backup_up"]
    write_backup_status(tmp_path, at=clock.now.isoformat(), ok=False,
                        last_success_at=clock.now.isoformat())
    assert mon.probe_backup() is False                      # last run failed


def test_status_has_backup_without_secrets(client, tmp_path):
    owner = owner_token(client)
    assert client.get("/admin/server/status", headers=bearer(owner)).json()["backup"] is None
    write_backup_status(tmp_path, at=T0.isoformat(), ok=False, error="off-server copy failed",
                        file="ShopServer_x.zip", size=10, verify={"ok": True},
                        offsite={"configured": True, "ok": False, "error": "OSError: denied",
                                 "file": None}, last_success_at=None)
    backup = client.get("/admin/server/status", headers=bearer(owner)).json()["backup"]
    assert backup["ok"] is False and backup["verified"] is True
    assert backup["offsite_error"] == "OSError: denied"
    assert "passphrase" not in json.dumps(backup).lower()


def test_backup_settings_are_not_remotely_editable():
    for key in ("BACKUP_PASSPHRASE", "BACKUP_COPY_DIR", "BACKUP_ENABLED"):
        assert key not in control.EDITABLE


# ---- SQL login / config hygiene ---------------------------------------------------
@pytest.mark.parametrize("user", ["sa", "SA", " Sa "])
def test_sa_is_refused(user):
    s = Settings(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                 accounting_trusted=False, accounting_username=user, accounting_password="x")
    with pytest.raises(ValueError, match="sa"):
        s.accounting_connection_string()


def test_least_privilege_login_is_accepted():
    s = Settings(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                 accounting_trusted=False, accounting_username="shopbot", accounting_password="x")
    assert "UID=shopbot" in s.accounting_connection_string()


def test_code_never_reads_options_ini():
    hits = [p.name for p in APP_DIR.rglob("*.py")
            if re.search(r"options\.ini", p.read_text(encoding="utf-8"), re.I)]
    assert hits == []


def test_grant_script_denies_secrets_and_verify_probes_them():
    sql = APP_DIR.parent / "sql"
    grant = (sql / "create_api_user.sql").read_text(encoding="utf-8")
    verify = (sql / "verify_permissions.sql").read_text(encoding="utf-8")
    for table in ("setting", "Telegram_Setting", "api_online_setting", "TabaghehBandi"):
        assert re.search(rf"DENY SELECT[^\n]*ON dbo\.{table} TO shopbot", grant), table
        assert f"'dbo.{table}', 'OBJECT', 'SELECT'" in verify, table
    for table in ("KalaOrder", "KalaOrderDetail"):
        assert f"DENY UPDATE, DELETE ON dbo.{table} TO shopbot" in grant
    assert "GRANT SELECT ON dbo.KOL (" in grant
    assert "IS_SRVROLEMEMBER('sysadmin'" in verify
