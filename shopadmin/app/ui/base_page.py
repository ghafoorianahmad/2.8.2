"""Base class for every page: header, refresh plumbing and toast helpers."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from . import theme, widgets
from .async_utils import AutoRefresh, run_async
from .context import AppContext


class BasePage(QWidget):
    """Common scaffolding: a title row, an optional toolbar and a body.

    Subclasses implement :meth:`build_body` and :meth:`load`.
    """

    title = "صفحه"
    subtitle = ""
    #: v2.7.0: one plain sentence at the top of the page: what it is for.
    help_text = ""
    #: pages that poll shopapi set this to True
    auto_refreshable = False
    #: pages that should reload when another page changes data
    reload_on_data_change = True

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.toasts = widgets.ToastHost(self)
        self._loaded_once = False
        self._busy = False

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ---- header row --------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(widgets.page_title(self.title, self.subtitle), 1)

        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        header.addLayout(self.toolbar)

        self.refresh_button = widgets.button(
            "به‌روزرسانی", icon_name="refresh", tooltip="دریافت دوبارهٔ اطلاعات",
            on_click=self.refresh,
        )
        self.toolbar.addWidget(self.refresh_button)
        root.addLayout(header)
        self.help_label = None
        if self.help_text:
            self.help_label = widgets.label("💡  " + self.help_text, name="PageHelp", wrap=True)
            root.addWidget(self.help_label)

        # ---- body --------------------------------------------------------
        self.body = QVBoxLayout()
        self.body.setSpacing(16)
        root.addLayout(self.body, 1)

        self.build_body()

        self._auto = AutoRefresh(self)
        self._auto.triggered.connect(self._on_auto_refresh)
        if self.auto_refreshable:
            self.configure_auto_refresh()
        self.context.connection_changed.connect(self._on_connection_changed)

    # ---- hooks -----------------------------------------------------------
    def build_body(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def load(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # ---- helpers ---------------------------------------------------------
    def configure_auto_refresh(self) -> None:
        seconds = self.context.auto_refresh_seconds
        self._auto.configure(seconds)
        self.refresh_button.setToolTip(
            f"به‌روزرسانی خودکار هر {_fa(seconds)} ثانیه"
            if seconds > 0
            else "به‌روزرسانی خودکار خاموش است (در تنظیمات قابل تغییر است)"
        )

    def refresh(self) -> None:
        """Force a reload, bypassing the "already loaded" guard."""
        self._loaded_once = True
        self.load()

    def ensure_loaded(self) -> None:
        """Called when the page becomes visible."""
        self.configure_auto_refresh()
        if not self._loaded_once:
            self._loaded_once = True
            self.load()
        else:
            self._auto.resume()

    def leave(self) -> None:
        self._auto.pause()

    def _on_auto_refresh(self) -> None:
        if self.isVisible() and self.context.connection_ok:
            self.load()

    def _on_connection_changed(self, ok: bool) -> None:
        if ok and self.isVisible() and not self._busy:
            return  # the next auto refresh or an explicit refresh will pick it up

    def set_busy(self, busy: bool, message: str = "در حال دریافت اطلاعات…") -> None:
        self._busy = busy
        self.refresh_button.setEnabled(not busy)

    def run(self, fn: Callable, *, on_success: Callable, on_error: Callable | None = None,
            busy_message: str = "در حال دریافت اطلاعات…") -> None:
        """Run a shopapi call off the GUI thread."""
        self.set_busy(True, busy_message)

        def _ok(result) -> None:
            self.context.set_connection(True)
            on_success(result)

        def _err(message: str, kind: str) -> None:
            if kind in ("connection", "timeout"):
                self.context.mark_offline()
            self.set_busy(False)
            handler = on_error or self.default_error
            handler(message, kind)

        run_async(fn, on_success=_ok, on_error=_err, on_done=lambda: self.set_busy(False))

    def default_error(self, message: str, kind: str = "error") -> None:
        self.toasts.show_error(message)

    def show_table_error(self, message: str = "") -> None:
        """Leave a clear failure state in the page's table, not a spinner."""
        table = getattr(self, "table", None)
        if table is not None and hasattr(table, "set_error_state"):
            table.set_error_state(hint=message or
                                  "اتصال به سرور فروشگاه را بررسی کنید و دوباره تلاش کنید.")

    def notify_success(self, message: str) -> None:
        self.toasts.show_success(message)

    def notify_error(self, message: str) -> None:
        self.toasts.show_error(message)

    def notify_warning(self, message: str) -> None:
        self.toasts.show_warning(message)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.toasts._reposition()

    # ---- empty banner helper --------------------------------------------
    def require_connection(self) -> bool:
        if self.context.connection_ok:
            return True
        self.notify_error("ارتباط با سرور فروشگاه برقرار نیست. اتصال را بررسی کنید.")
        return False


def _fa(value: int) -> str:
    from ..persian import to_persian_digits

    return to_persian_digits(value)
