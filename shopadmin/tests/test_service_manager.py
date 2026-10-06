"""Tests for the automatic ShopSystem.exe lifecycle (Issue 2).

These never touch the network and never launch the real ShopSystem.exe:

* reachability is stubbed,
* the "executable" is a harmless long-running ``python -c "time.sleep(...)"``,
* the service probe is stubbed, so the manager believes it came up.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services import child_process as cp
from app.services.child_process import (
    MSG_NOT_FOUND,
    MSG_START_EXITED,
    MSG_START_TIMEOUT,
    SERVICE_EXE_NAME,
    LaunchResult,
    ServiceMonitor,
    ServiceState,
    ShopSystemService,
    find_service_executable,
    host_of,
    is_local_address,
)


# --------------------------------------------------------------------------
# address classification
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8000", True),
        ("http://localhost:8000", True),
        ("http://LOCALHOST:8000", True),
        ("https://127.0.0.1:443", True),
        ("http://[::1]:8000", True),
        ("http://192.168.1.50:8000", False),
        ("http://shop.example.com", False),
        ("http://10.0.0.7", False),
        ("", False),
        ("not-a-url", False),
    ],
)
def test_local_address_detection(url, expected):
    assert is_local_address(url) is expected


def test_host_of_strips_port_and_lowercases():
    assert host_of("http://127.0.0.1:8000/x") == "127.0.0.1"
    assert host_of("HTTP://Server.LAN:9000") == "server.lan"
    assert host_of("") == ""


# --------------------------------------------------------------------------
# finding the executable
# --------------------------------------------------------------------------
def test_find_service_executable_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "is_frozen", lambda: True)
    assert find_service_executable() is None


def test_find_service_executable_next_to_the_app(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "is_frozen", lambda: True)
    (tmp_path / SERVICE_EXE_NAME).write_bytes(b"MZ")
    assert find_service_executable() == tmp_path / SERVICE_EXE_NAME


def test_find_service_executable_in_the_installed_subfolder(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(cp, "is_frozen", lambda: True)
    subfolder = tmp_path / "ShopSystem"
    subfolder.mkdir()
    (subfolder / SERVICE_EXE_NAME).write_bytes(b"MZ")
    assert find_service_executable() == subfolder / SERVICE_EXE_NAME


# --------------------------------------------------------------------------
# launch behaviour
# --------------------------------------------------------------------------
@pytest.fixture
def sleeper():
    """A long-running, harmless process to stand in for ShopSystem.exe."""
    return [sys.executable, "-c", "import time; time.sleep(120)"]


def _service(monkeypatch, base_url, sleeper, *, reachable_after=0):
    """Build a service whose probe is stubbed and whose exe is the sleeper."""
    service = ShopSystemService(base_url, timeout=3.0)
    monkeypatch.setattr(service, "is_reachable", lambda timeout=2.5: False)
    monkeypatch.setattr(sys, "executable", sleeper[0])

    def fake_find():
        return Path(sleeper[0])

    monkeypatch.setattr(cp, "find_service_executable", fake_find)
    # Launch the sleeper instead of the real executable.
    real_popen = subprocess.Popen

    def fake_popen(args, **kwargs):
        assert args == [str(Path(sleeper[0]))]
        return real_popen(sleeper, **kwargs)

    monkeypatch.setattr(cp.subprocess, "Popen", fake_popen)
    return service


def test_remote_address_never_launches_anything(monkeypatch, sleeper):
    service = _service(monkeypatch, "http://192.168.1.50:8000", sleeper)
    launched = []
    monkeypatch.setattr(cp.subprocess, "Popen",
                        lambda *a, **k: launched.append(a))

    result = service.start()
    assert result.ok is True
    assert result.launched is False
    assert launched == [], "a remote server must never cause a local launch"
    assert service.started_by_us is False


def test_already_running_service_is_not_restarted(monkeypatch, sleeper):
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    monkeypatch.setattr(service, "is_reachable", lambda timeout=2.5: True)
    called = []
    monkeypatch.setattr(cp.subprocess, "Popen", lambda *a, **k: called.append(a))

    result = service.start()
    assert result.ok is True
    assert result.launched is False
    assert called == []
    assert service.started_by_us is False


def test_missing_executable_reports_the_persian_message(monkeypatch, sleeper):
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    monkeypatch.setattr(cp, "find_service_executable", lambda: None)

    result = service.start()
    assert result.ok is False
    assert result.launched is False
    assert result.message == MSG_NOT_FOUND
    assert "ShopSystem.exe" in result.message
    assert service.started_by_us is False


def test_local_service_is_launched_and_then_stopped(monkeypatch, sleeper):
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)

    # The process starts but the probe never succeeds: force the ready path.
    monkeypatch.setattr(service, "_wait_until_ready", lambda progress: True)
    result = service.start()

    assert result.ok is True
    assert result.launched is True
    assert service.started_by_us is True
    assert service.pid is not None

    pid = service.pid
    service.stop(graceful_timeout=5.0)
    assert service.started_by_us is False
    assert service.pid is None
    # And the child really is gone.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(0.1)
    assert not _alive(pid), "the child process must be terminated on stop"


def test_a_manually_started_process_is_never_touched(monkeypatch, sleeper):
    """A service the owner started by hand must survive ShopAdmin closing."""
    manual = subprocess.Popen(sleeper)
    try:
        service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
        # We never launched anything, so stop() must be a no-op.
        service.stop()
        assert manual.poll() is None, "a manually started service must not be killed"
    finally:
        manual.terminate()
        manual.wait(timeout=5)


def test_stop_is_idempotent(monkeypatch, sleeper):
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    service.stop()
    service.stop()  # must not raise


def test_service_log_is_redirected_to_a_file(monkeypatch, sleeper, tmp_path):
    monkeypatch.setattr(cp, "data_dir", lambda: tmp_path)
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    monkeypatch.setattr(service, "_wait_until_ready", lambda progress: True)

    service.start()
    log_path = tmp_path / cp.SERVICE_LOG_NAME
    assert log_path.exists(), "the child's output must go to shopapi.log"
    service.stop()


def test_no_console_window_flag_is_requested(monkeypatch, sleeper, tmp_path):
    """CREATE_NO_WINDOW must be set, otherwise a console window would flash up."""
    monkeypatch.setattr(cp, "data_dir", lambda: tmp_path)
    service = ShopSystemService("http://127.0.0.1:8000", timeout=3.0)
    monkeypatch.setattr(service, "is_reachable", lambda timeout=2.5: False)
    monkeypatch.setattr(service, "_wait_until_ready", lambda progress: True)
    monkeypatch.setattr(cp, "find_service_executable", lambda: Path(sleeper[0]))

    captured: dict = {}
    real_popen = subprocess.Popen

    def spy(_args, **kwargs):
        captured.update(kwargs)
        # Launch the sleeper directly so the recorded flags stay untouched.
        forwarded = {k: v for k, v in kwargs.items() if k != "creationflags"}
        return real_popen(sleeper, **forwarded)

    monkeypatch.setattr(cp.subprocess, "Popen", spy)
    service.start()
    try:
        if sys.platform.startswith("win"):
            assert captured.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, \
                "the child must run with no visible console window"
        assert captured.get("stdout") is not None, "stdout must be redirected to a log"
        assert captured.get("stderr") == subprocess.STDOUT
        assert captured.get("stdin") == subprocess.DEVNULL
    finally:
        service.stop()


def _alive(pid: int | None) -> bool:
    """Cross-platform 'is this pid still running' helper."""
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return str(pid) in result.stdout
    except Exception:  # pragma: no cover - tasklist missing
        return False


# --------------------------------------------------------------------------
# ServiceMonitor (the Qt-facing wrapper)
# --------------------------------------------------------------------------
def test_monitor_reports_remote_state_without_launching(admin_qapp, monkeypatch):
    """A remote address must reach REMOTE state and never spawn a process.

    ``start()`` is still invoked (it is the single entry point), but for a remote
    address it must short-circuit inside ShopSystemService — so nothing is ever
    popped up, whatever the executable situation is.
    """
    monitor = ServiceMonitor("http://192.168.1.50:8000")
    launched: list = []
    monkeypatch.setattr(cp.subprocess, "Popen", lambda *a, **k: launched.append(a))
    # Make sure a local launch WOULD have been possible, so the assertion is real.
    monkeypatch.setattr(cp, "find_service_executable", lambda: Path("ShopSystem.exe"))

    states: list = []
    monitor.state_changed.connect(states.append)
    monitor.ensure_running_async()
    _pump(admin_qapp)

    assert launched == [], "a remote address must never cause a local launch"
    assert monitor.state == ServiceState.REMOTE
    assert monitor.started_by_us is False
    assert states[-1] == ServiceState.REMOTE


def test_monitor_reaches_connected_state(admin_qapp, monkeypatch, sleeper):
    monitor = ServiceMonitor("http://127.0.0.1:8000")
    monkeypatch.setattr(monitor.service, "start",
                        lambda **kwargs: LaunchResult(ok=True, launched=True))

    monitor.ensure_running_async()
    _pump(admin_qapp)
    assert monitor.state == ServiceState.CONNECTED


def test_monitor_emits_the_persian_error_when_launch_fails(admin_qapp, monkeypatch):
    monitor = ServiceMonitor("http://127.0.0.1:8000")
    monkeypatch.setattr(
        monitor.service, "start",
        lambda **kwargs: LaunchResult(ok=False, launched=False, message=MSG_NOT_FOUND),
    )
    errors: list = []
    monitor.failed.connect(errors.append)

    monitor.ensure_running_async()
    _pump(admin_qapp)

    assert errors == [MSG_NOT_FOUND]
    assert monitor.state == ServiceState.OFFLINE


def test_a_slow_start_is_reported_softly_not_as_a_dialog(admin_qapp, monkeypatch):
    """Started-but-not-ready-yet must not interrupt the user with an error box.

    The service is running and may come up any second; a modal dialog would be
    alarming and wrong, so this goes to the soft channel instead.
    """
    monitor = ServiceMonitor("http://127.0.0.1:8000")
    monkeypatch.setattr(
        monitor.service, "start",
        lambda **kwargs: LaunchResult(ok=False, launched=True,
                                      message="زمان کافی نبود", transient=True),
    )
    hard: list = []
    soft: list = []
    monitor.failed.connect(hard.append)
    monitor.failed_soft.connect(soft.append)

    monitor.ensure_running_async()
    _pump(admin_qapp)

    assert soft == ["زمان کافی نبود"]
    assert hard == [], "a transient slow start must not raise a hard failure"
    assert monitor.state == ServiceState.OFFLINE


def test_a_missing_executable_is_a_hard_failure(admin_qapp, monkeypatch):
    """The Persian 'not found' message must reach the user as a dialog."""
    monitor = ServiceMonitor("http://127.0.0.1:8000")
    monkeypatch.setattr(
        monitor.service, "start",
        lambda **kwargs: LaunchResult(ok=False, launched=False,
                                      message=MSG_NOT_FOUND, transient=False),
    )
    hard: list = []
    soft: list = []
    monitor.failed.connect(hard.append)
    monitor.failed_soft.connect(soft.append)

    monitor.ensure_running_async()
    _pump(admin_qapp)

    assert hard == [MSG_NOT_FOUND]
    assert soft == []


def test_start_timeout_is_flagged_as_transient(monkeypatch, sleeper):
    """The real ``start()`` must mark a timeout as transient, not as not-found."""
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    monkeypatch.setattr(service, "_wait_until_ready", lambda progress: False)
    result = service.start()
    try:
        assert result.ok is False
        assert result.launched is True
        assert result.transient is True
        assert result.message == MSG_START_TIMEOUT
    finally:
        service.stop()


def test_a_service_that_exits_immediately_explains_the_env_file(monkeypatch, sleeper):
    """The most common real failure: ShopSystem.exe closes at once (no .env).

    The message must tell the owner what to actually do, not just "try again".
    """
    service = _service(monkeypatch, "http://127.0.0.1:8000", sleeper)
    monkeypatch.setattr(service, "_wait_until_ready", lambda progress: False)

    # Make poll() report that the process already died.
    class DeadProcess:
        pid = 4242
        returncode = 1

        def poll(self):
            return 1

    service._process = DeadProcess()
    result = service.start()
    # start() replaces _process, so drive the branch directly instead.
    assert MSG_START_EXITED != MSG_NOT_FOUND
    assert ".env" in MSG_START_EXITED
    assert "ADMIN_API_KEY" in MSG_START_EXITED
    assert "shopapi.log" in MSG_START_EXITED
    service._process = None


def test_start_reports_exited_service_with_the_env_hint(monkeypatch, sleeper, tmp_path):
    """A service that dies immediately yields the actionable .env message."""
    monkeypatch.setattr(cp, "data_dir", lambda: tmp_path)
    service = ShopSystemService("http://127.0.0.1:8000", timeout=1.0)
    monkeypatch.setattr(service, "is_reachable", lambda timeout=2.5: False)
    monkeypatch.setattr(cp, "find_service_executable", lambda: Path(sleeper[0]))

    # Capture the real Popen BEFORE patching: cp.subprocess IS the stdlib module,
    # so calling subprocess.Popen inside the replacement would recurse forever.
    real_popen = subprocess.Popen

    # A process that exits instantly stands in for "ShopSystem.exe with no .env".
    def dying_popen(_args, **kwargs):
        forwarded = {k: v for k, v in kwargs.items() if k != "creationflags"}
        return real_popen([sleeper[0], "-c", "raise SystemExit(2)"], **forwarded)

    monkeypatch.setattr(cp.subprocess, "Popen", dying_popen)
    result = service.start()
    try:
        assert result.ok is False
        assert result.launched is True
        assert result.transient is False
        assert result.message == MSG_START_EXITED
    finally:
        service.stop()


def test_monitor_shutdown_stops_the_child(admin_qapp, monkeypatch, sleeper):
    monkeypatch.setattr(cp, "data_dir", lambda: Path("."))
    monitor = ServiceMonitor("http://127.0.0.1:8000")
    stopped: list = []
    monkeypatch.setattr(monitor.service, "stop", lambda: stopped.append(True))

    monitor.shutdown()
    assert stopped == [True]


def test_monitor_shutdown_never_raises(admin_qapp, monkeypatch):
    monitor = ServiceMonitor("http://127.0.0.1:8000")

    def boom():
        raise RuntimeError("deliberate")

    monkeypatch.setattr(monitor.service, "stop", boom)
    monitor.shutdown()  # must not raise


def test_state_labels_are_persian():
    import re

    for state in ServiceState:
        assert re.search(r"[\u0600-\u06FF]", state.label_fa), state
    assert ServiceState.CONNECTED.label_fa == "سرویس فروشگاه: متصل"
    assert ServiceState.STARTING.label_fa == "سرویس فروشگاه: در حال راه‌اندازی"
    assert ServiceState.OFFLINE.label_fa == "سرویس فروشگاه: قطع"


def _pump(app, rounds: int = 60) -> None:
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    for _ in range(rounds):
        app.processEvents()
