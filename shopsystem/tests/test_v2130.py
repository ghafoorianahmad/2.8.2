"""v2.13.0: watchdog + one owner alert per incident, a server whose bots/API gave
up exits for a restart, the off-server copy signs in to another computer's
share, and setup answers survive any console code page."""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backup
import launcher
import netshare
import winservice

from test_backup import PASS, data  # noqa: F401 - fixture
from test_service import FakeProcess, data_dir  # noqa: F401 - fixture

T0 = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)


# ---- watchdog / incidents -------------------------------------------------------
class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _fast_stop(monkeypatch, stop):
    real_wait = stop.wait
    monkeypatch.setattr(stop, "wait", lambda t=None: real_wait(0))


def test_one_alert_per_incident(monkeypatch):
    monkeypatch.setattr(launcher, "_assign_to_job", lambda job, p: None)
    stop = threading.Event()
    _fast_stop(monkeypatch, stop)
    clock = Clock()
    incidents = []
    # three quick failures (one incident), a long healthy run that then fails
    # (a new incident), a restart request (no alert), then stop
    plan = iter([(1, 5), (1, 5), (1, 5), (1, launcher.INCIDENT_RESET_SEC + 10),
                 (launcher.EXIT_RESTART, 5)])

    def popen(command, **kwargs):
        try:
            code, ran = next(plan)
        except StopIteration:
            stop.set()
            return FakeProcess(None)
        clock.t += ran
        return FakeProcess(code)

    spec = launcher.ChildSpec("shoptg", "کارگر تلگرام", ["x.exe"], env={})
    launcher.supervise_child(spec, stop, popen=popen, clock=clock,
                             on_incident=lambda s, code: incidents.append((s.name, code)))
    assert incidents == [("shoptg", 1), ("shoptg", 1)]


def test_watchdog_kills_a_child_without_heartbeat(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "_assign_to_job", lambda job, p: None)
    monkeypatch.setattr(launcher, "HEARTBEAT_CHECK_SEC", 0)
    stop = threading.Event()
    wall = [time.time()]
    beat = tmp_path / "shoptg.heartbeat"
    beat.write_text("1")
    os.utime(beat, (wall[0] - 3600, wall[0] - 3600))      # an hour old
    process = FakeProcess(None)
    spec = launcher.ChildSpec("shoptg", "کارگر تلگرام", ["x.exe"], env={}, heartbeat=beat)
    times = iter([wall[0]] + [wall[0] + 700] * 10)       # started, then 700 s later
    code = launcher._run_once(spec, stop, job=None, popen=lambda *a, **k: process,
                              stale_after=600, wall=lambda: next(times))
    assert code == "hung" and process.terminated


def test_fresh_heartbeat_keeps_the_child(tmp_path):
    beat = tmp_path / "hb"
    beat.write_text("1")
    spec = launcher.ChildSpec("shoptg", "x", ["x"], env={}, heartbeat=beat)
    now = time.time()
    assert not launcher._heartbeat_stale(spec, now - 5000, now, 600)
    assert launcher._heartbeat_stale(spec, now - 5000, now + 601, 600)
    # no file yet: counted from the start
    spec.heartbeat = tmp_path / "missing"
    assert not launcher._heartbeat_stale(spec, now, now + 300, 600)
    assert launcher._heartbeat_stale(spec, now, now + 601, 600)
    spec.heartbeat = None
    assert not launcher._heartbeat_stale(spec, 0, now, 600)


def test_supervision_survives_its_own_errors(monkeypatch):
    monkeypatch.setattr(launcher, "_assign_to_job", lambda job, p: None)
    stop = threading.Event()
    _fast_stop(monkeypatch, stop)
    calls = []

    def popen(command, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("unexpected")
        stop.set()
        return FakeProcess(None)

    spec = launcher.ChildSpec("server", "سرور", ["x.exe"], env={})
    launcher.supervise_child(spec, stop, popen=popen)
    assert len(calls) == 2


def test_restart_alert_goes_through_the_api_else_bale(monkeypatch):
    sent = []
    monkeypatch.setattr(launcher, "send_crash_alert", lambda label, values: sent.append(label))
    values = {"WORKER_API_KEY": "k", "API_PORT": "8443"}
    monkeypatch.setattr(launcher, "post_restart_event", lambda label, values: True)
    launcher.alert_restart("کارگر تلگرام", values)
    assert sent == []
    monkeypatch.setattr(launcher, "post_restart_event", lambda label, values: False)
    launcher.alert_restart("کارگر تلگرام", values)
    assert sent == ["کارگر تلگرام"]


def test_post_restart_event_needs_the_worker_key():
    assert launcher.post_restart_event("x", {}) is False
    seen = []
    assert launcher.post_restart_event(
        "کارگر تلگرام", {"WORKER_API_KEY": "k", "API_PORT": "9000"},
        post=lambda url, label, key: seen.append((url, label, key)) or True)
    assert seen == [("http://127.0.0.1:9000/worker/alerts", "کارگر تلگرام", "k")]


def test_tg_reader_gets_a_heartbeat_file(data_dir):
    launcher.configure_paths(data_dir)
    env = launcher.shoptg_env({}, run_mode="task", bundled=True)
    assert env["TG_HEARTBEAT_FILE"] == str(data_dir / "shoptg.heartbeat")
    spec = launcher.shoptg_spec({"TG_READER_ENABLED": "true"}, run_mode="task")
    assert spec.heartbeat == data_dir / "shoptg.heartbeat"


# ---- setup answers on any code page ----------------------------------------------
def test_emit_is_ascii_and_console_is_utf8(monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    launcher.utf8_console()
    launcher._emit({"ok": False, "title_fa": "دسترسی نیست"})
    stream.flush()
    line = raw.getvalue().decode("ascii")
    assert json.loads(line)["title_fa"] == "دسترسی نیست"
    print("سلام")                                   # no UnicodeEncodeError any more
    stream.flush()


# ---- off-server copy to another computer ------------------------------------------
def test_share_root_and_session():
    assert netshare.share_root(r"\\192.168.20.150\E\ShopServerBackup") == r"\\192.168.20.150\E"
    assert netshare.share_root(r"E:\ShopServerBackup") is None
    calls = []
    with netshare.session(r"\\pc\e\x", "user", "pw",
                          connect=lambda r, u, p: calls.append(("on", r, u)),
                          disconnect=lambda r: calls.append(("off", r))) as signed:
        assert signed is True
    assert calls == [("on", r"\\pc\e", "user"), ("off", r"\\pc\e")]
    with netshare.session(r"\\pc\e\x", "", "pw", connect=lambda *a: calls.append("x")) as signed:
        assert signed is False                      # no user name: nothing to sign in
    with netshare.session(r"D:\b", "user", "pw", connect=lambda *a: calls.append("x")) as signed:
        assert signed is False
    assert "x" not in calls


def test_backup_signs_in_to_the_share(data, tmp_path, monkeypatch):  # noqa: F811
    target = tmp_path / "remote"
    used = []

    def fake_session(folder, user, password):
        import contextlib

        @contextlib.contextmanager
        def cm():
            used.append((folder, user, password))
            yield True
        return cm()

    monkeypatch.setattr(netshare, "session", fake_session)
    config = backup.BackupConfig.from_values({
        "BACKUP_COPY_DIR": str(target), "BACKUP_PASSPHRASE": PASS,
        "BACKUP_SHARE_USER": r"PC\shop", "BACKUP_SHARE_PASSWORD": "pw"})
    assert (config.share_user, config.share_password) == (r"PC\shop", "pw")
    status = backup.run_backup(data, config, now=T0)
    assert status["ok"] and status["local_ok"] and used == [(config.copy_dir, r"PC\shop", "pw")]


def test_network_share_without_user_name_is_explained(data, tmp_path, monkeypatch):  # noqa: F811
    def denied(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(backup, "copy_offsite", denied)
    config = backup.BackupConfig(copy_dir=r"\\192.168.20.150\E\ShopServerBackup", passphrase=PASS)
    status = backup.run_backup(data, config, now=T0)
    assert not status["ok"] and status["local_ok"]
    assert status["last_local_success_at"] == status["at"]
    assert "no user name" in status["offsite"]["error"]
    assert status["offsite"]["network"] is True


def test_share_login_error_is_reported_in_persian(data, monkeypatch):  # noqa: F811
    def refused(folder, user, password):
        raise netshare.ShareLoginError(1326, netshare.ERROR_FA[1326])

    monkeypatch.setattr(netshare, "session", refused)
    config = backup.BackupConfig(copy_dir=r"\\pc\e", passphrase=PASS, share_user="u")
    status = backup.run_backup(data, config, now=T0)
    assert status["offsite"]["error"].startswith("ShareLogin 1326")


def test_archive_folder_is_readable_for_users(tmp_path):
    (tmp_path / "pricelists").mkdir()
    commands = winservice.acl_commands(tmp_path)
    assert ["icacls", str(tmp_path / "pricelists"), "/grant", "*S-1-5-32-545:(OI)(CI)RX",
            "/C", "/Q"] in commands
