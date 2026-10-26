"""v2.9.4 «پاک‌سازی داده‌های آزمایشی» (server settings, on the server, owner only).

1. what would be removed (counts) and what always stays;
2. «گرفتن پشتیبان» — a verified backup of the server's data folder, required;
3. the owner types «پاک‌سازی» and confirms;
4. the summary of what was removed.

Only the shop's own data (SQLite in the server's data folder) is cleared; the
accounting database is never opened by this tool.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from .. import server_setup as setup
from ..persian import to_persian_digits
from . import theme, widgets
from .async_utils import run_async

KEPT_TEXT = ("می‌مانند: «مدیر کل»، همهٔ تنظیمات سرور، گروه‌های کالا، لیست‌های قیمت و نگاشت "
             "ردیف‌ها، مدل‌های سایت، پراکسی‌ها، نشست تلگرام و گزارش امنیتی. پایگاه‌دادهٔ حسابداری "
             "(«سازه حساب») هرگز دست نمی‌خورد.")
#: the order the counts are listed in
ORDER = ("orders", "order_items", "payments", "receipts", "receipt_files", "item_requests",
         "item_request_messages", "inquiries", "users", "conversations", "carts", "events",
         "admin_notices", "sales_watch", "activity_log", "idempotency_keys", "staff",
         "password_requests")


def counts_text(payload: dict, *, done: bool = False) -> str:
    counts = payload.get("counts") or {}
    labels = payload.get("labels") or {}
    lines = [f"• {labels.get(key, key)}: {to_persian_digits(counts.get(key, 0))}"
             for key in ORDER if key in counts and (counts.get(key) or not done)]
    staff = payload.get("staff_removed") or []
    if staff:
        lines.append("• کاربران کارمند: " + "، ".join(staff))
    owners = payload.get("owners") or []
    if owners:
        lines.append("• «مدیر کل» (می‌ماند): " + "، ".join(owners))
    return "\n".join(lines) if lines else "چیزی برای پاک کردن نیست."


class CleanupDialog(widgets.ResponsiveDialog):
    def __init__(self, parent: QWidget | None, *, port: int) -> None:
        super().__init__(parent)
        self.port = port
        self.confirm_text = "پاک‌سازی"
        self.backed_up = False
        self.setWindowTitle("پاک‌سازی داده‌های آزمایشی")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        root.addWidget(widgets.label("پاک‌سازی داده‌های آزمایشی", size=14, bold=True))
        root.addWidget(widgets.label(
            "پیش از شروع کار واقعی، سفارش‌ها و دیگر داده‌های آزمایشی خود فروشگاه پاک می‌شوند. این "
            "کار برگشت ندارد (جز با بازگرداندن همان پشتیبانی که اول گرفته می‌شود).",
            name="Muted", wrap=True))
        root.addWidget(widgets.label("پاک می‌شوند:", bold=True))
        self.counts_label = widgets.label("در حال خواندن…", wrap=True)
        root.addWidget(self.counts_label)
        root.addWidget(widgets.label(KEPT_TEXT, name="Muted", wrap=True))

        self.backup_button = widgets.button("۱. گرفتن پشتیبان", icon_name="check",
                                            variant="primary", on_click=self._backup)
        self.backup_label = widgets.label("", wrap=True)
        root.addWidget(self.backup_label)
        root.addWidget(widgets.label("۲. برای تأیید، این کلمه را بنویسید: «پاک‌سازی»", bold=True))
        self.confirm_input = QLineEdit()
        self.confirm_input.setMinimumHeight(38)
        self.confirm_input.setPlaceholderText("پاک‌سازی")
        self.confirm_input.setEnabled(False)
        self.confirm_input.textChanged.connect(self._update)
        root.addWidget(self.confirm_input)
        self.result_label = widgets.label("", wrap=True)
        self.result_label.setVisible(False)
        root.addWidget(self.result_label)
        self.run_button = widgets.button("پاک‌سازی", icon_name="trash", variant="danger",
                                         on_click=self._run)
        self.run_button.setEnabled(False)
        self.close_button = widgets.button("بستن", on_click=self.reject)
        root.addLayout(widgets.footer(self.run_button, self.backup_button,
                                      close=self.close_button))
        self._load()

    # ---- steps ------------------------------------------------------------
    def _load(self) -> None:
        def ok(payload: dict) -> None:
            self.confirm_text = str(payload.get("confirm_text") or self.confirm_text)
            self.counts_label.setText(counts_text(payload))

        run_async(setup.cleanup_preview, self.port, on_success=ok,
                  on_error=lambda message, _k: self.counts_label.setText(
                      "خوانده نشد (سرور روشن است؟): " + message))

    def _backup(self) -> None:
        self.backup_button.setEnabled(False)
        self.backup_label.setText("در حال گرفتن و آزمودن پشتیبان… (ممکن است چند دقیقه طول بکشد)")
        self.backup_label.setStyleSheet("")

        def ok(status: dict) -> None:
            self.backed_up = True
            note = ""
            offsite = status.get("offsite") or {}
            if offsite.get("configured") and offsite.get("ok") is False:
                note = " (نسخهٔ بیرون از سرور نوشته نشد؛ پشتیبان روی خود سرور کامل است)"
            self.backup_label.setText(f"✔ پشتیبان گرفته و آزموده شد: {status.get('file')}{note}")
            self.backup_label.setStyleSheet(f"color: {theme.SUCCESS_DARK};")
            self.confirm_input.setEnabled(True)
            self.confirm_input.setFocus()
            self._update()

        def fail(message: str, _kind: str) -> None:
            self.backup_button.setEnabled(True)
            self.backup_label.setText("✖ " + message)
            self.backup_label.setStyleSheet(f"color: {theme.DANGER};")

        run_async(setup.backup_now, on_success=ok, on_error=fail)

    def _update(self, *_args) -> None:
        self.run_button.setEnabled(self.backed_up and
                                   self.confirm_input.text().strip() == self.confirm_text)

    def _run(self) -> None:
        if not widgets.confirm(self, "پاک‌سازی داده‌های آزمایشی",
                               "داده‌های آزمایشی فروشگاه همین حالا پاک می‌شوند. مطمئنید؟",
                               confirm_text="بله، پاک شود", cancel_text="انصراف", kind="danger"):
            return
        self.run_button.setEnabled(False)
        self.confirm_input.setEnabled(False)

        def ok(payload: dict) -> None:
            self.result_label.setText("✔ پاک شد:\n" + counts_text(payload, done=True))
            self.result_label.setStyleSheet(f"color: {theme.SUCCESS_DARK};")
            self.result_label.setVisible(True)
            self.counts_label.setText("پاک‌سازی انجام شد.")

        def fail(message: str, _kind: str) -> None:
            self.result_label.setText("✖ پاک‌سازی انجام نشد: " + message)
            self.result_label.setStyleSheet(f"color: {theme.DANGER};")
            self.result_label.setVisible(True)
            self.confirm_input.setEnabled(True)
            self._update()

        run_async(setup.cleanup_run, self.port, self.confirm_input.text().strip(),
                  on_success=ok, on_error=fail)
