"""صفحهٔ «درخواست‌های گذرواژه» — تأیید یا رد درخواست فراموشی گذرواژهٔ کارکنان.

کارمندی که گذرواژه‌اش را فراموش کرده در پنجرهٔ ورود درخواست می‌دهد. مدیر اینجا آن را
تأیید یا رد می‌کند؛ پس از تأیید خود کارمند گذرواژهٔ جدید دلخواهش را انتخاب می‌کند
(مدیر هیچ گذرواژه‌ای نمی‌بیند). گذرواژهٔ قبلی همان لحظه بی‌اعتبار می‌شود.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget

from ...permissions import PASSWORDS_DECIDE
from ...persian import format_shamsi, to_persian_digits
from ...statuses import role_fa
from .. import widgets
from ..base_page import BasePage

HEADERS = ("نام کاربری", "نام و نام خانوادگی", "نقش", "زمان درخواست", "عملیات")


class PasswordRequestsPage(BasePage):
    title = "درخواست‌های گذرواژه"
    subtitle = "کارکنانی که گذرواژهٔ خود را فراموش کرده‌اند"
    help_text = "کاربرانی که گذرواژه‌شان را فراموش کرده‌اند منتظر تأیید شما هستند."
    auto_refreshable = True

    def build_body(self) -> None:
        panel = widgets.Panel("درخواست‌های در انتظار")
        panel.body.addWidget(widgets.label(
            "با تأیید، همان کارمند در پنجرهٔ ورود گذرواژهٔ جدید دلخواهش را تعیین می‌کند "
            "(تا ۳۰ دقیقه فرصت دارد). فقط وقتی تأیید کنید که مطمئنید درخواست از خود اوست.",
            name="Muted", wrap=True))
        self.table = widgets.DataTable(HEADERS, key="password_requests")
        self.table.set_empty_state("درخواستی نیست", "", "users")
        self.table.setMinimumHeight(260)
        panel.body.addWidget(self.table, 1)
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)

    def load(self) -> None:
        if not self.context.can(PASSWORDS_DECIDE):
            return
        self.run(self.context.auth.list_password_requests, on_success=self._loaded,
                 on_error=lambda m, _k: self.show_table_error(m))

    def _loaded(self, items: list) -> None:
        items = list(items or [])
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for item in items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, str(item.get("username") or "—"), bold=True)
                self.table.set_cell(row, 1, str(item.get("full_name") or "—"))
                self.table.set_cell(row, 2, role_fa(str(item.get("role") or "")))
                self.table.set_cell(row, 3, format_shamsi(item.get("created_at")))
                self.table.set_widget(row, 4, self._actions(item))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        self.summary.setText(f"{to_persian_digits(len(items))} درخواست در انتظار تصمیم")

    def _actions(self, item: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(widgets.button(
            "تأیید", variant="primary", on_click=lambda i=item: self._decide(i, True)))
        layout.addWidget(widgets.button(
            "رد", variant="danger", on_click=lambda i=item: self._decide(i, False)))
        layout.addStretch(1)
        return holder

    def _decide(self, item: dict, approve: bool) -> None:
        name = str(item.get("username") or "")
        if approve and not widgets.confirm(
            self, "تأیید درخواست گذرواژه",
            f"به «{name}» اجازه داده شود گذرواژهٔ جدید تعیین کند؟",
            confirm_text="تأیید", kind="question",
        ):
            return
        request_id = int(item["id"])
        self.run(
            lambda: self.context.auth.decide_password_request(request_id, approve),
            on_success=lambda _r: (self.notify_success(
                "درخواست تأیید شد؛ کارمند می‌تواند گذرواژهٔ جدید بگذارد" if approve
                else "درخواست رد شد"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "انجام نشد", m),
        )
