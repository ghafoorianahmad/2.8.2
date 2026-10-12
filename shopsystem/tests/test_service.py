"""Phase 4: Windows service commands, supervisor, crash alerts, health check.

Nothing here touches the real service control manager, firewall or ACLs:
every system command goes through a recording fake runner.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path

import pytest

import launcher
import winservice


class FakeRunner:
    """Records commands; answers ``sc query`` from a mutable state."""

    def __init__(self, *, state: str | None = None, task: bool = False, fail: str = ""):
        self.state = state          # None = service not installed
        self.task = task
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, command):
        command = list(command)
        self.calls.append(command)
        out, code = "", 0
        if command[:2] == ["sc.exe", "query"]:
            if self.state is None:
                return subprocess.CompletedProcess(command, 1060, "", "does not exist")
            number = {v: k for k, v in winservice.STATES.items()}[self.state]
            out = f"SERVICE_NAME: ShopServer\n        STATE              : {number}  {self.state.upper()}\n"
        elif command[:2] == ["sc.exe", "create"]:
            self.state = "stopped"
        elif command[:2] == ["sc.exe", "stop"]:
            self.state = "stopped"
        elif command[:2] == ["sc.exe", "start"]:
            self.state = "running"
        elif command[:2] == ["sc.exe", "delete"]:
            self.state = None
        elif command[:2] == ["schtasks", "/Query"]:
            code = 0 if self.task else 1
        if self.fail and self.fail in " ".join(command):
            code = 5
            out = "Access is denied."
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def data_dir(tmp_path):
    folder = tmp_path / "ShopServer"
    folder.mkdir()
    (folder / ".env").write_text("API_PORT=8443\n", encoding="utf-8")
    (folder / "tls").mkdir()
    (folder / "tls" / "server.key").write_text("k", encoding="utf-8")
    return folder


# ---- winservice -------------------------------------------------------------------
def test_bin_path_quotes_spaces(tmp_path):
    cmd = winservice.service_command([r"C:\Program Files\ShopServer\ShopSystem\ShopSystem.exe"],
                                     Path(r"C:\ProgramData\ShopServer"))
    assert cmd.startswith('"C:\\Program Files\\ShopServer\\ShopSystem\\ShopSystem.exe" --winservice')
    assert cmd.endswith(r"--data-dir C:\ProgramData\ShopServer")


def test_install_creates_virtual_account_service(data_dir):
    run = FakeRunner()
    result = winservice.install(["ShopSystem.exe"], data_dir, run=run)
    create = next(c for c in run.calls if c[:2] == ["sc.exe", "create"])
    assert create[create.index("obj=") + 1] == r"NT SERVICE\ShopServer"
    assert create[create.index("start=") + 1] == "auto"
    assert "password=" not in create
    assert ["sc.exe", "failureflag", "ShopServer", "1"] in run.calls
    assert ["sc.exe", "sidtype", "ShopServer", "unrestricted"] in run.calls
    failure = next(c for c in run.calls if c[:2] == ["sc.exe", "failure"])
    assert "restart/10000" in failure[-1]
    grants = [c for c in run.calls if c[0] == "icacls"]
    assert grants[0] == ["icacls", str(data_dir), "/grant", r"NT SERVICE\ShopServer:(OI)(CI)M", "/C", "/Q"]
    granted = {c[1] for c in grants}
    assert str(data_dir / ".env") in granted and str(data_dir / "tls" / "server.key") in granted
    assert all("/inheritance:r" not in c and "/grant:r" not in c for c in grants)
    assert result == {"ok": True, "service": "ShopServer", "account": r"NT SERVICE\ShopServer",
                      "updated": False, "legacy_task_removed": False}


def test_reinstall_updates_and_removes_old_task(data_dir):
    run = FakeRunner(state="running", task=True)
    result = winservice.install(["ShopSystem.exe"], data_dir, run=run)
    assert ["sc.exe", "stop", "ShopServer"] in run.calls
    assert any(c[:2] == ["sc.exe", "config"] for c in run.calls)
    assert not any(c[:2] == ["sc.exe", "create"] for c in run.calls)
    assert ["schtasks", "/Delete", "/TN", "ShopServer", "/F"] in run.calls
    assert result["updated"] and result["legacy_task_removed"]


def test_install_grants_shoptg_env_and_session(data_dir, tmp_path):
    tg_dir = tmp_path / "shoptg"
    tg_dir.mkdir()
    (tg_dir / ".env").write_text("TG_API_ID=1\n", encoding="utf-8")
    tg_data = data_dir / "shoptg"
    tg_data.mkdir()
    (tg_data / "tg_session.dpapi").write_bytes(b"x")
    run = FakeRunner()
    winservice.install(["x.exe"], data_dir, shoptg_dir=tg_dir, shoptg_data=tg_data, run=run)
    grants = {c[1]: c[3] for c in run.calls if c[0] == "icacls"}
    assert grants[str(tg_dir / ".env")] == r"NT SERVICE\ShopServer:R"
    assert grants[str(tg_data)] == r"NT SERVICE\ShopServer:(OI)(CI)M"
    assert grants[str(tg_data / "tg_session.dpapi")] == r"NT SERVICE\ShopServer:M"


def test_install_failure_raises(data_dir):
    with pytest.raises(winservice.ServiceError):
        winservice.install(["x.exe"], data_dir, run=FakeRunner(fail="create"))


def test_state_start_stop_uninstall(data_dir):
    run = FakeRunner()
    assert winservice.state(run) is None
    winservice.install(["x.exe"], data_dir, run=run)
    assert winservice.state(run) == "stopped"
    winservice.start(run)
    assert winservice.state(run) == "running"
    winservice.stop(run, sleep=lambda _s: None)
    assert winservice.state(run) == "stopped"
    winservice.start(run)
    assert winservice.uninstall(data_dir, run=run) == {"ok": True, "removed": True}
    assert winservice.state(run) is None
    remove = [c for c in run.calls if "/remove:g" in c]
    assert remove and remove[0][1] == str(data_dir)
    assert winservice.uninstall(data_dir, run=run) == {"ok": True, "removed": False}


def test_stop_times_out():
    class Stuck(FakeRunner):
        def __call__(self, command):
            result = super().__call__(command)
            self.state = "stop_pending"
            return result

    with pytest.raises(winservice.ServiceError):
        winservice.stop(Stuck(state="running"), timeout=3, sleep=lambda _s: None)


# ---- supervisor ------------------------------------------------------------------------
class FakeProcess:
    def __init__(self, code):
        self.code = code
        self.pid = 1234
        self.returncode = None
        self.terminated = False

    def poll(self):
        if self.code is None and not self.terminated:
            return None
        self.returncode = self.code if not self.terminated else 1
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.poll()

    def kill(self):
        self.terminated = True


def test_child_restarts_and_crash_loop_alerts(monkeypatch):
    monkeypatch.setattr(launcher, "_assign_to_job", lambda job, p: None)
    stop = threading.Event()
    started = []
    alerts = []
    codes = iter([1, 1, 1, launcher.EXIT_RESTART])

    def popen(command, **kwargs):
        started.append(kwargs["env"])
        try:
            return FakeProcess(next(codes))
        except StopIteration:
            stop.set()
            return FakeProcess(None)

    real_wait = stop.wait
    monkeypatch.setattr(stop, "wait", lambda t=None: real_wait(0) if t and t > 1 else real_wait(0))
    spec = launcher.ChildSpec("server", "سرور", ["x.exe", "--worker"], env={"A": "1"})
    launcher.supervise_child(spec, stop, tracker=launcher.CrashTracker(),
                             on_crash_loop=lambda s: alerts.append(s.name), popen=popen)
    assert len(started) == 5
    assert alerts == ["server"]            # 3 failures -> one alert


def test_supervisor_stops_child_on_stop_event(monkeypatch):
    monkeypatch.setattr(launcher, "_assign_to_job", lambda job, p: None)
    stop = threading.Event()
    process = FakeProcess(None)
    stop.set()
    spec = launcher.ChildSpec("server", "x", ["x"], env={})
    # stop already set: never started
    launcher.supervise_child(spec, stop, popen=lambda *a, **k: process)
    assert process.terminated is False

    stop2 = threading.Event()
    threading.Timer(0.2, stop2.set).start()
    launcher.supervise_child(spec, stop2, popen=lambda *a, **k: process)
    assert process.terminated is True


def test_crash_tracker_window_and_throttle():
    now = [0.0]
    tracker = launcher.CrashTracker(clock=lambda: now[0])
    assert [tracker.failed("a") for _ in range(3)] == [False, False, True]
    assert tracker.failed("a") is False            # within the hour
    now[0] = 4000
    assert tracker.failed("a") is False            # old failures expired
    assert tracker.failed("a") is False
    assert tracker.failed("a") is True


def test_crash_alert_text_has_no_secrets():
    text = launcher.crash_alert_text("کارگر تلگرام")
    assert "کارگر تلگرام" in text and "supervisor.log" in text


def test_shoptg_spec_passes_only_what_it_needs(tmp_path, monkeypatch, data_dir):
    launcher.configure_paths(data_dir)
    tg = tmp_path / "shoptg"
    (tg / ".venv" / "Scripts").mkdir(parents=True)
    (tg / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    monkeypatch.setenv("SHOPSERVER_SUPERVISED", "1")
    values = {"SHOPTG_DIR": str(tg), "API_TLS": "true", "API_PORT": "8443",
              "WORKER_API_KEY": "wk", "BALE_TOKEN": "secret", "DB_PASSWORD": "pw"}
    spec = launcher.shoptg_spec(values, run_mode="service")
    assert spec.command[-2:] == ["-m", "app.main"] and spec.cwd == str(tg)
    assert spec.env["SHOPAPI_BASE_URL"] == "https://127.0.0.1:8443"
    assert spec.env["WORKER_API_KEY"] == "wk"
    assert spec.env["SHOPAPI_CA_FILE"].endswith("server.crt")
    assert spec.env["TG_SERVICE_ACCOUNT"] == r"NT SERVICE\ShopServer"
    assert "BALE_TOKEN" not in spec.env and "DB_PASSWORD" not in spec.env
    assert "SHOPSERVER_SUPERVISED" not in spec.env

    assert launcher.shoptg_spec({}, run_mode="service") is None
    assert launcher.shoptg_spec({"SHOPTG_DIR": str(tmp_path / "nope")}, run_mode="task") is None
    names = [s.name for s in launcher.child_specs(values, run_mode="task")]
    assert names == ["server", "shoptg"]
    assert "TG_SERVICE_ACCOUNT" not in launcher.shoptg_spec(values, run_mode="task").env


# ---- health check --------------------------------------------------------------------------
class _Health(http.server.BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):  # noqa: N802
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def test_health_check_ok_and_failure(data_dir, capsys):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        (data_dir / ".env").write_text(f"API_PORT={port}\nAPI_TLS=false\n", encoding="utf-8")
        launcher.configure_paths(data_dir)
        assert launcher.health_check(5) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True
        _Health.status = 500
        assert launcher.health_check(0) == 1
        assert json.loads(capsys.readouterr().out)["error"] == "HTTP 500"
    finally:
        _Health.status = 200
        server.shutdown()


def test_health_check_tls_without_certificate(data_dir, capsys):
    (data_dir / ".env").write_text("API_PORT=1\nAPI_TLS=true\n", encoding="utf-8")
    launcher.configure_paths(data_dir)
    assert launcher.health_check(0) == 1
    assert "certificate" in json.loads(capsys.readouterr().out)["error"]


def test_service_tool_reports_json(data_dir, monkeypatch, capsys):
    launcher.configure_paths(data_dir)
    run = FakeRunner()
    monkeypatch.setattr(winservice, "_default_runner", run)
    assert launcher.main(["--install-service", "--data-dir", str(data_dir)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["state"] == "stopped"
    assert launcher.main(["--service-status", "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "stopped"
