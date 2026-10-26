"""v2.9.4 «راهنمای کد وضعیت سفارش» — read only, before real writing is switched on.

Shows every ``Status`` value of the accounting order table (``KalaOrder``) with
its count, split into orders made by «سازه حساب» itself and internet orders, and
the latest orders «سازه حساب» made itself. The owner opens those orders in «سازه
حساب» to see which status name each number is, and types the right number into
«کد وضعیت سفارش». Nothing is written anywhere (the server only SELECTs).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..persian import format_money, to_persian_digits
from . import theme, widgets
from .async_utils import run_async

STATUS_HEADERS = ("کد وضعیت", "ساخت «سازه حساب»", "اینترنتی", "آخرین سفارش", "آخرین تاریخ")
LATEST_HEADERS = ("شمارهٔ سفارش", "تاریخ", "کد وضعیت", "کد کاربر", "تعداد قلم", "مبلغ")


def status_rows(payload: dict) -> list[tuple]:
    """One row per Status: (status, sazeh count, internet count, last order, last date)."""
    merged: dict = {}
    for row in payload.get("statuses") or []:
        key = row.get("status")
        entry = merged.setdefault(key, {"sazeh": 0, "internet": 0, "last": None, "date": ""})
        entry["internet" if row.get("internet") else "sazeh"] += int(row.get("count") or 0)
        last = row.get("last_order")
        if last is not None and (entry["last"] is None or last > entry["last"]):
            entry["last"] = last
        entry["date"] = max(entry["date"], str(row.get("last_date") or ""))
    ordered = sorted(merged.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    return [("خالی (NULL)" if status is None else to_persian_digits(status),
             to_persian_digits(e["sazeh"]), to_persian_digits(e["internet"]),
             "—" if e["last"] is None else to_persian_digits(e["last"]),
             to_persian_digits(e["date"]) or "—") for status, e in ordered]


def latest_rows(payload: dict) -> list[tuple]:
    out = []
    for row in payload.get("latest_sazeh") or []:
        status = row.get("status")
        out.append((to_persian_digits(row.get("order") or "—"),
                    to_persian_digits(row.get("date") or "—"),
                    "خالی (NULL)" if status is None else to_persian_digits(status),
                    "—" if row.get("user_code") is None else to_persian_digits(row["user_code"]),
                    to_persian_digits(row.get("items") or 0),
                    format_money(row.get("total") or 0)))
    return out


class StatusCodesDialog(widgets.ResponsiveDialog):
    """``loader()`` returns the server's answer (``/admin/server/order-status-codes``)."""

    def __init__(self, parent: QWidget | None, loader: Callable[[], dict]) -> None:
        super().__init__(parent)
        self.loader = loader
        self.setWindowTitle("راهنمای کد وضعیت سفارش")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(760)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        root.addWidget(widgets.label("راهنمای «کد وضعیت سفارش»", size=14, bold=True))
        root.addWidget(widgets.label(
            "فقط خواندن؛ هیچ چیزی در حسابداری نوشته نمی‌شود. چند سفارش از جدول پایین را در «سازه "
            "حساب» باز کنید و ببینید وضعیت هر کدام چه نامی دارد؛ کدی که با وضعیت دلخواه برای "
            "سفارش تازهٔ اینترنتی یکی است را در «سرور فروشگاه › کد وضعیت سفارش» بنویسید. پیش از "
            "سرور اصلی این کار را روی یک نسخهٔ جدا از پایگاه‌دادهٔ واقعی انجام دهید.",
            name="Muted", wrap=True))
        self.database_label = widgets.label("", bold=True, wrap=True)
        root.addWidget(self.database_label)
        root.addWidget(widgets.label("کدهای وضعیت و تعداد سفارش‌ها:", bold=True))
        self.status_table = widgets.DataTable(STATUS_HEADERS, key="status_codes",
                                              fit_width=True, stretch_column=1)
        self.status_table.set_empty_state("سفارشی نیست", "این پایگاه‌داده هنوز سفارشی ندارد.")
        self.status_table.setMinimumHeight(170)
        root.addWidget(self.status_table)
        root.addWidget(widgets.label("آخرین سفارش‌هایی که خود «سازه حساب» ساخته است:", bold=True))
        self.latest_table = widgets.DataTable(LATEST_HEADERS, key="status_latest",
                                              fit_width=True, stretch_column=0)
        self.latest_table.set_empty_state("سفارشی نیست",
                                          "«سازه حساب» هنوز سفارشی در این پایگاه‌داده نساخته است.")
        self.latest_table.setMinimumHeight(200)
        root.addWidget(self.latest_table)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        self.refresh_button = widgets.button("خواندن دوباره", icon_name="refresh",
                                             on_click=self.load)
        root.addLayout(widgets.footer(self.refresh_button,
                                      close=widgets.button("بستن", on_click=self.accept)))
        self.load()

    def load(self) -> None:
        self.refresh_button.setEnabled(False)
        self.error_label.setVisible(False)
        self.status_table.set_busy(True)
        self.latest_table.set_busy(True)
        run_async(self.loader, on_success=self.show_payload, on_error=self._failed,
                  on_done=lambda: self.refresh_button.setEnabled(True))

    def _failed(self, message: str, _kind: str = "") -> None:
        self.status_table.set_error_state()
        self.latest_table.set_error_state()
        self.error_label.setText("خوانده نشد: " + message)
        self.error_label.setVisible(True)

    def show_payload(self, payload: dict) -> None:
        payload = payload or {}
        self.status_table.set_busy(False)
        self.latest_table.set_busy(False)
        if not payload.get("ok", True):
            self._failed(str(payload.get("message_fa") or "حسابداری در دسترس نیست."))
            return
        database = str(payload.get("database") or "")
        self.database_label.setText(f"پایگاه‌داده: «{database}»" if database else "")
        self.status_table.fill(status_rows(payload))
        self.latest_table.fill(latest_rows(payload))
