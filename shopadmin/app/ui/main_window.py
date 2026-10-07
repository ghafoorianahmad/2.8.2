"""پنجرهٔ اصلی: نوار کناری سمت راست، نوار بالا و ناحیهٔ محتوا."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..logging_setup import get_logger
from ..paths import APP_VERSION
from ..persian import to_persian_digits
from ..permissions import (
    CUSTOMERS_VIEW,
    DASHBOARD_VIEW,
    ORDERS_VIEW,
    PRODUCTS_VIEW,
    REPORTS_VIEW,
    SERVER_MANAGE,
    SETTINGS_VIEW,
    USERS_VIEW,
)
from ..statuses import ROLE_SUPER_ADMIN, role_fa
from . import theme, widgets
from .context import AppContext
from .pages.customers import CustomersPage
from .pages.dashboard import DashboardPage
from .pages.orders import OrdersPage
from .pages.products import ProductsPage
from .pages.reports import ReportsPage
from .pages.server import ServerPage
from .pages.settings import SettingsPage
from .pages.users import UsersPage

# (key, Persian label, icon, permission)
NAV_ITEMS = (
    ("dashboard", "داشبورد", "dashboard", DASHBOARD_VIEW),
    ("customers", "مشتریان", "customers", CUSTOMERS_VIEW),
    ("orders", "سفارش‌ها", "orders", ORDERS_VIEW),
    ("products", "محصولات", "products", PRODUCTS_VIEW),
    ("reports", "گزارش‌ها", "reports", REPORTS_VIEW),
    ("settings", "تنظیمات", "settings", SETTINGS_VIEW),
    ("users", "کاربران سیستم", "users", USERS_VIEW),
    ("server", "سرور فروشگاه", "server", SERVER_MANAGE),
)

BANNER_TEXT = "حالت آزمایشی — سفارش‌ها واقعاً در حسابداری ثبت نمی‌شوند"

log = get_logger("main_window")

#: Which unread notification kinds belong to which sidebar entry.
BADGE_KINDS = {
    "customers": ("customer_registered",),
    "orders": ("order_created", "receipt_uploaded"),
}


class MainWindow(QMainWindow):
    logout_requested = Signal()
    session_expired = Signal()
    #: The ✕ was pressed; the controller decides between tray and quit.
    close_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.toasts = widgets.ToastHost(self)
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_texts: dict[str, str] = {}
        self._current_key = ""
        #: False: closing hides to the tray (decided by the controller).
        self.allow_close = context.notifier is None

        self.setWindowTitle(f"مدیریت فروشگاه — {context.display_name}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(1180, 720)
        self.resize(1360, 840)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # RTL: the sidebar is added first so it sits on the RIGHT edge.
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main_area(), 1)

        self._last_activity = self._now()
        self._activity_guard = False
        self._clock = QTimer(self)
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(self._refresh_clock)
        self._clock.start()

        self._inactivity = QTimer(self)
        self._inactivity.setInterval(15_000)
        self._inactivity.timeout.connect(self._check_inactivity)
        self._inactivity.start()

        # Installed LAST: the event filter reads _last_activity/_activity_guard,
        # and building the pages above can already emit events.
        self._build_pages()
        self._install_inactivity_filter()
        self._connect_context()
        self._build_service_monitor()
        self._refresh_header()
        self._update_banner()

        self.navigate("dashboard")

    # ------------------------------------------------------------------ layout
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(248)
        sidebar.setStyleSheet(
            f"QFrame#Sidebar {{ background: {theme.SIDEBAR_BG}; "
            f"border: none; }}"
        )
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(6)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(6, 0, 6, 10)
        brand_layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.icon_pixmap("products", 28, "#FFFFFF"))
        logo.setFixedSize(42, 42)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"background: {theme.SIDEBAR_ACTIVE}; border-radius: 12px;")
        brand_layout.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(widgets.label("مدیریت فروشگاه", name="SidebarTitle"))
        titles.addWidget(widgets.label("کنسول مدیر", name="SidebarMuted"))
        brand_layout.addLayout(titles, 1)
        layout.addWidget(brand)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {theme.SIDEBAR_HOVER};")
        layout.addWidget(divider)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, text, icon_name, permission in NAV_ITEMS:
            if not self.context.can(permission):
                continue
            self._nav_texts[key] = text
            button = QPushButton(f"  {text}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setIcon(theme.nav_icon(icon_name))
            button.setIconSize(QSize(20, 20))
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.clicked.connect(lambda _c=False, k=key: self.navigate(k))
            group.addButton(button)
            layout.addWidget(button)
            self._nav_buttons[key] = button

        layout.addStretch(1)

        self.connection_box = QWidget()
        box_layout = QVBoxLayout(self.connection_box)
        box_layout.setContentsMargins(6, 6, 6, 0)
        box_layout.setSpacing(4)
        self.connection_label = widgets.label("", name="SidebarMuted", wrap=True)
        box_layout.addWidget(self.connection_label)
        self.version_label = widgets.label(
            f"نسخهٔ {to_persian_digits(APP_VERSION)}", name="SidebarMuted"
        )
        box_layout.addWidget(self.version_label)
        layout.addWidget(self.connection_box)
        return sidebar

    def _build_main_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_topbar())

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(20, 10, 20, 10)
        banner_layout.setSpacing(10)
        banner_icon = QLabel()
        banner_icon.setPixmap(theme.icon_pixmap("warning", 20, theme.WARNING))
        banner_layout.addWidget(banner_icon)
        self.banner_label = widgets.label(BANNER_TEXT, color=theme.WARNING_TEXT, bold=True, wrap=True)
        banner_layout.addWidget(self.banner_label, 1)
        self.banner.setStyleSheet(
            f"QFrame#Banner {{ background: {theme.WARNING_BG}; "
            f"border-bottom: 1px solid {theme.BORDER}; }}"
        )
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        return container

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(72)
        bar.setStyleSheet(
            f"QFrame#TopBar {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER}; }}"
        )
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(14)

        self.page_title_label = widgets.label("", size=13, bold=True)
        layout.addWidget(self.page_title_label)
        layout.addStretch(1)

        status_box = QWidget()
        status_layout = QHBoxLayout(status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(14, 14)
        status_layout.addWidget(self.status_dot)
        self.status_text = widgets.label("", name="Muted")
        status_layout.addWidget(self.status_text)
        layout.addWidget(status_box)

        layout.addWidget(widgets.vline())

        # ---- shopapi service state (متصل / در حال راه‌اندازی / قطع) ------
        service_box = QWidget()
        service_layout = QHBoxLayout(service_box)
        service_layout.setContentsMargins(0, 0, 0, 0)
        service_layout.setSpacing(8)
        self.service_dot = QLabel()
        self.service_dot.setFixedSize(14, 14)
        service_layout.addWidget(self.service_dot)
        self.service_label = widgets.label("", name="Muted")
        service_layout.addWidget(self.service_label)
        self.service_retry_button = widgets.button(
            "راه‌اندازی", icon_name="refresh", variant="ghost",
            tooltip="تلاش دوباره برای راه‌اندازی سرویس فروشگاه",
            on_click=self.retry_service,
        )
        self.service_retry_button.setVisible(False)
        service_layout.addWidget(self.service_retry_button)
        layout.addWidget(service_box)

        layout.addWidget(widgets.vline())

        user_box = QWidget()
        user_layout = QHBoxLayout(user_box)
        user_layout.setContentsMargins(0, 0, 0, 0)
        user_layout.setSpacing(10)
        avatar = QLabel()
        avatar.setPixmap(theme.icon_pixmap("user", 20, theme.PRIMARY_DARK))
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(f"background: {theme.PRIMARY_SOFT}; border-radius: 19px;")
        user_layout.addWidget(avatar)

        names = QVBoxLayout()
        names.setSpacing(0)
        self.user_name_label = widgets.label("", size=11, bold=True)
        names.addWidget(self.user_name_label)
        user_layout.addLayout(names)
        self.role_badge = widgets.StatusPill("", "approved")
        user_layout.addWidget(self.role_badge)
        layout.addWidget(user_box)

        self.logout_button = widgets.button(
            "خروج", icon_name="logout", on_click=self._request_logout,
            tooltip="خروج از حساب کاربری",
        )
        layout.addWidget(self.logout_button)

        self._status_dot_ok = theme.dot_pixmap(theme.SUCCESS, 14)
        self._status_dot_bad = theme.dot_pixmap(theme.DANGER, 14)
        self._status_dot_unknown = theme.dot_pixmap(theme.TEXT_FAINT, 14)
        self.status_dot.setPixmap(self._status_dot_unknown)
        return bar

    # ------------------------------------------------------------------ pages
    def _build_pages(self) -> None:
        factories = {
            "dashboard": DashboardPage,
            "customers": CustomersPage,
            "orders": OrdersPage,
            "products": ProductsPage,
            "reports": ReportsPage,
            "settings": SettingsPage,
            "users": UsersPage,
            "server": ServerPage,
        }
        for key, text, _icon, permission in NAV_ITEMS:
            if not self.context.can(permission):
                continue
            page = factories[key](self.context)
            self._pages[key] = page
            self.stack.addWidget(page)

    # ------------------------------------------------------------------ nav
    def navigate(self, key: str, filter_key: str = "") -> None:
        page = self._pages.get(key)
        if page is None:
            key = next(iter(self._pages), "")
            page = self._pages.get(key)
            if page is None:
                return

        if self._current_key and self._current_key != key:
            previous = self._pages.get(self._current_key)
            if hasattr(previous, "leave"):
                previous.leave()

        self._current_key = key
        self.stack.setCurrentWidget(page)
        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.page_title_label.setText(getattr(page, "title", ""))
        if filter_key and hasattr(page, "set_filter"):
            page.set_filter(filter_key)
        if key in BADGE_KINDS:
            self.context.mark_seen(*BADGE_KINDS[key])
        if hasattr(page, "ensure_loaded"):
            page.ensure_loaded()
        self._refresh_header()

    def current_page(self) -> Optional[QWidget]:
        return self._pages.get(self._current_key)

    def apply_settings_changed(self) -> None:
        """Settings changed: re-read intervals on every page."""
        for page in self._pages.values():
            if hasattr(page, "configure_auto_refresh"):
                page.configure_auto_refresh()
        self._refresh_header()

    # ------------------------------------------------------------------ header
    def _refresh_header(self) -> None:
        self.user_name_label.setText(self.context.display_name or "—")
        role = self.context.role
        self.role_badge.setText(role_fa(role))
        if role == ROLE_SUPER_ADMIN:
            # Purple text on a white pill: 5.70:1 (white-on-purple would be equal,
            # but this also keeps the badge consistent with the users page).
            self.role_badge.setStyleSheet(
                f"color: {theme.ROLE_PURPLE}; background: {theme.SURFACE}; "
                f"border: 1px solid {theme.ROLE_PURPLE}; border-radius: 10px; "
                f"padding: 3px 10px; font-weight: 700;"
            )
        else:
            foreground, background = theme_status_colors_for_role(role)
            self.role_badge.setStyleSheet(
                f"color: {foreground}; background: {background}; border-radius: 10px; "
                f"padding: 3px 10px; font-weight: 600;"
            )
        self._update_connection_ui()

    def _update_connection_ui(self) -> None:
        if not self.context.store.base_url:
            self.status_dot.setPixmap(self._status_dot_unknown)
            self.status_text.setText("سرور تنظیم نشده")
            self.connection_label.setText("آدرس سرور فروشگاه تنظیم نشده است.")
            return
        if self.context.connection_ok:
            self.status_dot.setPixmap(self._status_dot_ok)
            self.status_text.setText("متصل")
            self.connection_label.setText(
                f"متصل به {self.context.store.base_url}"
            )
            self.connection_label.setStyleSheet(f"color: {theme.SIDEBAR_OK};")
        else:
            self.status_dot.setPixmap(self._status_dot_bad)
            self.status_text.setText("قطع")
            self.connection_label.setText(f"قطع ارتباط با {self.context.store.base_url}")
            self.connection_label.setStyleSheet(f"color: {theme.SIDEBAR_BAD};")

    def _refresh_clock(self) -> None:
        if self._current_key:
            page = self.current_page()
            if page is not None and hasattr(page, "configure_auto_refresh"):
                page.configure_auto_refresh()

    # ------------------------------------------------------- shopapi service
    def _build_service_monitor(self) -> None:
        """Create a ServiceMonitor when the controller did not supply one.

        Normally the application controller owns the monitor (so it can start
        the service before anyone logs in, and always clean it up on quit); this
        fallback keeps :class:`MainWindow` usable on its own, e.g. in tests.
        """
        from ..services.child_process import ServiceMonitor

        monitor = getattr(self, "_injected_service_monitor", None)
        if monitor is None:
            monitor = ServiceMonitor(self.context.store.base_url, self)
        self.attach_service_monitor(monitor)

    def attach_service_monitor(self, monitor) -> None:
        """Connect an externally owned ServiceMonitor to this window's top bar."""
        self.service_monitor = monitor
        self.service_monitor.set_base_url(self.context.store.base_url,
                                         self.context.store.server_cert_pem)
        self.service_monitor.state_changed.connect(self._on_service_state)
        self.service_monitor.message.connect(self._on_service_message)
        self.service_monitor.failed.connect(self._on_service_error)
        self._on_service_state(self.service_monitor.state)

    def ensure_service_running(self) -> None:
        """Ask the manager to probe, and start the local service if needed."""
        if getattr(self, "service_monitor", None) is None:
            return
        self.service_monitor.set_base_url(self.context.store.base_url,
                                         self.context.store.server_cert_pem)
        self.service_monitor.ensure_running_async()

    def retry_service(self) -> None:
        self.service_retry_button.setEnabled(False)
        self.service_retry_button.setText("در حال تلاش…")
        self.ensure_service_running()

    def _on_service_state(self, state) -> None:
        from ..services.child_process import ServiceState

        colors = {
            ServiceState.CONNECTED: (theme.SUCCESS, theme.SUCCESS_DARK),
            ServiceState.STARTING: (theme.WARNING, theme.WARNING_TEXT),
            ServiceState.OFFLINE: (theme.DANGER, theme.DANGER),
            ServiceState.REMOTE: (theme.INFO, theme.INFO_DARK),
        }
        dot_color, text_color = colors.get(state, (theme.TEXT_FAINT, theme.TEXT_MUTED))
        self.service_dot.setPixmap(theme.dot_pixmap(dot_color, 14))
        self.service_label.setText(state.label_fa)
        self.service_label.setStyleSheet(f"color: {text_color};")
        self.service_retry_button.setVisible(state == ServiceState.OFFLINE)
        self.service_retry_button.setEnabled(True)
        self.service_retry_button.setText("راه‌اندازی")

    def _on_service_message(self, message: str) -> None:
        if message:
            self.toasts.show(message, "info", 3000)

    def _on_service_error(self, message: str) -> None:
        """A failed auto-start is shown clearly but must not block the app."""
        widgets.error(self, "سرویس فروشگاه", message)
        self.toasts.show_error(message)

    def _update_banner(self) -> None:
        """Yellow banner whenever shopapi runs with accounting writes disabled."""
        show = self.context.dry_run_mode
        self.banner.setVisible(show)

    # ------------------------------------------------------------------ events
    def _connect_context(self) -> None:
        self.context.connection_changed.connect(lambda _ok: self._refresh_header())
        self.context.system_info_changed.connect(lambda _info: self._update_banner())
        self.context.data_changed.connect(self._on_data_changed)
        notifier = self.context.notifier
        if notifier is not None:
            notifier.counts_changed.connect(self._update_badges)
            self._update_badges(dict(notifier.unread))
        self.context.server_events.connect(self._on_server_events)

    def _update_badges(self, unread: dict) -> None:
        """Show «(۳)» next to a sidebar entry with unseen items."""
        for key, kinds in BADGE_KINDS.items():
            button = self._nav_buttons.get(key)
            if button is None:
                continue
            count = sum(int(unread.get(k, 0)) for k in kinds)
            text = self._nav_texts.get(key, "")
            button.setText(f"  {text}  ({to_persian_digits(count)})" if count else f"  {text}")
            button.setProperty("hasBadge", bool(count))
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_server_events(self, events: list) -> None:
        """Something happened on the server: refresh what is on screen now."""
        page = self.current_page()
        key = self._current_key
        if key in BADGE_KINDS and self.isVisible() and self.isActiveWindow():
            self.context.mark_seen(*BADGE_KINDS[key])
        if page is not None and hasattr(page, "refresh") and self.isVisible():
            page.refresh()
        from ..notifications import notice_for

        for event in events:
            notice = notice_for(event)
            if notice is not None:
                self.toasts.show(f"{notice.title}: {notice.body}", "info", 5000)

    def _on_data_changed(self) -> None:
        for key, page in self._pages.items():
            if key == self._current_key:
                continue
            if getattr(page, "reload_on_data_change", False) and hasattr(page, "_loaded_once"):
                page._loaded_once = False

    def _install_inactivity_filter(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Track user activity for the session timeout.

        This runs for EVERY event in the application, so it must be trivial and
        must never raise: an exception escaping a Python override of a Qt virtual
        is re-raised by Qt for every subsequent event, which floods the log and
        can recurse. The re-entrancy flag stops the bookkeeping itself from
        generating further activity events.
        """
        if self._activity_guard:
            return False
        try:
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.KeyPress,
                QEvent.Type.Wheel,
                QEvent.Type.TouchBegin,
            ):
                self._activity_guard = True
                try:
                    self._last_activity = self._now()
                finally:
                    self._activity_guard = False
        except Exception as exc:  # noqa: BLE001 - never break the event loop
            log.warning("activity tracking skipped: %s", type(exc).__name__)
        return False

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _check_inactivity(self) -> None:
        timeout = self.context.session_timeout_minutes * 60
        if timeout <= 0:
            return
        if self._now() - self._last_activity >= timeout:
            self._inactivity.stop()
            self.session_expired.emit()

    def _request_logout(self) -> None:
        if widgets.confirm(
            self, "خروج از حساب",
            "آیا می‌خواهید از حساب کاربری خود خارج شوید؟",
            confirm_text="خروج", cancel_text="انصراف",
        ):
            self.logout_requested.emit()

    def reset_activity(self) -> None:
        """Called after a fresh login so the session timer starts clean."""
        self._last_activity = self._now()
        if not self._inactivity.isActive():
            self._inactivity.start()

    def refresh_current_page(self) -> None:
        page = self.current_page()
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def check_connection_async(self) -> None:
        """Probe shopapi so the top-bar dot reflects reality on startup."""
        from .async_utils import run_async

        def work():
            return self.context.api.test_connection()

        run_async(
            work,
            on_success=self._on_connection_probe_ok,
            on_error=lambda _m, _k: self.context.mark_offline(),
        )

    def _on_connection_probe_ok(self, info) -> None:
        self.context.apply_system_info(info)
        # Keep the service indicator honest about what the server really is.
        monitor = getattr(self, "service_monitor", None)
        if monitor is not None:
            monitor.refresh_state_async()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.toasts._reposition()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.allow_close:
            event.ignore()
            self.close_requested.emit()
            return
        self._inactivity.stop()
        self._clock.stop()
        super().closeEvent(event)


def theme_status_colors_for_role(role: str) -> tuple[str, str]:
    """Foreground/background for a role badge, all meeting WCAG AA."""
    mapping = {
        "admin": (theme.PRIMARY_DARK, theme.PRIMARY_LIGHT),
        "operator": (theme.INFO_DARK, theme.INFO_LIGHT),
        "viewer": (theme.TEXT_MUTED, theme.BACKGROUND),
    }
    return mapping.get(role, (theme.TEXT_MUTED, theme.BACKGROUND))
