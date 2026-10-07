"""صفحهٔ داشبورد — چهار کارت آماری، آخرین سفارش‌ها و به‌روزرسانی خودکار."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...persian import format_int, format_money, format_shamsi, to_persian_digits
from ...statuses import (
    ORDER_APPROVED,
    ORDER_RECEIPT_UPLOADED,
    ORDER_STATUS_FA,
    ORDER_WRITTEN,
    order_status_fa,
)
from .. import theme, widgets
from ..base_page import BasePage
from ..context import AppContext

DASHBOARD_HEADERS = ("شماره سفارش", "مشتری", "تعداد اقلام", "مبلغ کل", "وضعیت", "تاریخ ثبت")


class DashboardPage(BasePage):
    title = "داشبورد"
    subtitle = "نمای کلی فروشگاه — هر ۳۰ ثانیه به‌روزرسانی می‌شود"
    auto_refreshable = True

    def build_body(self) -> None:
        cards = widgets.CardGrid(min_card_width=250)
        self.card_pending_customers = widgets.StatCard(
            "مشتریان در انتظار تأیید", icon_name="customers",
            accent=theme.WARNING, tint=theme.WARNING_LIGHT,
        )
        self.card_receipts = widgets.StatCard(
            "سفارش‌های در انتظار بررسی فیش", icon_name="receipt",
            accent=theme.PRIMARY, tint=theme.PRIMARY_LIGHT,
        )
        self.card_today = widgets.StatCard(
            "سفارش‌های تأییدشده امروز", icon_name="check",
            accent=theme.SUCCESS, tint=theme.SUCCESS_LIGHT,
        )
        self.card_products = widgets.StatCard(
            "تعداد محصولات فعال", icon_name="products",
            accent=theme.INFO, tint=theme.INFO_LIGHT,
        )
        for card in (self.card_pending_customers, self.card_receipts,
                     self.card_today, self.card_products):
            cards.add_card(card)
        self.body.addWidget(cards)

        self.card_pending_customers.clicked.connect(lambda: self._go("customers", "pending"))
        self.card_receipts.clicked.connect(lambda: self._go("orders", ORDER_RECEIPT_UPLOADED))
        self.card_today.clicked.connect(lambda: self._go("orders", ORDER_WRITTEN))

        chart_panel = widgets.Panel("سفارش‌های ۷ روز اخیر")
        self.chart = widgets.BarChart()
        chart_panel.body.addWidget(self.chart)
        self.body.addWidget(chart_panel)

        panel = widgets.Panel("آخرین ۱۰ سفارش")
        self.table = widgets.DataTable(DASHBOARD_HEADERS, key="dashboard")
        self.table.set_empty_state(
            "هنوز سفارشی ثبت نشده است",
            "به‌محض ثبت سفارش توسط مشتریان، اینجا نمایش داده می‌شود.",
            "orders",
        )
        self.table.setMinimumHeight(300)
        panel.body.addWidget(self.table, 1)
        self.body.addWidget(panel, 1)

        self.body.addWidget(widgets.label(
            "برای دیدن جزئیات، از صفحهٔ «سفارش‌ها» استفاده کنید.", name="Faint"))

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        for card in (self.card_pending_customers, self.card_receipts,
                     self.card_today, self.card_products):
            card.set_loading()
        self.table.set_busy(True)

        def work() -> dict:
            api = self.context.api
            return {
                "pending_customers": api.list_customers("pending"),
                "receipts": api.list_orders(ORDER_RECEIPT_UPLOADED),
                "approved": api.list_orders(ORDER_APPROVED),
                "written": api.list_orders(ORDER_WRITTEN),
                "products": api.list_products(page=1, page_size=1),
                "info": api.system_info(),
            }

        self.run(work, on_success=self._render, on_error=self._fail)

    def _fail(self, message: str, kind: str) -> None:
        for card in (self.card_pending_customers, self.card_receipts,
                     self.card_today, self.card_products):
            card.set_error()
        self.show_table_error(message)
        self.default_error(message, kind)

    def _render(self, data: dict) -> None:
        self.context.apply_system_info(data["info"])

        pending_customers = data["pending_customers"]
        receipts = data["receipts"]
        approved = data["approved"]
        written = data["written"]
        products = data["products"]

        # "تأییدشده امروز": orders approved or written whose last action is today.
        today_orders = [
            order for order in list(approved) + list(written)
            if _is_today(order.get("created_at"))
        ]

        self.card_pending_customers.set_value(format_int(len(pending_customers)))
        self.card_receipts.set_value(format_int(len(receipts)))
        self.card_today.set_value(
            format_int(len(today_orders)),
            hint=f"از {to_persian_digits(len(written) + len(approved))} سفارش تأییدشده",
        )
        self.card_products.set_value(format_int(products.get("total", 0)))

        all_orders = list(receipts) + list(approved) + list(written)
        self.chart.set_data(orders_per_day(all_orders))
        rows = sorted(
            all_orders,
            key=lambda order: order.get("created_at") or "",
            reverse=True,
        )[:10]
        self._fill_table(rows)
        self.table.set_busy(False)

    def _fill_table(self, orders: list[dict]) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for order in orders:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, to_persian_digits(order.get("id", "")))
                self.table.set_cell(row, 1, str(order.get("user_name") or f"سفارش {to_persian_digits(order.get('id'))}"))
                items = order.get("items") or []
                self.table.set_cell(row, 2, to_persian_digits(len(items)))
                self.table.set_cell(row, 3, format_money(order.get("total", 0)), bold=True)
                self.table.set_widget(row, 4, widgets.pill_cell(
                    widgets.StatusPill(order_status_fa(order.get("status")), order.get("status"))
                ))
                self.table.set_cell(row, 5, format_shamsi(order.get("created_at")))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._empty_widget = None if orders else self.table._empty_widget
        self.table._refresh_states()

    # ------------------------------------------------------------------ nav
    def _go(self, page_key: str, filter_key: str = "") -> None:
        window = self.window()
        navigate = getattr(window, "navigate", None)
        if callable(navigate):
            navigate(page_key, filter_key)


def orders_per_day(orders: list[dict], days: int = 7, today: date | None = None) -> list[tuple[str, int]]:
    """Order counts for the last ``days`` days, oldest first, labelled شمسی «ماه/روز»."""
    from ...persian import coerce_datetime, gregorian_to_jalali

    end = today or datetime.now().date()
    counts = {end - timedelta(days=offset): 0 for offset in range(days - 1, -1, -1)}
    for order in orders:
        moment = coerce_datetime(order.get("created_at"))
        if moment is not None and moment.date() in counts:
            counts[moment.date()] += 1
    result = []
    for day, count in counts.items():
        _, month, dom = gregorian_to_jalali(day.year, day.month, day.day)
        result.append((to_persian_digits(f"{month}/{dom}"), count))
    return result


def _is_today(value: object) -> bool:
    from ...persian import coerce_datetime

    moment = coerce_datetime(value)
    if moment is None:
        return False
    return moment.date() == datetime.now().date()
