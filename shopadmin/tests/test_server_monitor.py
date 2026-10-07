"""The console is a pure client: it probes the server and never launches one.

Regression for the Windows Sandbox report: the installed client showed
"ShopSystem.exe not found next to this program" because the old service
manager tried to start the server whenever the address was local.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from app.services import connection
from app.services.connection import (
    MSG_SERVER_UNREACHABLE,
    ConnectionState,
    ServerMonitor,
    unreachable_message,
)
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture

APP_DIR = Path(__file__).resolve().parent.parent / "app"
#: Only the server setup (run by ShopServerSetup, left out of the client
#: build) may know about the server program.
SERVER_ONLY = {APP_DIR / "server_setup.py", APP_DIR / "ui" / "server_setup_wizard.py"}


def _pump(app, rounds: int = 60) -> None:
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    for _ in range(rounds):
        app.processEvents()


@pytest.fixture
def no_process_spawning(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("the management console must never start a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def test_client_code_never_mentions_the_server_program():
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path not in SERVER_ONLY and re.search(r"ShopSystem", path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"client modules reference ShopSystem: {offenders}"


def test_old_service_manager_is_gone():
    assert not (APP_DIR / "services" / "child_process.py").exists()
    assert not (APP_DIR / "services" / "jobobject.py").exists()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "https://localhost:8443",
                                 "https://192.168.1.10:8443"])
def test_unreachable_server_is_reported_not_launched(admin_qapp, monkeypatch,
                                                     no_process_spawning, url):
    monkeypatch.setattr(connection, "probe", lambda *a, **k: False)
    monitor = ServerMonitor(url)
    messages: list = []
    monitor.unreachable.connect(messages.append)

    monitor.check_async()
    _pump(admin_qapp)

    assert monitor.state == ConnectionState.OFFLINE
    assert len(messages) == 1
    assert MSG_SERVER_UNREACHABLE in messages[0]
    assert url in messages[0], "the message must show the configured address"
    assert "ShopSystem" not in messages[0]


def test_reachable_server_is_connected(admin_qapp, monkeypatch, no_process_spawning):
    monkeypatch.setattr(connection, "probe", lambda *a, **k: True)
    monitor = ServerMonitor("https://192.168.1.10:8443")
    messages: list = []
    monitor.unreachable.connect(messages.append)

    monitor.check_async()
    _pump(admin_qapp)

    assert monitor.state == ConnectionState.CONNECTED
    assert messages == []


def test_quiet_check_updates_state_without_a_message(admin_qapp, monkeypatch):
    monkeypatch.setattr(connection, "probe", lambda *a, **k: False)
    monitor = ServerMonitor("https://192.168.1.10:8443")
    messages: list = []
    monitor.unreachable.connect(messages.append)

    monitor.check_async(report=False)
    _pump(admin_qapp)

    assert monitor.state == ConnectionState.OFFLINE
    assert messages == []


def test_a_crashing_probe_counts_as_unreachable(admin_qapp, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("deliberate")

    monkeypatch.setattr(connection, "probe", boom)
    monitor = ServerMonitor("https://192.168.1.10:8443")
    monitor.check_async(report=False)
    _pump(admin_qapp)
    assert monitor.state == ConnectionState.OFFLINE


def test_probe_never_raises_for_a_dead_address():
    assert connection.probe("http://127.0.0.1:9", timeout=0.5) is False
    assert connection.probe("") is False


def test_unreachable_message_is_persian_with_address_and_retry():
    message = unreachable_message("https://10.0.0.5:8443")
    assert message.startswith(MSG_SERVER_UNREACHABLE)
    assert "https://10.0.0.5:8443" in message
    assert "تلاش دوباره" in message
    for state in ConnectionState:
        assert re.search(r"[؀-ۿ]", state.label_fa)


def test_main_window_retry_button_and_dialog(ui_context, admin_qapp, monkeypatch,
                                            top_level_windows, no_process_spawning):
    """Offline: the top bar offers «تلاش دوباره» and a dialog with the address."""
    from app.permissions import ROLE_SUPER_ADMIN
    from app.ui import widgets
    from app.ui.main_window import MainWindow

    monkeypatch.setattr(connection, "probe", lambda *a, **k: False)
    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    asked: list = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: asked.append(k) or False)
    window.show()
    window.check_server()
    _pump(admin_qapp)

    assert window.server_label.text() == MSG_SERVER_UNREACHABLE
    assert window.server_retry_button.isVisibleTo(window)
    assert window.server_retry_button.text() == "تلاش دوباره"
    assert asked and asked[0]["confirm_text"] == "تلاش دوباره"
    window.allow_close = True
    window.close()


def test_rendered_buttons_meet_aa_in_wizards_and_dialogs(admin_qapp):
    """What Qt really paints: wizard «ادامه», login, MessageDialog, QMessageBox.

    The Sandbox report (white text on a light button) came from a window
    stylesheet cascading into its buttons and child dialogs; only a rendered
    check sees that.
    """
    from scripts.contrast_audit import contrast_ratio, rendered_pairs

    pairs = rendered_pairs()
    assert len(pairs) >= 15
    failing = [(label, fg, bg) for label, fg, bg, minimum in pairs
               if contrast_ratio(fg, bg) < minimum]
    assert failing == []
