"""صفحهٔ سرور — وضعیت، تنظیمات، گزارش و راه‌اندازی دوبارهٔ سرور (فقط مدیر کل).

همهٔ این کارها از طریق API و با بررسی نقش روی خود سرور انجام می‌شود. اتصال
حسابداری، کلید ثبت واقعی در حسابداری و کلیدهای سرویس از راه دور تغییر
نمی‌کنند و فقط روی خود رایانهٔ سرور قابل تغییرند.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...api_client import short_fingerprint
from ...edition import is_server_edition
from ...logging_setup import get_logger
from ...permissions import PROXIES_MANAGE, SERVER_MANAGE, SERVER_VIEW
from ...persian import format_shamsi, to_english_digits, to_persian_digits
from ...server_settings import SETTINGS_FA, local_problem, translate_field_errors
from .. import theme, widgets
from ..base_page import BasePage
from ..rtl import RIGHT

PLATFORM_FA = {"bale": "بله", "telegram": "تلگرام"}

log = get_logger("server_page")


def accounting_text(status: dict) -> tuple[str, str]:
    """v2.8.1: the connection row with the real reason (wrong name, no permission, …)."""
    acc = status.get("accounting") or {}
    if acc.get("ok"):
        return (f"متصل ({to_persian_digits(acc.get('latency_ms', 0))} میلی‌ثانیه)",
                theme.SUCCESS_DARK)
    name = str(status.get("accounting_database") or "").strip()
    reason = str(acc.get("message_fa") or "").strip() or "پایگاه‌دادهٔ حسابداری پاسخ نمی‌دهد."
    code = str(acc.get("error_code") or "")
    if code in ("4060", "229", "230"):
        reason += (" (کاربر SQL سرور به این پایگاه‌داده دسترسی ندارد؛ grant_shop_app.ps1 را برای "
                   "همین پایگاه‌داده روی رایانهٔ سرور اجرا کنید.)")
    where = f"«{name}»: " if name else ""
    return f"قطع — {where}{reason}", theme.DANGER


def write_text(status: dict) -> tuple[str, str]:
    """v2.8.1: real writing on/off for the current database, and why it is off."""
    name = str(status.get("accounting_database") or "").strip() or "—"
    if status.get("accounting_write_enabled"):
        if status.get("status_code_configured") is False:
            return (f"روشن برای «{name}»، ولی «کد وضعیت سفارش» تنظیم نشده؛ تا تنظیم نشود "
                    "هیچ سفارشی ثبت نمی‌شود (پایین همین صفحه).", theme.WARNING_TEXT)
        if status.get("test_mode"):
            return f"فعال کامل — پایگاه آزمایشی «{name}» (خواندن و نوشتن آزاد)", theme.SUCCESS_DARK
        return f"فعال — ثبت واقعی در «{name}»", theme.SUCCESS_DARK
    reason = status.get("write_block_reason")
    where = "«تنظیمات سرور» روی رایانهٔ سرور"
    if reason == "not_allowed":
        return (f"خاموش — «{name}» در فهرست پایگاه‌داده‌های مجاز نیست؛ سرور فقط از آن می‌خواند. "
                f"برای ثبت، در {where} آن را مجاز و «ثبت واقعی» را روشن کنید.", theme.WARNING_TEXT)
    if reason == "write_off":
        return (f"خاموش — «{name}» مجاز است ولی «ثبت واقعی» برایش روشن نشده (در {where}).",
                theme.WARNING_TEXT)
    if reason == "no_database":
        return "خاموش — پایگاه‌دادهٔ حسابداری تنظیم نشده است.", theme.WARNING_TEXT
    return f"آزمایشی — بدون ثبت واقعی (فقط در {where} قابل تغییر)", theme.WARNING_TEXT


def server_settings_available() -> bool:
    """«تنظیمات سرور» only in the server edition, on the server computer itself."""
    if not is_server_edition():
        return False
    try:
        from ...server_setup import server_installed_here
    except ImportError:
        return False
    return server_installed_here()


def _uptime_fa(seconds: int) -> str:
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{to_persian_digits(days)} روز")
    if hours:
        parts.append(f"{to_persian_digits(hours)} ساعت")
    parts.append(f"{to_persian_digits(minutes)} دقیقه")
    return " و ".join(parts)


class ServerPage(BasePage):
    title = "تنظیمات سرور فروشگاه"
    subtitle = "وضعیت سرور و ربات‌ها، تنظیمات مشترک فروشگاه، گزارش و راه‌اندازی دوباره"
    help_text = ("تنظیمات رایانهٔ اصلی فروشگاه که برای همهٔ کارکنان یکی است (مدیر، یا "
                 "دسترسی «تنظیمات سرور فروشگاه»). تنظیمات همین رایانه در «تنظیمات برنامه» است.")
    reload_on_data_change = False
    #: v2.8.2: a form page: never reloaded by itself (it wiped what was being typed)
    auto_refreshable = False
    refresh_on_server_events = False

    def build_body(self) -> None:
        if not self.context.can(SERVER_VIEW):
            panel = widgets.Panel()
            panel.body.addWidget(widgets.label("دسترسی غیرمجاز", size=14, bold=True))
            panel.body.addWidget(widgets.label(
                "برای این صفحه دسترسی «تنظیمات سرور فروشگاه — دیدن» لازم است.",
                name="Muted", wrap=True))
            self.body.addWidget(panel)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)
        layout.addWidget(self._build_status_panel())
        layout.addWidget(self._build_telegram_panel())
        layout.addWidget(self._build_settings_panel())
        layout.addWidget(self._build_log_panel())
        layout.addStretch(1)
        scroll.setWidget(container)
        self.body.addWidget(scroll, 1)
        self._settings: dict = {}
        self._inputs: dict[str, QWidget] = {}

    # ------------------------------------------------------------------ status
    def _build_status_panel(self) -> QWidget:
        panel = widgets.Panel("وضعیت")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self.status_labels: dict[str, QWidget] = {}
        rows = (
            ("accounting", "اتصال به حسابداری"),
            ("write", "ثبت در حسابداری"),
            ("uptime", "مدت روشن بودن سرور"),
            ("version", "نسخه"),
            ("bots", "ربات‌ها"),
            ("telegram", "خوانندهٔ تلگرام"),
            ("health", "پایش سلامت"),
            ("backup", "پشتیبان‌گیری روزانه"),
            ("counts", "در انتظار رسیدگی"),
        )
        for index, (key, caption) in enumerate(rows):
            grid.addWidget(widgets.label(caption + ":", name="Muted"), index, 0)
            value = widgets.label("—", wrap=True)
            grid.addWidget(value, index, 1)
            self.status_labels[key] = value
        grid.setColumnStretch(1, 1)
        panel.body.addLayout(grid)

        panel.body.addWidget(widgets.hline())
        panel.body.addWidget(widgets.label("اثرانگشت امنیتی سرور (برای تأیید روی رایانه‌های کارکنان)",
                                           bold=True))
        self.fingerprint_short = widgets.label("—", size=14, bold=True)
        self.fingerprint_short.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.fingerprint_short.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel.body.addWidget(self.fingerprint_short)
        self.fingerprint_full = widgets.label("", name="Faint", wrap=True)
        self.fingerprint_full.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.fingerprint_full.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel.body.addWidget(self.fingerprint_full)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        # v2.8.1: the server setup wizard with the saved values (database, allowed
        # databases and real writing, network, bot tokens) - on the server only
        self.server_settings_button = widgets.button(
            "تنظیمات سرور (پایگاه‌داده، شبکه، ربات‌ها)", icon_name="settings",
            variant="primary", on_click=self._open_server_settings,
            tooltip="باز کردن دوبارهٔ راه‌اندازی سرور با مقدارهای فعلی؛ نیاز به دسترسی مدیر ویندوز")
        self.server_settings_button.setVisible(server_settings_available()
                                               and self.context.can(SERVER_MANAGE))
        buttons.addWidget(self.server_settings_button)
        self.restart_button = widgets.button(
            "راه‌اندازی دوبارهٔ سرور", icon_name="refresh", variant="danger",
            on_click=self._restart)
        buttons.addWidget(self.restart_button)
        panel.body.addLayout(buttons)
        return panel

    def _open_server_settings(self) -> None:
        try:
            from ...server_setup import relaunch_elevated

            shown = relaunch_elevated(["--server-settings"])
        except Exception as exc:  # noqa: BLE001 - reported below
            log.warning("server settings: elevation failed: %s", type(exc).__name__)
            shown = False
        if shown:
            self.notify_success("پنجرهٔ «تنظیمات سرور» باز می‌شود (پس از تأیید ویندوز).")
        else:
            widgets.error(self, "تنظیمات سرور",
                          "«تنظیمات سرور» به دسترسی مدیر ویندوز نیاز دارد و درخواست آن تأیید نشد. "
                          "دوباره بزنید و در پنجرهٔ ویندوز «Yes / بله» را انتخاب کنید.")

    # ------------------------------------------------------------------ telegram (v2.9.0)
    def _build_telegram_panel(self) -> QWidget:
        panel = widgets.Panel("خوانندهٔ تلگرام و استخر پراکسی")
        panel.body.addWidget(widgets.label(
            "لیست قیمت کانال خودکار خوانده می‌شود و پراکسی‌های تازه هر روز آزموده می‌شوند؛ اگر "
            "پراکسی فعلی قطع شود خودکار سراغ بعدی می‌رود. ورود حساب تلگرام و کلید برنامه در "
            "«تنظیمات سرور» روی خود رایانهٔ سرور است.", name="Muted", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self.tg_labels: dict[str, QWidget] = {}
        for index, (key, caption) in enumerate((
            ("reader", "خواننده"),
            ("price", "لیست قیمت کانال"),
            ("pool", "استخر پراکسی"),
            ("collect", "آخرین جمع‌آوری پراکسی"),
        )):
            grid.addWidget(widgets.label(caption + ":", name="Muted"), index, 0)
            value = widgets.label("—", wrap=True)
            grid.addWidget(value, index, 1)
            self.tg_labels[key] = value
        grid.setColumnStretch(1, 1)
        panel.body.addLayout(grid)
        # v2.9.1: every column as wide as its content (the host was cut with «…»),
        # «منبع» takes the rest; never a horizontal scroll bar
        self.proxy_table = widgets.DataTable(SERVER_PROXY_HEADERS, key="server_proxies",
                                             fit_width=True, stretch_column=5)
        self.proxy_table.set_empty_state("هنوز پراکسی‌ای در استخر نیست",
                                         "یک پراکسی دستی اضافه کنید تا خواننده بتواند شروع کند.",
                                         "wifi")
        self.proxy_table.setMinimumHeight(200)
        panel.body.addWidget(self.proxy_table)
        self.proxy_hint = widgets.label("", name="Muted", wrap=True)
        self.proxy_hint.setVisible(False)
        panel.body.addWidget(self.proxy_hint)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.add_proxy_button = widgets.button(
            "افزودن پراکسی دستی…", icon_name="plus", variant="primary", on_click=self._add_proxy,
            tooltip="پیوند tg://proxy یا t.me/proxy؛ اول از همه امتحان می‌شود")
        self.add_proxy_button.setVisible(self.context.can(PROXIES_MANAGE))
        buttons.addWidget(self.add_proxy_button)
        buttons.addWidget(widgets.button("به‌روزرسانی", icon_name="refresh", on_click=self.load))
        panel.body.addLayout(buttons)
        return panel

    def _show_telegram(self, status: dict) -> None:
        for key, (text, color) in telegram_details(status.get("telegram_worker"),
                                                   status.get("proxy_pool")).items():
            label = self.tg_labels[key]
            label.setText(text)
            label.setStyleSheet(f"color: {color};" if color else "")

    def _load_proxies(self) -> None:
        self.proxy_table.set_busy(True)
        self.run(self.context.api.list_proxies, on_success=self._show_proxies,
                 on_error=self._proxies_unavailable)

    def _show_proxies(self, proxies: list) -> None:
        table = self.proxy_table
        table.set_busy(False)
        table.setRowCount(0)
        active = [p for p in proxies or [] if p.get("state") in ("main", "probation")][:15]
        for p in active:
            row = table.rowCount()
            table.insertRow(row)
            table.set_cell(row, 0, f"{p.get('host') or ''}:{p.get('port') or ''}", bold=True)
            table.set_cell(row, 1, str(p.get("kind") or ""))
            table.set_cell(row, 2, PROXY_STATE_FA.get(p.get("state"), str(p.get("state") or "")))
            failing = bool(p.get("failing_now"))
            checked = bool(p.get("last_ok_at") or p.get("last_fail_at"))
            table.set_cell(row, 3, "قطع" if failing else ("سالم" if checked else "آزموده نشده"),
                           color=theme.DANGER if failing else
                           (theme.SUCCESS_DARK if checked else theme.TEXT_MUTED))
            latency = p.get("last_latency_ms")
            table.set_cell(row, 4, f"{to_persian_digits(latency)} میلی‌ثانیه" if latency else "—")
            table.set_cell(row, 5, proxy_source_fa(p.get("source")))
        self.proxy_hint.setVisible(False)
        if not active:
            table.fill([])

    def _proxies_unavailable(self, message: str, kind: str) -> None:
        self.proxy_table.set_busy(False)
        self.proxy_table.fill([])
        self.proxy_hint.setText("فهرست پراکسی‌ها دیده نشد: " + (message or "")
                                + " (دیدن آن دسترسی «لیست قیمت — دیدن» می‌خواهد.)")
        self.proxy_hint.setVisible(True)

    def _add_proxy(self) -> None:
        from PySide6.QtWidgets import QDialog

        from .pricelist import AddProxyDialog

        dialog = AddProxyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        link, main = dialog.link, dialog.main
        self.run(lambda: self.context.api.add_proxy(link, main),
                 on_success=lambda _r: (self.notify_success(
                     "پراکسی اضافه شد؛ خواننده در چند دقیقه آن را امتحان می‌کند."),
                     self._load_proxies()))

    def load(self) -> None:
        if not self.context.can(SERVER_VIEW):
            return
        self.run(self.context.api.server_status, on_success=self._show_status)
        self._load_proxies()
        self.run(self.context.api.server_settings, on_success=self._show_settings,
                 on_error=self._settings_unavailable)

    def _show_status(self, status: dict) -> None:
        self._set("accounting", *accounting_text(status))
        self._set("write", *write_text(status))
        self._set("uptime", _uptime_fa(status.get("uptime_seconds", 0)))
        self._set("version", to_persian_digits(status.get("version", "—")))

        bots = (status.get("components") or {}).get("bots") or {}
        configured = bots.get("configured") or []
        platforms = bots.get("platforms") or {}
        if not configured:
            self._set("bots", "هیچ رباتی تنظیم نشده است (توکن بله یا تلگرام را در تنظیمات پایین وارد کنید)",
                      theme.WARNING_TEXT)
        else:
            parts = []
            for name in configured:
                state = platforms.get(name) or {}
                label = PLATFORM_FA.get(name, name)
                if state.get("running") and not state.get("consecutive_errors"):
                    parts.append(f"{label}: فعال")
                elif state.get("running"):
                    parts.append(f"{label}: خطا در اتصال ({to_persian_digits(state.get('consecutive_errors'))} بار)")
                else:
                    parts.append(f"{label}: متوقف")
                if state.get("last_ok_at"):
                    parts[-1] += f" — آخرین پاسخ: {format_shamsi(state['last_ok_at'])}"
            bad = any("خطا" in p or "متوقف" in p for p in parts)
            self._set("bots", "\n".join(parts), theme.DANGER if bad else theme.SUCCESS_DARK)

        self._set(*telegram_text(status.get("telegram_worker")))
        self._show_telegram(status)
        self._set(*health_text(status.get("health")))
        self._set(*backup_text(status.get("backup")))

        counts = status.get("counts") or {}
        self._set("counts",
                  f"مشتری منتظر تأیید: {to_persian_digits(counts.get('customers_pending', 0))} — "
                  f"فیش منتظر بررسی: {to_persian_digits(counts.get('orders_receipt_uploaded', 0))} — "
                  f"سفارش منتظر پرداخت: {to_persian_digits(counts.get('orders_awaiting_payment', 0))}")

        fingerprint = status.get("tls_fingerprint") or ""
        if fingerprint:
            self.fingerprint_short.setText(short_fingerprint(fingerprint))
            self.fingerprint_full.setText(fingerprint)
        else:
            self.fingerprint_short.setText("—")
            self.fingerprint_full.setText("سرور بدون https اجرا می‌شود؛ ارتباط در شبکه رمزنگاری نشده است.")
        self.restart_button.setEnabled(bool(status.get("restart_available"))
                                       and self.context.can(SERVER_MANAGE))
        self.restart_button.setToolTip("" if status.get("restart_available") else
                                       "سرور در حالت سرویس اجرا نمی‌شود")

    def _set(self, key: str, text: str, color: str | None = None) -> None:
        label = self.status_labels[key]
        label.setText(text)
        label.setStyleSheet(f"color: {color};" if color else "")

    def _restart(self) -> None:
        if not widgets.confirm(
            self, "راه‌اندازی دوبارهٔ سرور",
            "سرور و ربات‌ها چند ثانیه قطع می‌شوند و با تنظیمات فعلی دوباره بالا می‌آیند. "
            "ادامه می‌دهید؟", confirm_text="راه‌اندازی دوباره", kind="warning",
        ):
            return
        self.run(self.context.api.restart_server,
                 on_success=lambda _r: self.notify_success(
                     "دستور راه‌اندازی دوباره فرستاده شد؛ چند ثانیه بعد صفحه را به‌روز کنید."))

    # ------------------------------------------------------------------ settings
    def _build_settings_panel(self) -> QWidget:
        panel = widgets.Panel("تنظیمات سرور")
        panel.body.addWidget(widgets.label(
            "پس از ذخیره، سرور را دوباره راه‌اندازی کنید تا تغییرات اعمال شود. اتصال به حسابداری، "
            "روشن کردن ثبت واقعی و کلیدهای سرویس فقط روی خود رایانهٔ سرور تغییر می‌کنند.",
            name="Muted", wrap=True))
        self.settings_form = QFormLayout()
        self.settings_form.setLabelAlignment(RIGHT)
        self.settings_form.setHorizontalSpacing(18)
        self.settings_form.setVerticalSpacing(10)
        panel.body.addLayout(self.settings_form)
        self.settings_message = widgets.label("", wrap=True)
        self.settings_message.setVisible(False)
        panel.body.addWidget(self.settings_message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_settings_button = widgets.button(
            "ذخیرهٔ تنظیمات سرور", icon_name="save", variant="primary", on_click=self._save_settings)
        buttons.addWidget(self.save_settings_button)
        # v2.8.2: «تنظیمات سرور فروشگاه — دیدن» only: read, never save
        self.save_settings_button.setEnabled(self.context.can(SERVER_MANAGE))
        self.save_settings_button.setVisible(self.context.can(SERVER_MANAGE))
        panel.body.addLayout(buttons)
        return panel

    def _settings_unavailable(self, message: str, _kind: str) -> None:
        self.save_settings_button.setEnabled(False)
        self._show_settings_message(message, ok=False)

    def _show_settings(self, settings: dict) -> None:
        self._settings = settings
        while self.settings_form.rowCount():
            self.settings_form.removeRow(0)
        self._inputs = {}
        for key, info in settings.items():
            caption, hint, kind = SETTINGS_FA.get(key, (key, "", "text"))
            if info.get("secret"):
                field = QLineEdit()
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                field.setPlaceholderText("تنظیم شده — برای تغییر، مقدار جدید را وارد کنید"
                                         if info.get("set") else "تنظیم نشده")
            elif kind == "bool":
                field = QCheckBox("بله")
                field.setChecked(str(info.get("value", "")).lower() in ("1", "true", "yes", "on"))
            else:
                field = QLineEdit(str(info.get("value") or ""))
                if kind == "int" or key in ("ADMIN_CHAT_IDS", "STOCK_WAREHOUSES"):
                    field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            if hint:
                field.setToolTip(hint)
            self._inputs[key] = field
            field.setEnabled(self.context.can(SERVER_MANAGE))   # v2.8.2: «دیدن» only = read
            self.settings_form.addRow(widgets.label(caption + ":"), field)
        self.save_settings_button.setEnabled(self.context.can(SERVER_MANAGE))

    def has_unsaved_changes(self) -> bool:
        return bool(getattr(self, "_inputs", None)) and bool(self._collect_changes())

    def _collect_changes(self) -> dict[str, str]:
        changes: dict[str, str] = {}
        for key, field in self._inputs.items():
            info = self._settings.get(key) or {}
            if isinstance(field, QCheckBox):
                value = "true" if field.isChecked() else "false"
                current = "true" if str(info.get("value", "")).lower() in ("1", "true", "yes", "on") else "false"
                if value != current:
                    changes[key] = value
            elif info.get("secret"):
                if field.text().strip():   # empty = keep the saved value
                    changes[key] = to_english_digits(field.text()).strip()
            else:
                value = field.text().strip()
                if value != str(info.get("value") or ""):
                    changes[key] = value
        return changes

    def _save_settings(self) -> None:
        changes = self._collect_changes()
        if not changes:
            self._show_settings_message("تغییری برای ذخیره وجود ندارد.", ok=True)
            return
        problems = {k: p for k, v in changes.items() if (p := local_problem(k, v))}
        if problems:
            self._show_settings_message(translate_field_errors(problems), ok=False)
            return

        def ok(_result) -> None:
            self._show_settings_message(
                "تنظیمات روی سرور ذخیره شد. برای اعمال، سرور را دوباره راه‌اندازی کنید.", ok=True)
            self.context.audit("server_settings", "کلیدها: " + "، ".join(sorted(changes)))
            self.run(self.context.api.server_settings, on_success=self._show_settings)
            if self.restart_button.isEnabled() and widgets.confirm(
                self, "اعمال تنظیمات", "سرور اکنون دوباره راه‌اندازی شود؟",
                confirm_text="راه‌اندازی دوباره", cancel_text="بعداً",
            ):
                self.run(self.context.api.restart_server,
                         on_success=lambda _r: self.notify_success("سرور در حال راه‌اندازی دوباره است"))

        self.run(lambda: self.context.api.update_server_settings(changes), on_success=ok,
                 on_error=lambda m, _k: self._show_settings_message(m, ok=False))

    def _show_settings_message(self, text: str, *, ok: bool) -> None:
        self.settings_message.setText(text)
        self.settings_message.setStyleSheet(f"color: {theme.SUCCESS_DARK if ok else theme.DANGER};")
        self.settings_message.setVisible(True)

    # ------------------------------------------------------------------ log
    def _build_log_panel(self) -> QWidget:
        panel = widgets.Panel("گزارش سرور (app.log)")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self.log_view.setFont(font)
        self.log_view.setMinimumHeight(260)
        self.log_view.setPlaceholderText("برای دیدن آخرین رویدادهای سرور، «نمایش گزارش» را بزنید.")
        panel.body.addWidget(self.log_view)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("نمایش گزارش", icon_name="file", on_click=self._load_log))
        panel.body.addLayout(buttons)
        return panel

    def _load_log(self) -> None:
        def ok(lines: list) -> None:
            self.log_view.setPlainText("\n".join(lines))
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

        self.run(lambda: self.context.api.server_logs(300), on_success=ok)


HEALTH_NAMES = {"sql": "SQL حسابداری", "bot": "ربات بله", "bale": "اتصال به بله",
                "tg": "کارگر تلگرام", "backup": "پشتیبان‌گیری"}


def backup_text(backup: dict | None) -> tuple[str, str, str | None]:
    """Status-row text for the server's daily backup."""
    if not backup:
        return "backup", "هنوز انجام نشده (روزانه، ساعت ۳ بامداد؛ README_FA بخش پشتیبان)", None
    when = format_shamsi(backup["at"]) if backup.get("at") else "—"
    if not backup.get("ok"):
        reason = backup.get("offsite_error") or backup.get("error") or "نامشخص"
        last = backup.get("last_success_at")
        tail = f" — آخرین پشتیبان موفق: {format_shamsi(last)}" if last else ""
        return "backup", f"ناموفق در {when} ({reason}){tail}", theme.DANGER
    if backup.get("offsite_configured"):
        where = "نسخهٔ رمزگذاری‌شدهٔ بیرون از سرور: سالم"
    else:
        where = "نسخهٔ بیرون از سرور تنظیم نشده (BACKUP_COPY_DIR)"
    text = f"موفق و آزموده — {when}\n{where}"
    return "backup", text, theme.SUCCESS_DARK if backup.get("offsite_configured") else theme.WARNING_TEXT


SERVER_PROXY_HEADERS = ("پراکسی", "نوع", "وضعیت", "الان", "تأخیر", "منبع")
PROXY_STATE_FA = {"main": "اصلی", "probation": "آزمایشی", "retired": "کنار گذاشته",
                  "disabled": "غیرفعال"}
PRICE_OUTCOME_FA = {
    "active": "لیست تازه فعال شد", "held": "نگه داشته شد (تغییر زیاد قیمت؛ تأیید لازم است)",
    "failed": "خوانده نشد (قالب ناشناخته)", "duplicate": "همان لیست قبلی بود",
    "older": "قدیمی‌تر از لیست فعال بود", "too_large": "فایل بیش از حد بزرگ بود",
    "not_pdf": "فایل PDF نبود", "download_failed": "دریافت نشد",
}


def proxy_source_fa(source) -> str:
    text = str(source or "")
    if text == "manual":
        return "دستی"
    if text.startswith("channel:"):
        return "کانال @" + text.split(":", 1)[1]
    return text or "—"


def telegram_details(worker: dict | None, pool: dict | None) -> dict[str, tuple[str, str | None]]:
    """v2.9.0: the rows of «خوانندهٔ تلگرام و استخر پراکسی» (no secrets in there)."""
    worker = worker or {}
    out: dict[str, tuple[str, str | None]] = {}
    _, text, color = telegram_text(worker or None)
    preset = worker.get("api_preset")
    if preset:
        text += "\nکلید: " + ("عمومی Telegram Desktop (موقت)" if preset == "tdesktop"
                              else "کلید خودِ فروشگاه")
    out["reader"] = (text, color)
    price = worker.get("price") or {}
    channel = worker.get("price_channel")
    if price.get("checked_at") or price.get("at"):
        parts = []
        if channel:
            parts.append(f"@{channel}")
        if price.get("checked_at"):
            parts.append(f"آخرین بررسی: {format_shamsi(price['checked_at'])}")
        if price.get("at"):
            outcome = PRICE_OUTCOME_FA.get(price.get("outcome") or "", price.get("outcome") or "")
            parts.append(f"آخرین فایل: {format_shamsi(price['at'])} — {outcome}")
        bad = price.get("outcome") in ("failed", "too_large", "not_pdf", "download_failed")
        out["price"] = ("\n".join(parts), theme.DANGER if bad else None)
    else:
        out["price"] = (f"@{channel} — هنوز بررسی نشده" if channel else "هنوز بررسی نشده", None)
    pool = pool or {}
    if pool:
        target = int(pool.get("target") or 5)
        working = int(pool.get("working") or 0)
        text = (f"{to_persian_digits(working)} پراکسی سالم از {to_persian_digits(target)} "
                f"(در استخر: {to_persian_digits(pool.get('active') or 0)}، "
                f"دستی: {to_persian_digits(pool.get('manual') or 0)}، "
                f"کنار گذاشته: {to_persian_digits(pool.get('retired') or 0)})")
        if pool.get("all_failing"):
            text += "\nهیچ پراکسی‌ای کار نمی‌کند؛ یک پراکسی دستی اضافه کنید."
        color = theme.DANGER if not working else (theme.WARNING_TEXT if working < target
                                                  else theme.SUCCESS_DARK)
        out["pool"] = (text, color)
    else:
        out["pool"] = ("—", None)
    collect = worker.get("collect") or {}
    if collect.get("at"):
        via = {"account": "با حساب تلگرام", "web": "از صفحهٔ عمومی کانال"}
        ways = "، ".join(via.get(w, w) for w in str(collect.get("via") or "").split(",") if w)
        out["collect"] = (
            f"{format_shamsi(collect['at'])} — {to_persian_digits(collect.get('found') or 0)} پیوند، "
            f"{to_persian_digits(collect.get('tested') or 0)} آزموده، "
            f"{to_persian_digits(collect.get('added') or 0)} سالم اضافه شد"
            + (f" ({ways})" if ways else "")
            # v2.9.1: why nothing was found (channel unreadable, filtered page, …)
            + ("\nدلیل: " + str(collect["error"]) if collect.get("error") else ""),
            theme.WARNING_TEXT if collect.get("error") else None)
    else:
        out["collect"] = ("هنوز انجام نشده (روزی یک بار؛ وقتی استخر کم باشد هر ساعت)", None)
    return out


def telegram_text(worker: dict | None) -> tuple[str, str, str | None]:
    """Status-row text for the Telegram reader (price lists + proxy pool)."""
    if not worker:
        return "telegram", "روشن نشده یا هنوز گزارشی نداده است («تنظیمات سرور» › تلگرام)", None
    when = format_shamsi(worker["at"]) if worker.get("at") else "—"
    if worker.get("login_required"):
        return ("telegram", "نیاز به ورود به حساب تلگرام («تنظیمات سرور» روی خود سرور › "
                f"تلگرام › ورود به حساب تلگرام) — {when}", theme.DANGER)
    if worker.get("connected"):
        via = worker.get("proxy") or "اتصال مستقیم"
        return "telegram", f"متصل از طریق {via} — آخرین گزارش: {when}", theme.SUCCESS_DARK
    error = worker.get("error") or "قطع"
    return "telegram", f"قطع ({error}) — آخرین گزارش: {when}", theme.DANGER


def health_text(health: dict | None) -> tuple[str, str, str | None]:
    """Status-row text for the server's health monitor."""
    if not health or not health.get("checks"):
        return "health", "هنوز بررسی نشده (هر یک دقیقه یک‌بار)", None
    parts, bad = [], False
    for key, name in HEALTH_NAMES.items():
        check = health["checks"].get(key) or {}
        if check.get("ok") is None and not check.get("down"):
            continue
        if check.get("down"):
            parts.append(f"{name}: از کار افتاده")
            bad = True
        elif check.get("ok"):
            parts.append(f"{name}: سالم")
        else:
            parts.append(f"{name}: خطا ({to_persian_digits(check.get('fails', 0))} بار)")
    text = "، ".join(parts) or "—"
    if health.get("checked_at"):
        text += f"\nآخرین بررسی: {format_shamsi(health['checked_at'])}"
    return "health", text, theme.DANGER if bad else theme.SUCCESS_DARK
