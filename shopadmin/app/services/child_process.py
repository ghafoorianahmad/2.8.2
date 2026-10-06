"""Start and stop the local shopapi service (``ShopSystem.exe``) automatically.

The shop owner should never have to double-click a console window and keep it
open. This manager:

1. probes the configured address;
2. if it is a LOCAL address and nothing answers, finds and starts
   ``ShopSystem.exe`` **with no visible console** (``CREATE_NO_WINDOW``), with
   stdout/stderr redirected to ``shopapi.log`` in the ShopAdmin data folder;
3. waits until the API answers, reporting progress, then hands over to the
   normal HTTP client;
4. stops ONLY the process it started when ShopAdmin exits — a service the owner
   started by hand is never touched.

If the address is remote (anything that is not 127.0.0.1/localhost/::1) nothing
is ever launched; the app just connects over HTTP as before.

The child is placed in a Windows Job Object (see :mod:`.jobobject`) so it cannot
be orphaned if ShopAdmin crashes.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal

from ..api_client import ApiError, ShopApiClient
from ..logging_setup import get_logger
from ..paths import app_dir, data_dir, is_frozen
from .jobobject import JobObject

log = get_logger("service")

SERVICE_EXE_NAME = "ShopSystem.exe"
SERVICE_LOG_NAME = "shopapi.log"

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

MSG_NOT_FOUND = (
    "سرویس فروشگاه (ShopSystem.exe) در کنار این برنامه پیدا نشد. "
    "لطفاً آن را در همان پوشه قرار دهید."
)
MSG_START_FAILED = (
    "راه‌اندازی سرویس فروشگاه ناموفق بود. لطفاً برنامه را دوباره اجرا کنید."
)
#: Shown when the service starts and immediately exits — almost always a missing
#: or incomplete .env next to ShopSystem.exe, which the owner can actually fix.
MSG_START_EXITED = (
    "سرویس فروشگاه بلافاصله بسته شد. معمولاً علت آن نبود یا ناقص بودن پروندهٔ "
    ".env در پوشهٔ ShopSystem است. آن پرونده را از .env.example بسازید و "
    "ADMIN_API_KEY را در آن وارد کنید، سپس دوباره تلاش کنید.\n"
    "جزئیات در پروندهٔ shopapi.log ثبت شده است."
)
MSG_START_TIMEOUT = (
    "سرویس فروشگاه در زمان مورد انتظار آماده نشد. چند لحظه صبر کنید و دوباره تلاش کنید."
)
#: The installed server runs as a Windows scheduled task; ShopAdmin never starts
#: a second copy of it, it can only ask Windows to run that task.
MSG_TASK_NOT_RUNNING = (
    "سرور فروشگاه روی این رایانه به‌صورت سرویس ویندوز نصب است ولی پاسخ نمی‌دهد. "
    "رایانه را یک‌بار دوباره راه‌اندازی کنید یا از مدیر سیستم بخواهید وظیفهٔ «ShopServer» "
    "را در Task Scheduler اجرا کند."
)
SERVER_TASK_NAME = "ShopServer"


def server_task_installed() -> bool:
    """True when the server setup registered the boot-time scheduled task."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", SERVER_TASK_NAME],
                                capture_output=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class ServiceState(str, Enum):
    """What the top-bar indicator shows."""

    CONNECTED = "connected"      # سرویس فروشگاه: متصل
    STARTING = "starting"        # سرویس فروشگاه: در حال راه‌اندازی
    OFFLINE = "offline"          # سرویس فروشگاه: قطع
    REMOTE = "remote"            # سرور راه دور — ما چیزی اجرا نمی‌کنیم

    @property
    def label_fa(self) -> str:
        return {
            ServiceState.CONNECTED: "سرویس فروشگاه: متصل",
            ServiceState.STARTING: "سرویس فروشگاه: در حال راه‌اندازی",
            ServiceState.OFFLINE: "سرویس فروشگاه: قطع",
            ServiceState.REMOTE: "سرویس فروشگاه: راه دور",
        }[self]


@dataclass
class LaunchResult:
    ok: bool
    message: str = ""
    launched: bool = False
    #: True when the service exists but simply did not answer in time. Not a
    #: configuration problem, so it should NOT interrupt the user with a dialog.
    transient: bool = False


def host_of(base_url: str) -> str:
    """Host part of a base URL, lower-cased, without the port."""
    try:
        return (urlparse(str(base_url or "")).hostname or "").strip().lower()
    except ValueError:
        return ""


def is_local_address(base_url: str) -> bool:
    """True when the address points at this very machine."""
    return host_of(base_url) in LOCAL_HOSTS


def find_service_executable() -> Optional[Path]:
    """Locate ``ShopSystem.exe`` next to ShopAdmin (or beside the project)."""
    roots: list[Path] = []
    here = app_dir()
    roots.append(here)
    if is_frozen():
        # Installed layout: %ProgramFiles%\ShopAdmin\{ShopAdmin.exe, ShopSystem\...}
        roots.append(here / "ShopSystem")
        roots.append(here.parent / "ShopSystem")
    else:
        # Source layout: shopadmin/ next to shopapi/
        roots.append(here.parent / "ShopSystem")
        roots.append(here.parent / "shopapi" / "dist" / "ShopSystem")

    for root in roots:
        candidate = root / SERVICE_EXE_NAME
        if candidate.is_file():
            return candidate

    # Last resort: any nearby copy, but never scan the whole disk.
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for entry in root.glob(f"**/{SERVICE_EXE_NAME}"):
                if entry.is_file():
                    return entry
        except OSError:
            continue
    return None


class ShopSystemService:
    """Owns the lifecycle of the local shopapi process."""

    def __init__(self, base_url: str = "", timeout: float = 12.0,
                 server_cert_pem: str = "") -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.server_cert_pem = server_cert_pem
        self._process: Optional[subprocess.Popen] = None
        self._job = JobObject()
        self._log_handle = None

    # ------------------------------------------------------------------ state
    @property
    def started_by_us(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process is not None else None

    def is_reachable(self, *, timeout: float = 2.5) -> bool:
        """Quick health probe; never raises."""
        if not self.base_url:
            return False
        probe = ShopApiClient(self.base_url, "", timeout=timeout,
                              server_cert_pem=self.server_cert_pem)
        try:
            probe.health()
            return True
        except ApiError:
            return False
        except Exception:  # noqa: BLE001 - a probe must never crash startup
            return False
        finally:
            probe.close()

    # ------------------------------------------------------------------ start
    def _service_log_path(self) -> Path:
        return data_dir() / SERVICE_LOG_NAME

    def start(self, *, on_progress: Callable[[str], None] | None = None) -> LaunchResult:
        """Ensure the local service is running. Blocking; call off the GUI thread."""
        def progress(message: str) -> None:
            log.info("%s", message)
            if on_progress is not None:
                try:
                    on_progress(message)
                except Exception:  # noqa: BLE001
                    pass

        if not is_local_address(self.base_url):
            progress(f"address {host_of(self.base_url)} is remote; not launching anything")
            return LaunchResult(ok=True, launched=False)

        if self.is_reachable():
            progress("the service is already answering; nothing to start")
            return LaunchResult(ok=True, launched=False)

        if self.base_url.startswith("https://") or server_task_installed():
            # Installed server: Windows owns it. Ask the task to run (works when
            # this account may), never start a private second copy.
            progress("the server is installed as a scheduled task; asking Windows to run it")
            subprocess.run(["schtasks", "/Run", "/TN", SERVER_TASK_NAME], capture_output=True,
                           timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.is_reachable(timeout=2.0):
                    return LaunchResult(ok=True, launched=False)
                time.sleep(1.5)
            return LaunchResult(ok=False, message=MSG_TASK_NOT_RUNNING, transient=True)

        executable = find_service_executable()
        if executable is None:
            log.error("ShopSystem.exe not found next to %s", app_dir())
            return LaunchResult(ok=False, message=MSG_NOT_FOUND)

        progress(f"starting {executable.name}")
        try:
            self._log_handle = open(self._service_log_path(), "ab", buffering=0)
            creation_flags = 0
            if os.name == "nt":
                creation_flags = (
                    subprocess.CREATE_NO_WINDOW  # no console window at all
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            self._process = subprocess.Popen(  # noqa: S603 - fixed, verified path
                [str(executable)],
                cwd=str(executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                close_fds=True,
            )
        except OSError as exc:
            log.exception("could not start the service: %s", type(exc).__name__)
            return LaunchResult(ok=False, message=MSG_START_FAILED)

        log.info("service started with pid=%s", self._process.pid)
        if not self._job.assign(self._process.pid):
            log.warning("service pid=%s is not in a job object; it could be orphaned "
                        "if ShopAdmin crashes", self._process.pid)

        if self._wait_until_ready(progress):
            return LaunchResult(ok=True, launched=True)
        if self._process.poll() is not None:
            log.error("the service exited early with code %s", self._process.returncode)
            return LaunchResult(ok=False, launched=True, message=MSG_START_EXITED)
        # Started, still running, just not answering yet: keep it, report softly.
        return LaunchResult(ok=False, launched=True, message=MSG_START_TIMEOUT,
                            transient=True)

    def _wait_until_ready(self, progress: Callable[[str], None]) -> bool:
        deadline = time.monotonic() + self.timeout
        attempt = 0
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False
            attempt += 1
            if self.is_reachable(timeout=2.0):
                progress(f"the service answered after {attempt} probe(s)")
                return True
            time.sleep(0.7)
        return False

    # ------------------------------------------------------------------ stop
    def stop(self, *, graceful_timeout: float = 5.0) -> None:
        """Stop ONLY the process this manager started."""
        process = self._process
        if process is None:
            self._close_log()
            return
        if process.poll() is None:
            log.info("stopping the child service pid=%s", process.pid)
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=graceful_timeout)
                log.info("the service stopped cleanly")
            except subprocess.TimeoutExpired:
                log.warning("the service did not stop in %.0fs; killing it",
                            graceful_timeout)
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    log.error("could not kill the child service")
        else:
            log.info("the child service had already exited (code %s)", process.returncode)

        self._process = None
        self._close_log()
        # Closing the job handle is belt-and-braces: even if the steps above
        # failed, Windows kills everything left in the job.
        self._job.close()

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None


class ServiceMonitor(QObject):
    """Qt-facing wrapper: owns a :class:`ShopSystemService` and reports state.

    Every potentially slow operation (probing, launching, waiting for readiness)
    runs on a background thread so the window keeps painting.
    """

    state_changed = Signal(object)          # ServiceState
    message = Signal(str)                   # Persian, user-facing
    failed = Signal(str)                    # Persian failure message
    failed_soft = Signal(str)               # Persian, but transient (no dialog)

    def __init__(self, base_url: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = ShopSystemService(base_url)
        self._state = ServiceState.OFFLINE
        self._busy = False

    # ------------------------------------------------------------------ props
    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def service(self) -> ShopSystemService:
        return self._service

    @property
    def started_by_us(self) -> bool:
        return self._service.started_by_us

    def set_base_url(self, base_url: str, server_cert_pem: str | None = None) -> None:
        self._service.base_url = base_url
        if server_cert_pem is not None:
            self._service.server_cert_pem = server_cert_pem

    def is_local(self) -> bool:
        return is_local_address(self._service.base_url)

    def _set_state(self, state: ServiceState) -> None:
        if state == self._state:
            return
        self._state = state
        log.info("service state -> %s", state.value)
        self.state_changed.emit(state)

    # ------------------------------------------------------------------ start
    def ensure_running_async(self) -> None:
        """Probe, and start the local service if needed. Never blocks the GUI."""
        if self._busy:
            log.info("service check already in progress")
            return
        self._busy = True
        if self.is_local():
            self._set_state(ServiceState.STARTING)
            self.message.emit("در حال بررسی و راه‌اندازی سرویس فروشگاه…")
        else:
            self._set_state(ServiceState.REMOTE)

        from ..ui.async_utils import run_async

        run_async(
            self._service.start,
            on_progress=self.message.emit,
            on_success=self._on_start_result,
            on_error=self._on_unexpected,
            on_done=self._mark_idle,
        )

    def _mark_idle(self) -> None:
        self._busy = False

    def _on_start_result(self, result: LaunchResult) -> None:
        if result.ok:
            if self.is_local():
                self._set_state(ServiceState.CONNECTED)
                if result.launched:
                    self.message.emit("سرویس فروشگاه راه‌اندازی شد")
                else:
                    self.message.emit("سرویس فروشگاه از قبل در حال اجرا بود")
            else:
                self._set_state(ServiceState.REMOTE)
            return
        self._set_state(ServiceState.OFFLINE)
        if result.message:
            if result.transient:
                # Warn in the status area, but do not interrupt with a dialog.
                self.failed_soft.emit(result.message)
            else:
                self.failed.emit(result.message)

    def _on_unexpected(self, message: str, _kind: str) -> None:
        self._set_state(ServiceState.OFFLINE)
        self.failed.emit(message or MSG_START_FAILED)

    # ------------------------------------------------------------------ probe
    def refresh_state_async(self) -> None:
        """Re-check reachability without launching anything."""
        def work() -> bool:
            return self._service.is_reachable()

        def ok(reachable: bool) -> None:
            if not self.is_local():
                self._set_state(ServiceState.REMOTE)
            elif reachable:
                self._set_state(ServiceState.CONNECTED)
            elif self._service.started_by_us:
                self._set_state(ServiceState.STARTING)
            else:
                self._set_state(ServiceState.OFFLINE)

        from ..ui.async_utils import run_async

        run_async(work, on_success=ok, on_error=lambda _m, _k: None)

    # ------------------------------------------------------------------ stop
    def shutdown(self) -> None:
        """Stop the child service. Called from QApplication.aboutToQuit."""
        try:
            self._service.stop()
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            log.exception("error while stopping the service: %s", type(exc).__name__)
