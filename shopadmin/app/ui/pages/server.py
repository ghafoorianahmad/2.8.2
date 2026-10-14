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
from ...permissions import SERVER_MANAGE
from ...persian import format_shamsi, to_persian_digits
from ...server_settings import SETTINGS_FA, local_problem, translate_field_errors
from .. import theme, widgets
from ..base_page import BasePage

PLATFORM_FA = {"bale": "بله", "telegram": "تلگرام"}


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
    title = "سرور فروشگاه"
    subtitle = "وضعیت سرور و ربات‌ها، تنظیمات، گزارش و راه‌اندازی دوباره"
    reload_on_data_change = False

    def build_body(self) -> None:
        if not self.context.can(SERVER_MANAGE):
            panel = widgets.Panel()
            panel.body.addWidget(widgets.label("دسترسی غیرمجاز", size=14, bold=True))
            panel.body.addWidget(widgets.label(
                "مدیریت سرور فقط برای نقش «مدیر کل» در دسترس است.", name="Muted", wrap=True))
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
            ("telegram", "کارگر تلگرام"),
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
        self.restart_button = widgets.button(
            "راه‌اندازی دوبارهٔ سرور", icon_name="refresh", variant="danger",
            on_click=self._restart)
        buttons.addWidget(self.restart_button)
        panel.body.addLayout(buttons)
        return panel

    def load(self) -> None:
        if not self.context.can(SERVER_MANAGE):
            return
        self.run(self.context.api.server_status, on_success=self._show_status)
        self.run(self.context.api.server_settings, on_success=self._show_settings,
                 on_error=self._settings_unavailable)

    def _show_status(self, status: dict) -> None:
        acc = status.get("accounting") or {}
        if acc.get("ok"):
            self._set("accounting", f"متصل ({to_persian_digits(acc.get('latency_ms', 0))} میلی‌ثانیه)",
                      theme.SUCCESS_DARK)
        else:
            self._set("accounting", "قطع — سرور به پایگاه‌دادهٔ حسابداری دسترسی ندارد", theme.DANGER)
        if status.get("test_mode"):
            self._set("write", "فعال کامل — پایگاه آزمایشی (خواندن و نوشتن آزاد)",
                      theme.SUCCESS_DARK)
        elif status.get("accounting_write_enabled"):
            self._set("write", "فعال (ثبت واقعی)", theme.SUCCESS_DARK)
        else:
            self._set("write", "آزمایشی — بدون ثبت واقعی (فقط روی خود سرور قابل تغییر)",
                      theme.WARNING_TEXT)
        self._set("uptime", _uptime_fa(status.get("uptime_seconds", 0)))
        self._set("version", to_persian_digits(status.get("version", "—")))

        bots = (status.get("components") or {}).get("bots") or {}
        configured = bots.get("configured") or []
        platforms = bots.get("platforms") or {}
        if not configured:
            self._set("bots", "هیچ رباتی تنظیم نشده است (توکن بله/تلگرام را در تنظیمات پایین وارد کنید)",
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
        self.restart_button.setEnabled(bool(status.get("restart_available")))
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
        self.settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
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
            self.settings_form.addRow(widgets.label(caption + ":"), field)
        self.save_settings_button.setEnabled(True)

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
                if field.text().strip():
                    changes[key] = field.text().strip()
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


def telegram_text(worker: dict | None) -> tuple[str, str, str | None]:
    """Status-row text for the Telegram price/proxy worker (shoptg)."""
    if not worker:
        return "telegram", "نصب نشده یا هنوز گزارشی نداده است", None
    when = format_shamsi(worker["at"]) if worker.get("at") else "—"
    if worker.get("login_required"):
        return "telegram", f"نیاز به ورود دوباره به تلگرام (login.ps1 روی سرور) — {when}", theme.DANGER
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
