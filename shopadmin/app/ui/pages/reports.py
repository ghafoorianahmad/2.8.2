"""صفحهٔ گزارش‌ها — فیلتر بازهٔ شمسی و وضعیت، جمع‌بندی و خروجی اکسل/سی‌اس‌وی."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from ...permissions import REPORTS_EXPORT
from ...persian import (
    coerce_datetime,
    format_int,
    format_money,
    format_shamsi,
    format_shamsi_long,
    to_persian_digits,
)
from ...reporting import (
    DEFAULT_ORDER_STATUSES,
    build_customer_rows,
    build_order_rows,
    filter_by_range,
    summarize,
    write_csv,
    write_xlsx,
)
from ...statuses import ORDER_STATUS_FA, order_status_fa
from .. import theme, widgets
from ..base_page import BasePage
from ..widgets_shamsi import ShamsiRangePicker

HEADERS = ("شماره سفارش", "مشتری", "تعداد اقلام", "مبلغ کل", "وضعیت", "تاریخ ثبت")


class ReportsPage(BasePage):
    title = "گزارش‌ها"
    subtitle = "جمع‌بندی سفارش‌ها و مشتریان در یک بازهٔ زمانی دلخواه"

    def build_body(self) -> None:
        filters = widgets.Panel("صافی‌های گزارش")
        row = QHBoxLayout()
        row.setSpacing(12)

        self.range_picker = ShamsiRangePicker()
        self.range_picker.changed.connect(self._on_filters_changed)
        row.addWidget(self.range_picker, 1)

        row.addWidget(widgets.label("وضعیت سفارش:"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for status in DEFAULT_ORDER_STATUSES:
            self.status_combo.addItem(ORDER_STATUS_FA[status], status)
        self.status_combo.setMinimumWidth(170)
        self.status_combo.currentIndexChanged.connect(lambda _i: self.load())
        row.addWidget(self.status_combo)

        filters.body.addLayout(row)
        self.body.addWidget(filters)

        # ---- summary cards ----------------------------------------------
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.card_orders = widgets.StatCard(
            "تعداد سفارش", icon_name="orders", accent=theme.PRIMARY, tint=theme.PRIMARY_LIGHT
        )
        self.card_amount = widgets.StatCard(
            "مبلغ کل", icon_name="chart", accent=theme.SUCCESS, tint=theme.SUCCESS_LIGHT
        )
        self.card_customers = widgets.StatCard(
            "مشتریان جدید", icon_name="customers", accent=theme.INFO, tint=theme.INFO_LIGHT
        )
        for card in (self.card_orders, self.card_amount, self.card_customers):
            cards.addWidget(card, 1)
        self.body.addLayout(cards)

        # ---- table + export ---------------------------------------------
        panel = widgets.Panel("سفارش‌های بازهٔ انتخابی")
        export_row = QHBoxLayout()
        export_row.addWidget(widgets.label(
            f"بازهٔ گزارش: {format_shamsi_long(self.range_picker.from_date())} تا "
            f"{format_shamsi_long(self.range_picker.to_date())}", name="Muted"
        ), 1)

        self.export_excel_button = widgets.button(
            "خروجی اکسل", icon_name="download", variant="primary", on_click=self._export_excel
        )
        self.export_csv_button = widgets.button(
            "خروجی CSV", icon_name="download", on_click=self._export_csv
        )
        self.export_excel_button.setEnabled(self.context.can(REPORTS_EXPORT))
        self.export_csv_button.setEnabled(self.context.can(REPORTS_EXPORT))
        if not self.context.can(REPORTS_EXPORT):
            tooltip = "نقش شما اجازهٔ گرفتن خروجی ندارد"
            self.export_excel_button.setToolTip(tooltip)
            self.export_csv_button.setToolTip(tooltip)
        export_row.addWidget(self.export_excel_button)
        export_row.addWidget(self.export_csv_button)
        panel.body.addLayout(export_row)

        self.table = widgets.DataTable(HEADERS)
        self.table.set_empty_state(
            "در این بازه سفارشی وجود ندارد",
            "بازهٔ تاریخ را بزرگ‌تر کنید یا وضعیت را روی «همهٔ وضعیت‌ها» بگذارید.",
            "reports",
        )
        self.table.setMinimumHeight(320)
        panel.body.addWidget(self.table, 1)
        self.body.addWidget(panel, 1)

        self._orders: list[dict] = []
        self._customers: list[dict] = []
        self._filtered: list[dict] = []
        self._summary: dict = {}

    # ------------------------------------------------------------------ state
    def _on_filters_changed(self) -> None:
        self.load()

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        for card in (self.card_orders, self.card_amount, self.card_customers):
            card.set_loading()
        self.table.set_busy(True)

        status = self.status_combo.currentData()
        start, end = self.range_picker.range()

        def work() -> dict:
            api = self.context.api
            orders = api.list_orders(status) if status else _all_orders(api)
            customers = api.list_customers()
            return {"orders": orders, "customers": customers}

        self.run(work, on_success=lambda data: self._render(data, start, end),
                 on_error=self._on_error)

    def _on_error(self, message: str, kind: str) -> None:
        for card in (self.card_orders, self.card_amount, self.card_customers):
            card.set_error()
        self.show_table_error(message)
        self.default_error(message, kind)

    def _render(self, data: dict, start: date, end: date) -> None:
        self._orders = list(data.get("orders") or [])
        self._customers = list(data.get("customers") or [])
        self._filtered = filter_by_range(self._orders, start, end, field="created_at")
        self._summary = summarize(self._filtered, self._customers, start, end)

        self.card_orders.set_value(format_int(self._summary["order_count"]))
        self.card_amount.set_value(format_money(self._summary["total_amount"], with_unit=False),
                                   hint="تومان")
        self.card_customers.set_value(
            format_int(self._summary["new_customers"]),
            hint=f"از {format_int(self._summary['customer_count'])} مشتری",
        )

        rows = build_order_rows(self._filtered)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for row_data in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, to_persian_digits(row_data["id"]), bold=True)
                self.table.set_cell(row, 1, str(row_data["customer"]))
                self.table.set_cell(row, 2, to_persian_digits(row_data["items_count"]))
                self.table.set_cell(row, 3, format_money(row_data["total"]))
                status = next(
                    (o.get("status") for o in self._filtered
                     if str(o.get("id")) == str(row_data["id"])), ""
                )
                self.table.set_widget(row, 4, widgets.pill_cell(
                    widgets.StatusPill(order_status_fa(status), status)
                ))
                self.table.set_cell(row, 5, format_shamsi(row_data["created_at"]))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        self.table.set_busy(False)

    # ------------------------------------------------------------------ export
    def _default_filename(self, extension: str) -> str:
        start, end = self.range_picker.range()
        return (
            f"گزارش-سفارش‌ها-{format_shamsi(start).replace('/', '-')}"
            f"-تا-{format_shamsi(end).replace('/', '-')}.{extension}"
        )

    def _export_excel(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ خروجی اکسل", self._default_filename("xlsx"),
            "فایل اکسل (*.xlsx)",
        )
        if not path:
            return
        try:
            written = write_xlsx(
                Path(path), self._filtered, self._customers,
                self.range_picker.range(), self._summary,
            )
        except Exception as exc:  # noqa: BLE001 - report any failure in Persian
            _log_export_failure("xlsx", exc)
            widgets.error(self, "خروجی اکسل گرفته نشد",
                          "ذخیرهٔ فایل ممکن نشد. مسیر و دسترسی پوشه را بررسی کنید.")
            return
        self.notify_success(f"خروجی اکسل با موفقیت ذخیره شد ({to_persian_digits(written)} سفارش)")
        self.context.audit("report_export", "excel")

    def _export_csv(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ خروجی CSV", self._default_filename("csv"),
            "فایل CSV (*.csv)",
        )
        if not path:
            return
        try:
            written = write_csv(Path(path), self._filtered, self._customers,
                                self.range_picker.range(), self._summary)
        except Exception as exc:  # noqa: BLE001
            _log_export_failure("csv", exc)
            widgets.error(self, "خروجی CSV گرفته نشد",
                          "ذخیرهٔ فایل ممکن نشد. مسیر و دسترسی پوشه را بررسی کنید.")
            return
        self.notify_success(f"خروجی CSV با موفقیت ذخیره شد ({to_persian_digits(written)} سفارش)")
        self.context.audit("report_export", "csv")


def _all_orders(api) -> list[dict]:
    """Fetch every order status the app can display, without duplicates."""
    collected: dict[object, dict] = {}
    for status in DEFAULT_ORDER_STATUSES:
        for order in api.list_orders(status) or []:
            collected[order.get("id")] = order
    return list(collected.values())


def _log_export_failure(kind: str, exc: Exception) -> None:
    from ...logging_setup import get_logger

    get_logger("reports").warning("export %s failed: %s", kind, type(exc).__name__)
