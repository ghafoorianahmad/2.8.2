"""صفحهٔ «بایگانی» (نسخهٔ ۲٫۸٫۰، فقط‌خواندنی).

هر پنج‌شنبه ساعت ۲۳:۳۰ سفارش‌ها و درخواست‌های تمام‌شده (ارسال‌شده، لغو، رد،
منقضی) به اینجا می‌آیند. کاربر فروش فقط کارهای خودش را در سال مالی جاری (پایگاه
دادهٔ فعلی) می‌بیند؛ مدیر همه‌چیز را از همهٔ سال‌ها، با جستجو. هیچ‌چیز پاک یا
ویرایش نمی‌شود؛ تغییر سفارش تمام‌شده فقط در «سازه حساب» انجام می‌شود.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QWidget

from ...permissions import ARCHIVE_MANUAL
from ...persian import format_money, format_shamsi, to_persian_digits
from ...statuses import order_status_fa
from .. import widgets
from ..base_page import BasePage
from .item_requests import KIND_FA, OUTCOME_FA, ItemRequestDialog, product_text
from .orders import OrderDetailDialog, customer_label, owner_label, tracking_fa

ORDER_HEADERS = ("شماره سفارش", "مشتری", "مبلغ کل", "وضعیت", "پیگیری", "مسئول", "سال مالی",
                 "تاریخ ثبت")
REQUEST_HEADERS = ("شماره", "نوع", "مشتری", "نتیجه", "مسئول", "سال مالی", "کالا")


class ArchivePage(BasePage):
    title = "بایگانی"
    subtitle = "سفارش‌ها و درخواست‌های تمام‌شده (فقط دیدن)"
    help_text = ("کارهای تمام‌شده هر پنج‌شنبه شب خودکار به اینجا می‌آیند و می‌شود زودتر هم از "
                 "«سفارش‌ها» فرستاد. چیزی پاک یا ویرایش نمی‌شود؛ تغییر سفارش تمام‌شده فقط در «سازه "
                 "حساب» ممکن است.")

    def build_body(self) -> None:
        principal = self.context.principal
        self.is_manager = principal is not None and principal.is_manager
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
        self._tab = "orders"
        self._tab_buttons = {}
        for key, text in (("orders", "سفارش‌ها"), ("requests", "درخواست‌ها")):
            button = widgets.button(text, variant="ghost",
                                    on_click=lambda k=key: self.set_tab(k))
            button.setObjectName("Tab")
            button.setCheckable(True)
            button.setChecked(key == self._tab)
            self._tab_buttons[key] = button
            bar.addWidget(button)
        self.search = widgets.SearchBox("شماره، نام مشتری یا کالا")
        self.search.returnPressed.connect(self.load)
        bar.addWidget(self.search)
        self.db_input = QLineEdit()
        self.db_input.setPlaceholderText("سال مالی (نام پایگاه داده؛ خالی = همه)")
        self.db_input.setMinimumWidth(240)
        self.db_input.returnPressed.connect(self.load)
        self.db_input.setVisible(self.is_manager)
        bar.addWidget(self.db_input)
        bar.addWidget(widgets.button("جستجو", icon_name="search", on_click=self.load))
        self.body.addWidget(bar_holder)
        if not self.is_manager:
            self.body.addWidget(widgets.label(
                "فقط کارهای خودتان در سال مالی جاری نمایش داده می‌شود.", name="Muted"))

        panel = widgets.Panel()
        self.orders_table = widgets.DataTable(ORDER_HEADERS, selectable_rows=True,
                                              key="archive_orders_v280", keep_columns=(7,))
        self.orders_table.set_empty_state("سفارشی در بایگانی نیست", "", "archive")
        self.orders_table.row_activated.connect(self._open_order)
        self.requests_table = widgets.DataTable(REQUEST_HEADERS, selectable_rows=True,
                                                key="archive_requests_v280")
        self.requests_table.set_empty_state("درخواستی در بایگانی نیست", "", "archive")
        self.requests_table.row_activated.connect(self._open_request)
        self.requests_table.setVisible(False)
        self.open_order_button = widgets.open_button(self.orders_table)
        self.open_request_button = widgets.open_button(self.requests_table)
        self.open_request_button.setVisible(False)
        bar.addWidget(self.open_order_button)
        bar.addWidget(self.open_request_button)
        # v2.18.0: back out of the archive, one or many
        self.can_restore = self.context.can(ARCHIVE_MANUAL)
        self.restore_button = widgets.button("برگرداندن تیک‌خورده‌ها", icon_name="refresh",
                                             on_click=self._restore_checked)
        self.restore_button.setVisible(self.can_restore)
        bar.addWidget(self.restore_button)
        if self.can_restore:
            self.orders_table.enable_checks(keep_text=True)
        for table in (self.orders_table, self.requests_table):
            table.setMinimumHeight(360)
            panel.body.addWidget(table, 1)
        self.table = self.orders_table
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)
        self.orders: list[dict] = []
        self.requests: list[dict] = []

    def set_tab(self, key: str) -> None:
        self._tab = key if key in self._tab_buttons else "orders"
        for tab_key, button in self._tab_buttons.items():
            button.setChecked(tab_key == self._tab)
        self.orders_table.setVisible(self._tab == "orders")
        self.requests_table.setVisible(self._tab == "requests")
        self.open_order_button.setVisible(self._tab == "orders")
        self.open_request_button.setVisible(self._tab == "requests")
        self.restore_button.setVisible(self.can_restore and self._tab == "orders")
        self.table = self.orders_table if self._tab == "orders" else self.requests_table
        self.load()

    def load(self) -> None:
        q = self.search.text().strip()
        db = self.db_input.text().strip() if self.is_manager else ""
        api = self.context.api
        if self._tab == "orders":
            self.run(lambda: api.archived_orders(q, db), on_success=self._orders_loaded,
                     on_error=lambda m, _k: self.show_table_error(m))
        else:
            self.run(lambda: api.archived_item_requests(q, db), on_success=self._requests_loaded,
                     on_error=lambda m, _k: self.show_table_error(m))

    def _orders_loaded(self, rows) -> None:
        self.orders = [r for r in (rows or []) if isinstance(r, dict)]
        table = self.orders_table
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(0)
            for order in self.orders:
                row = table.rowCount()
                table.insertRow(row)
                table.set_cell(row, 0, to_persian_digits(order.get("id", "")), bold=True)
                if self.can_restore:
                    table.set_check(row, False, keep_text=True)
                table.set_row_key(row, order.get("id"))
                table.set_cell(row, 1, customer_label(order))
                table.set_cell(row, 2, format_money(order.get("total", 0)))
                table.set_cell(row, 3, order_status_fa(order.get("status")))
                table.set_cell(row, 4, tracking_fa(order))
                table.set_cell(row, 5, owner_label(order))
                table.set_cell(row, 6, str(order.get("accounting_db") or "—"))
                table.set_cell(row, 7, format_shamsi(order.get("created_at")))
        finally:
            table.setUpdatesEnabled(True)
        table._refresh_states()
        self.summary.setText(f"{to_persian_digits(len(self.orders))} سفارش در بایگانی")

    def _restore_checked(self) -> None:
        ids = [int(key) for key in self.orders_table.checked_keys()]
        if not ids:
            self.notify_warning("سفارش‌ها را تیک بزنید.")
            return
        self.run(lambda: self.context.api.restore_orders(ids), on_success=self._restored)

    def _restored(self, result: object) -> None:
        done = (result if isinstance(result, dict) else {}).get("restored") or []
        self.notify_success(f"{to_persian_digits(len(done))} سفارش از بایگانی برگشت.")
        self.context.data_changed.emit()
        self.load()

    def _requests_loaded(self, rows) -> None:
        self.requests = [r for r in (rows or []) if isinstance(r, dict)]
        table = self.requests_table
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(0)
            for item in self.requests:
                row = table.rowCount()
                table.insertRow(row)
                kind = str(item.get("kind") or "unavailable")
                table.set_cell(row, 0, to_persian_digits(item.get("id", "")), bold=True)
                table.set_cell(row, 1, KIND_FA.get(kind, kind))
                table.set_cell(row, 2, str(item.get("customer_name") or "—"))
                table.set_cell(row, 3, OUTCOME_FA.get(str(item.get("outcome") or ""),
                                                      "رسیدگی شد"))
                table.set_cell(row, 4, owner_label(item))
                table.set_cell(row, 5, str(item.get("accounting_db") or "—"))
                table.set_cell(row, 6, product_text(item))
        finally:
            table.setUpdatesEnabled(True)
        table._refresh_states()
        self.summary.setText(f"{to_persian_digits(len(self.requests))} درخواست در بایگانی")

    def _open_order(self, row: int) -> None:
        if 0 <= row < len(self.orders):
            OrderDetailDialog(self.context, {**self.orders[row], "finished": True}, self).exec()

    def _open_request(self, row: int) -> None:
        if 0 <= row < len(self.requests):
            ItemRequestDialog(self.context, {**self.requests[row], "archived": True}, self).exec()
