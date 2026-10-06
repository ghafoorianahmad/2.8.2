"""Application controller: startup order, wizard, sign-in, notifications, lock."""
from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .api_client import MSG_SESSION_EXPIRED, ShopApiClient
from .auth import AuthService
from .logging_setup import get_logger, setup_logging
from .paths import APP_NAME, data_dir, is_frozen
from .store import Store
from .ui import theme, widgets
from .ui.context import AppContext
from .ui.login_window import LoginWindow
from .ui.main_window import MainWindow
from .ui.wizard import SetupWizard, needs_setup

log = get_logger("main")

SESSION_LOCKED_MESSAGE = (
    "به دلیل عدم فعالیت، برنامه قفل شد. برای ادامه گذرواژه را دوباره وارد کنید. "
    "اعلان‌های فروشگاه در این مدت همچنان نمایش داده می‌شوند."
)


def prefer_fusion_style(app: QApplication) -> None:
    """Fusion draws the same on every Windows version, which keeps our
    stylesheet predictable."""
    app.setStyle("Fusion")


def apply_env_overrides(store: Store) -> None:
    """A ``.env`` next to the .exe may pre-seed the server address.

    Precedence: an explicit environment variable wins over a value already saved
    in the local database, so an administrator can point a machine at another
    server without opening the UI. No secret is ever read from here: clients
    sign in with their own username and password.
    """
    from dotenv import load_dotenv

    from .paths import app_dir

    for candidate in (app_dir() / ".env", data_dir() / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            log.info("loaded configuration from %s", candidate.name)
            break

    base_url = os.getenv("SHOPADMIN_BASE_URL", "").strip()
    if base_url:
        store.set_setting("shopapi_base_url", base_url.rstrip("/"))
    timeout = os.getenv("SHOPADMIN_SESSION_TIMEOUT_MINUTES", "").strip()
    if timeout.isdigit():
        store.set_setting("session_timeout_minutes", int(timeout))
    refresh = os.getenv("SHOPADMIN_AUTO_REFRESH_SECONDS", "").strip()
    if refresh.isdigit():
        store.set_setting("auto_refresh_seconds", int(refresh))


class ShopAdminApp(QObject):
    """Owns the window lifecycle so nothing is garbage-collected mid-flight."""

    #: Emitted from any thread when the server rejects our session.
    _session_invalid = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.store = Store()
        self.api = ShopApiClient()
        self.auth = AuthService(self.store, self.api)
        self.context: Optional[AppContext] = None
        self.login_window: Optional[LoginWindow] = None
        self.main_window: Optional[MainWindow] = None
        self.wizard: Optional[SetupWizard] = None
        self.watcher = None
        self.notifier = None
        #: Owned here (not by the window) so it always survives long enough to
        #: be cleaned up on quit, even if the main window is already gone.
        self.service_monitor = None
        self._logging_out = False
        self._locked = False
        self._quitting = False
        # The API client may report a dead session from a worker thread; a
        # queued signal brings that back to the GUI thread.
        self._session_invalid.connect(self._on_session_invalid, Qt.ConnectionType.QueuedConnection)
        self.api.on_session_invalid = self._session_invalid.emit

    # ------------------------------------------------------------------ start
    def start(self, *, server_setup: bool = False) -> None:
        apply_env_overrides(self.store)
        if server_setup:
            self.show_server_setup()
            return
        self.ensure_service_started()
        if needs_setup(self.store):
            log.info("first run detected; showing the setup wizard")
            self.show_wizard()
            return
        self._configure_api()
        if self._try_auto_login():
            return
        self.show_login()

    def _configure_api(self) -> None:
        """Point the client at the saved server, with its pinned certificate."""
        self.api.configure(self.store.base_url)
        self.api.set_server_cert(self.store.server_cert_pem)

    # -------------------------------------------------------------- service
    def ensure_service_started(self) -> None:
        """Probe the shopapi address and start ShopSystem.exe if it is local."""
        from .services.child_process import ServiceMonitor

        base_url = self.store.base_url
        if not base_url:
            return
        if self.service_monitor is None:
            self.service_monitor = ServiceMonitor(base_url)
            self.service_monitor.failed.connect(self._on_service_failure)
            self.service_monitor.failed_soft.connect(self._on_service_slow)
        self.service_monitor.set_base_url(base_url, self.store.server_cert_pem)
        self.service_monitor.ensure_running_async()

    def _on_service_failure(self, message: str) -> None:
        parent = self.main_window or self.login_window or self.wizard
        log.warning("service start reported a problem: %s", message)
        try:
            widgets.error(parent, "سرویس فروشگاه", message)
        except Exception as exc:  # noqa: BLE001 - a dialog must never be fatal
            log.warning("could not show the service error dialog: %s", type(exc).__name__)

    def _on_service_slow(self, message: str) -> None:
        log.warning("service is slow to become ready: %s", message)

    # -------------------------------------------------------------- auto login
    def _try_auto_login(self) -> bool:
        if not self.store.get_setting("remember_me", False):
            return False
        if not self.auth.has_saved_session():
            return False
        result = self.auth.try_auto_login()
        if result is None:
            log.info("auto login was not possible; showing the login window")
            return False
        log.info("landing directly on the dashboard as %s", result.principal.username)
        self._signed_in(result, auto=True)
        return True

    # ------------------------------------------------------------ server setup
    def show_server_setup(self) -> None:
        """Run on the server computer (as administrator) to install the server."""
        from .ui.server_setup_wizard import ServerSetupWizard

        self.server_wizard = ServerSetupWizard()
        self.server_wizard.completed.connect(self._server_setup_done)
        self.server_wizard.show()
        _centre(self.server_wizard)

    def _server_setup_done(self, base_url: str, pem: str) -> None:
        # The certificate comes from the server's own file: no fingerprint
        # question is needed on this computer.
        self.store.configure_connection(base_url, pem)
        self.store.set_setting("wizard_completed", True)
        self.store.audit("setup", "server_setup", "سرور فروشگاه روی این رایانه راه‌اندازی شد")
        self._configure_api()
        self.show_login()

    # ------------------------------------------------------------------ wizard
    def show_wizard(self) -> None:
        self.wizard = SetupWizard(self.store, self.auth)
        self.wizard.finished.connect(self._wizard_done)
        self.wizard.show()
        _centre(self.wizard)

    def _wizard_done(self) -> None:
        if self.wizard is not None:
            self.wizard.close()
            self.wizard = None
        log.info("setup wizard finished")
        self.ensure_service_started()
        self._configure_api()
        self.show_login()

    # ------------------------------------------------------------------ login
    def show_login(self, message: str = "") -> None:
        self._configure_api()
        if self.login_window is None:
            self.login_window = LoginWindow(self.store, self.auth)
            self.login_window.logged_in.connect(self._on_logged_in)
        else:
            self.login_window.reset()
        if message:
            self.login_window.show_message(message)
        self.login_window.show()
        self.login_window.raise_()
        self.login_window.activateWindow()
        _centre(self.login_window)

    def _on_logged_in(self, result) -> None:
        if self.login_window is not None:
            self.login_window.close()
            self.login_window = None
        self._signed_in(result, auto=False)

    def _signed_in(self, result, *, auto: bool) -> None:
        """A server session exists: force a password change if asked, then open."""
        if result.must_change_password:
            from .ui.password_dialog import ForcedPasswordChangeDialog

            dialog = ForcedPasswordChangeDialog(self.auth)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.auth.logout()
                self.show_login()
                return
        principal = result.principal

        if self._locked and self.main_window is not None and self.context is not None:
            if self.context.principal and self.context.principal.user_id == principal.user_id:
                self._unlock()
                return
            # Somebody else signed in at the lock screen: close the old session.
            self._close_session(end_server_session=False)

        self._open_main_window(principal, auto=auto)

    def _open_main_window(self, principal, *, auto: bool = False) -> None:
        self.context = AppContext(
            store=self.store,
            auth=self.auth,
            api=self.api,
            principal=principal,
        )
        self._start_notifications()
        self.context.notifier = self.notifier
        self.main_window = MainWindow(self.context)
        self.main_window.attach_service_monitor(self.service_monitor)
        self.main_window.logout_requested.connect(self.logout)
        self.main_window.session_expired.connect(self._lock)
        self.main_window.close_requested.connect(self._on_main_close)
        self.main_window.show()
        _centre(self.main_window)
        self.main_window.reset_activity()
        QTimer.singleShot(50, self.main_window.ensure_service_running)
        QTimer.singleShot(700, self.main_window.check_connection_async)
        log.info("session started for role=%s (auto=%s)", principal.role, auto)

        if auto:
            QTimer.singleShot(
                400,
                lambda: self.main_window and self.main_window.toasts.show_success(
                    f"ورود با کاربر {principal.full_name or principal.username}"
                ),
            )

    # ------------------------------------------------------------ notifications
    def _start_notifications(self) -> None:
        from .notifications import EventWatcher, TrayNotifier

        if self.notifier is None:
            self.notifier = TrayNotifier(self.store, self)
            self.notifier.open_requested.connect(self._open_from_tray)
            self.notifier.quit_requested.connect(self.quit_application)
        # Keep running in the tray when the window is closed, if a tray exists.
        self.app.setQuitOnLastWindowClosed(self.notifier.tray is None)

        if self.watcher is not None:
            self.watcher.stop()
        interval = self.store.get_int_setting("event_poll_seconds", 15, minimum=5, maximum=600)
        self.watcher = EventWatcher(self.store.base_url, self.api.token,
                                    interval_seconds=interval, parent=self,
                                    server_cert_pem=self.store.server_cert_pem)
        self.watcher.events_arrived.connect(self._on_server_events)
        self.watcher.session_lost.connect(self._on_session_invalid)
        self.watcher.start()

    def _stop_notifications(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher.client.close()
            self.watcher = None

    def _on_server_events(self, events: list) -> None:
        if self.notifier is not None:
            self.notifier.handle_events(events)
        if self.context is not None:
            self.context.server_events.emit(events)
            self.context.data_changed.emit()

    def _open_from_tray(self, page: str, filter_key: str) -> None:
        if self._locked or self.main_window is None:
            if self.login_window is not None:
                self.login_window.show()
                self.login_window.raise_()
                self.login_window.activateWindow()
            return
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()
        if page:
            self.main_window.navigate(page, filter_key)

    def _on_main_close(self) -> None:
        """Window closed with the ✕: stay in the tray, or quit when there is none."""
        if self.notifier is not None and self.notifier.tray is not None \
                and self.store.get_setting("close_to_tray", True):
            self.main_window.hide()
            self.notifier.tray.showMessage(
                "مدیریت فروشگاه",
                "برنامه در کنار ساعت ویندوز فعال ماند تا اعلان‌ها را دریافت کنید. "
                "برای خروج کامل از منوی همان آیکون استفاده کنید.",
            )
            return
        self.quit_application()

    # ------------------------------------------------------------------ lock
    def _lock(self) -> None:
        """Inactivity: hide the data, keep the server session for notifications."""
        if self._locked or self.main_window is None:
            return
        log.info("locking after inactivity")
        self._locked = True
        self.main_window.hide()
        username = self.context.principal.username if self.context and self.context.principal else ""
        self.show_login(SESSION_LOCKED_MESSAGE)
        if self.login_window is not None and username:
            self.login_window.prefill_username(username)

    def _unlock(self) -> None:
        """Same user signed in again: keep the window, swap to the new session."""
        old_token = self.watcher.client.token if self.watcher is not None else ""
        self._locked = False
        if self.watcher is not None:
            self.watcher.set_token(self.api.token)
            if not self.watcher.running:
                self.watcher.start()
        if old_token and old_token != self.api.token:
            _logout_token(self.store.base_url, old_token, self.store.server_cert_pem)
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.reset_activity()
        log.info("unlocked")

    # ------------------------------------------------------------------ session
    def _on_session_invalid(self) -> None:
        """The server no longer accepts our token (expired, revoked, role changed)."""
        if self._quitting or self.context is None:
            return
        log.info("server session ended; returning to the login window")
        self._close_session(end_server_session=False)
        self.auth.forget_remembered()
        self.show_login(MSG_SESSION_EXPIRED)

    def _close_session(self, *, end_server_session: bool) -> None:
        self._stop_notifications()
        if end_server_session:
            self.auth.logout()
        if self.main_window is not None:
            self.main_window.allow_close = True
            self.main_window.close()
            self.main_window = None
        self.context = None
        self._locked = False

    def logout(self, message: str = "") -> None:
        if self._logging_out:
            return
        self._logging_out = True
        try:
            if self.context is not None and self.context.principal is not None:
                self.store.audit(self.context.principal.username, "logout", "خروج از برنامه")
            self._close_session(end_server_session=True)
            if needs_setup(self.store):
                # e.g. the server address was changed in the settings page
                self.show_wizard()
            else:
                self.show_login(message)
        finally:
            self._logging_out = False

    def quit_application(self) -> None:
        self._quitting = True
        self._stop_notifications()
        if self.notifier is not None:
            self.notifier.hide()
        if self.main_window is not None:
            self.main_window.allow_close = True
        self.app.quit()

    def shutdown(self) -> None:
        """Stop the local shopapi service we started. Safe to call twice."""
        self._stop_notifications()
        if self.notifier is not None:
            self.notifier.hide()
        monitor = self.service_monitor
        if monitor is None:
            return
        self.service_monitor = None
        log.info("application is quitting; stopping the local service if we started it")
        try:
            monitor.shutdown()
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            log.exception("error during service shutdown: %s", type(exc).__name__)


def _logout_token(base_url: str, token: str, server_cert_pem: str = "") -> None:
    """End an old server session in the background (best effort)."""
    from .ui.async_utils import run_async

    def work() -> None:
        client = ShopApiClient(base_url, token, timeout=5, server_cert_pem=server_cert_pem)
        try:
            client.logout()
        finally:
            client.close()

    run_async(work)


def _log_credential_backend() -> None:
    try:
        from .credentials import backend_name, keyring_available

        if keyring_available():
            log.info("credential store: OS keyring (%s)", backend_name())
        else:
            log.warning(
                "credential store: OS keyring unavailable; the remember-me token "
                "will use the obfuscated local file (never plain text)"
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never break startup
        log.warning("credential store check failed: %s", type(exc).__name__)


def _centre(widget) -> None:
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    geometry = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(geometry.center())
    widget.move(frame.topLeft())


INSTANCE_MUTEX = "ShopAdminRunning"   # also checked by the installer (AppMutex)


def _hold_instance_mutex():
    """A named mutex so the installer can tell the app is running."""
    try:
        import ctypes

        return ctypes.windll.kernel32.CreateMutexW(None, False, INSTANCE_MUTEX)
    except Exception:  # noqa: BLE001 - non-Windows
        return None


def _instance_server_name() -> str:
    import getpass

    return f"ShopAdmin-{getpass.getuser()}"


def _activate_running_instance() -> bool:
    """True when another copy is running: it is asked to show itself."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(_instance_server_name())
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def _listen_for_second_instances(controller: "ShopAdminApp"):
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(_instance_server_name())
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        controller._open_from_tray("", "")

    server.newConnection.connect(on_connection)
    server.listen(_instance_server_name())
    return server


def run(argv: list[str] | None = None) -> int:
    """Entry point used by ``run_shopadmin.py`` and the packaged .exe."""
    logger = setup_logging()
    logger.info("Python %s, frozen=%s", sys.version.split()[0], is_frozen())
    _log_credential_backend()
    args = list(argv if argv is not None else sys.argv)
    server_setup = "--server-setup" in args

    if server_setup:
        from .server_setup import is_admin, relaunch_elevated

        if not is_admin():
            # Ask Windows for administrator rights (UAC) and let that copy work.
            relaunch_elevated(["--server-setup"])
            return 0

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("مدیریت فروشگاه")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    prefer_fusion_style(app)
    theme.apply_theme(app)
    app.setWindowIcon(theme.app_icon())

    if not server_setup and _activate_running_instance():
        logger.info("another copy is already running; asked it to show itself")
        return 0
    mutex = _hold_instance_mutex()  # noqa: F841 - held for the life of the process

    controller = ShopAdminApp(app)
    instance_server = _listen_for_second_instances(controller)  # noqa: F841
    app.aboutToQuit.connect(controller.shutdown)
    controller.start(server_setup=server_setup)
    return app.exec()


def main() -> int:
    """Console-script friendly wrapper with a Persian fatal-error dialog."""
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        log.exception("fatal startup error: %s", type(exc).__name__)
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "خطای آغاز برنامه",
                "برنامه نتوانست آغاز شود. جزئیات در فایل لاگ ثبت شد.\n"
                "لطفاً برنامه را دوباره اجرا کنید یا با پشتیبانی تماس بگیرید.",
            )
        except Exception:  # pragma: no cover
            pass
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
