"""Application controller: startup order, wizard, login, session and logout."""
from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from .api_client import ShopApiClient
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

SESSION_EXPIRED_MESSAGE = (
    "به دلیل عدم فعالیت، نشست شما به پایان رسید. لطفاً دوباره وارد شوید."
)


def prefer_fusion_style(app: QApplication) -> None:
    """Fusion draws the same on every Windows version, which keeps our
    stylesheet predictable."""
    app.setStyle("Fusion")


def apply_env_overrides(store: Store) -> None:
    """A ``.env`` next to the .exe may pre-seed the connection settings.

    Precedence: an explicit environment variable wins over a value already saved
    in the local database, so an administrator can point a machine at another
    server without opening the UI.
    """
    from dotenv import load_dotenv

    from .paths import app_dir

    for candidate in (app_dir() / ".env", data_dir() / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            log.info("loaded configuration from %s", candidate.name)
            break

    base_url = os.getenv("SHOPADMIN_BASE_URL", "").strip()
    api_key = os.getenv("SHOPADMIN_API_KEY", "").strip()
    if base_url:
        store.set_setting("shopapi_base_url", base_url.rstrip("/"))
    if api_key:
        store.set_setting("shopapi_api_key", api_key)
    timeout = os.getenv("SHOPADMIN_SESSION_TIMEOUT_MINUTES", "").strip()
    if timeout.isdigit():
        store.set_setting("session_timeout_minutes", int(timeout))
    refresh = os.getenv("SHOPADMIN_AUTO_REFRESH_SECONDS", "").strip()
    if refresh.isdigit():
        store.set_setting("auto_refresh_seconds", int(refresh))


class ShopAdminApp(QObject):
    """Owns the window lifecycle so nothing is garbage-collected mid-flight."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.store = Store()
        self.auth = AuthService(self.store)
        self.api = ShopApiClient()
        self.context: Optional[AppContext] = None
        self.login_window: Optional[LoginWindow] = None
        self.main_window: Optional[MainWindow] = None
        self.wizard: Optional[SetupWizard] = None
        #: Owned here (not by the window) so it always survives long enough to
        #: be cleaned up on quit, even if the main window is already gone.
        self.service_monitor = None
        self._logging_out = False

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        apply_env_overrides(self.store)
        # Start the local service FIRST, before the wizard or the login window:
        # on a first run this means the owner's "آزمایش اتصال" in the wizard
        # already succeeds, instead of failing because nothing is listening yet.
        self.ensure_service_started()
        if needs_setup(self.store, self.auth):
            log.info("first run detected; showing the setup wizard")
            self.show_wizard()
            return
        if self._try_auto_login():
            return
        self.show_login()

    # -------------------------------------------------------------- service
    def ensure_service_started(self) -> None:
        """Probe the shopapi address and start ShopSystem.exe if it is local.

        Runs BEFORE the login window so that by the time the user is looking at
        a form, the service is already coming up.
        """
        from .services.child_process import ServiceMonitor

        base_url = self.store.base_url
        if not base_url:
            return
        if self.service_monitor is None:
            self.service_monitor = ServiceMonitor(base_url)
            self.service_monitor.failed.connect(self._on_service_failure)
            self.service_monitor.failed_soft.connect(self._on_service_slow)
        else:
            self.service_monitor.set_base_url(base_url)
        self.service_monitor.ensure_running_async()

    def _on_service_failure(self, message: str) -> None:
        """Show a failed auto-start clearly, without blocking the app."""
        from .ui import widgets

        parent = self.main_window or self.login_window or self.wizard
        log.warning("service start reported a problem: %s", message)
        try:
            widgets.error(parent, "سرویس فروشگاه", message)
        except Exception as exc:  # noqa: BLE001 - a dialog must never be fatal
            log.warning("could not show the service error dialog: %s", type(exc).__name__)

    def _on_service_slow(self, message: str) -> None:
        """The service is starting but slow: inform, never block with a dialog."""
        log.warning("service is slow to become ready: %s", message)

    # -------------------------------------------------------------- auto login
    def _try_auto_login(self) -> bool:
        """Sign in from the saved token, skipping the login window entirely.

        Returns True when the user landed on the dashboard. Any failure simply
        falls through to the normal login window — the user never sees an error
        for a stale token.
        """
        if not self.store.get_setting("remember_me", False):
            return False
        if not self.auth.has_saved_session():
            return False

        result = self.auth.try_auto_login()
        if result is None:
            log.info("auto login was not possible; showing the login window")
            return False

        principal = result.principal
        log.info("landing directly on the dashboard as %s", principal.username)
        self._open_main_window(principal, auto=True)
        return True

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
        # The address may have changed in the wizard; make sure the monitor is
        # pointed at the final value (the service is already running by now).
        self.ensure_service_started()
        self.show_login()

    # ------------------------------------------------------------------ login
    def show_login(self) -> None:
        self.api.configure(self.store.base_url, self.store.api_key)
        self.login_window = LoginWindow(self.store, self.auth)
        self.login_window.logged_in.connect(self._on_logged_in)
        self.login_window.show()
        _centre(self.login_window)

    def _on_logged_in(self, principal) -> None:
        if self.login_window is not None:
            self.login_window.close()
            self.login_window = None
        self._open_main_window(principal, auto=False)

    def _open_main_window(self, principal, *, auto: bool = False) -> None:
        """Create and show the main window for a signed-in principal."""
        self.api.configure(self.store.base_url, self.store.api_key)
        self.context = AppContext(
            store=self.store,
            auth=self.auth,
            api=self.api,
            principal=principal,
        )
        self.main_window = MainWindow(self.context)
        # Hand the controller-owned monitor to the window's top bar (the window
        # would otherwise create its own, unused, instance).
        self.main_window.attach_service_monitor(self.service_monitor)
        self.main_window.logout_requested.connect(self.logout)
        self.main_window.session_expired.connect(self._session_expired)
        self.main_window.show()
        _centre(self.main_window)
        self.main_window.reset_activity()
        # Make sure the local shopapi service is up, then probe it. The service
        # check runs first so the very first data request already succeeds.
        QTimer.singleShot(50, self.main_window.ensure_service_running)
        QTimer.singleShot(700, self.main_window.check_connection_async)
        log.info("session started for role=%s (auto=%s)", principal.role, auto)

        if auto:
            # Small reassurance that nobody typed a password.
            QTimer.singleShot(
                400,
                lambda: self.main_window.toasts.show_success(
                    f"ورود با کاربر {principal.full_name or principal.username}"
                ),
            )

    # ------------------------------------------------------------------ session
    def shutdown(self) -> None:
        """Stop the local shopapi service we started. Safe to call twice."""
        monitor = self.service_monitor
        if monitor is None:
            return
        self.service_monitor = None
        log.info("application is quitting; stopping the local service if we started it")
        try:
            monitor.shutdown()
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            log.exception("error during service shutdown: %s", type(exc).__name__)

    def _session_expired(self) -> None:
        log.info("session expired after inactivity")
        if self.main_window is not None:
            widgets.info(self.main_window, "پایان نشست", SESSION_EXPIRED_MESSAGE, kind="warning")
        self.logout(message=SESSION_EXPIRED_MESSAGE)

    def logout(self, message: str = "") -> None:
        if self._logging_out:
            return
        self._logging_out = True
        try:
            if self.context is not None and self.context.principal is not None:
                self.store.audit(
                    self.context.principal.username, "logout", "خروج از برنامه"
                )
            if self.main_window is not None:
                self.main_window.close()
                self.main_window = None
            self.context = None
            self.show_login()
            if message and self.login_window is not None:
                self.login_window._fail(message)
                self.login_window.saved_box.setVisible(False)
        finally:
            self._logging_out = False


def _log_credential_backend() -> None:
    """Record where «مرا به خاطر بسپار» will store its token.

    Logged at startup so a support call can tell in one line whether the Windows
    Credential Manager is being used, or the obfuscated fallback file.
    """
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
    """Place a window in the middle of the primary screen."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    geometry = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(geometry.center())
    widget.move(frame.topLeft())


def run(argv: list[str] | None = None) -> int:
    """Entry point used by ``run_shopadmin.py`` and the packaged .exe."""
    logger = setup_logging()
    logger.info("Python %s, frozen=%s", sys.version.split()[0], is_frozen())
    _log_credential_backend()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("مدیریت فروشگاه")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    prefer_fusion_style(app)
    theme.apply_theme(app)

    controller = ShopAdminApp(app)
    # Stop the ShopSystem.exe we started when the application quits, however it
    # quits (window closed, logout+exit, or a fatal error).
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
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
