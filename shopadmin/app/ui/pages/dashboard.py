"""صفحهٔ داشبورد — چهار کارت آماری، آخرین سفارش‌ها و به‌روزرسانی خودکار."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...api_client import ApiError
from ...permissions import PRODUCTS_VIEW, SHOP_STATE
from ...persian import (
    format_datetime_shamsi,
    format_int,
    format_money,
    format_shamsi,
    to_persian_digits,
)
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
    help_text = "خلاصهٔ امروز فروشگاه. هشدارهای مهم (اگر باشد) بالای صفحه با رنگ زرد نشان داده می‌شوند."
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
        # v2.8.3: «محصولات» is its own permission (the dashboard is for everyone)
        shown = [self.card_pending_customers, self.card_receipts, self.card_today]
        if self.context.can(PRODUCTS_VIEW):
            shown.append(self.card_products)
        else:
            self.card_products.setVisible(False)
        for card in shown:
            cards.add_card(card)
        self.body.addWidget(cards)

        self.card_pending_customers.clicked.connect(lambda: self._go("customers", "pending"))
        self.card_receipts.clicked.connect(lambda: self._go("orders", ORDER_RECEIPT_UPLOADED))
        self.card_today.clicked.connect(lambda: self._go("orders", ORDER_WRITTEN))

        # v2.6.0: setup problems that stop the bot from selling (no payment card,
        # no product group shown in the bot). Hidden while everything is fine.
        self.setup_warning = widgets.label("", color=theme.WARNING_TEXT, bold=True, wrap=True)
        self.setup_warning.setObjectName("SetupWarning")
        self.setup_warning.setStyleSheet(
            f"QLabel#SetupWarning {{ background: {theme.WARNING_BG}; border: 2px solid {theme.WARNING};"
            f" border-radius: 8px; padding: 12px 16px; font-size: 14px; }}")
        self.setup_warning.setVisible(False)
        self.body.addWidget(self.setup_warning)

        # Sales state (v2.5.0): sales follow the distributor's price list
        # (morning list until 13:30, evening list until 20:30, Friday closed).
        # The buttons override it; the decision is stored and audited on the server.
        # Only phones (priced from the Telegram list) are affected; accessories
        # and other items stay orderable at all times.
        shop_panel = widgets.Panel("وضعیت فروش گوشی")
        self.shop_state_label = widgets.label("…", bold=True)
        self.shop_state_label.setWordWrap(True)
        shop_panel.body.addWidget(self.shop_state_label)
        self.shop_state_detail = widgets.label("", name="Faint")
        self.shop_state_detail.setWordWrap(True)
        shop_panel.body.addWidget(self.shop_state_detail)
        buttons = QHBoxLayout()
        self.sales_buttons: dict[str, object] = {}
        for action, text, variant in (
            ("open", "باز کردن فروش", "primary"),
            ("close", "بستن فروش", "default"),
            ("holiday", "تعطیلی امروز", "default"),
        ):
            btn = widgets.button(text, variant=variant,
                                 on_click=lambda _=False, a=action: self._sales_action(a))
            btn.setVisible(False)
            buttons.addWidget(btn)
            self.sales_buttons[action] = btn
        buttons.addStretch(1)
        shop_panel.body.addLayout(buttons)
        self.body.addWidget(shop_panel)
        self._shop_closed: bool | None = None
        # Old name kept for callers/tests that look for "the" toggle.
        self.shop_toggle = self.sales_buttons["close"]

        chart_panel = widgets.Panel("سفارش‌های ۷ روز اخیر")
        self.chart = widgets.BarChart()
        chart_panel.body.addWidget(self.chart)
        self.body.addWidget(chart_panel)

        panel = widgets.Panel("آخرین ۱۰ سفارش")
        # v2.8.3: the columns fill the panel; no horizontal scroll bar under the table
        self.table = widgets.DataTable(DASHBOARD_HEADERS, key="dashboard", fit_width=True)
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

        show_products = self.context.can(PRODUCTS_VIEW)

        def work() -> dict:
            api = self.context.api
            return {
                "pending_customers": api.list_customers("pending"),
                "receipts": api.list_orders(ORDER_RECEIPT_UPLOADED),
                "approved": api.list_orders(ORDER_APPROVED),
                "written": api.list_orders(ORDER_WRITTEN),
                "products": (api.list_products(page=1, page_size=1) if show_products
                             else {"total": 0}),
                "info": api.system_info(),
                "shop": _shop_state(api),
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
        self._render_shop_state(data.get("shop"))

        all_orders = list(receipts) + list(approved) + list(written)
        # v2.8.3: the chart of a user who is not a manager counts only their own work
        principal = self.context.principal
        manager = principal is not None and principal.is_manager
        self.chart.set_data(orders_per_day(all_orders if manager
                                           else [o for o in all_orders if o.get("owned_by_me")]))
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

    # ------------------------------------------------------------------ sales state
    def _render_setup_warning(self, state: object) -> None:
        problems = setup_problems(state)
        self.setup_warning.setText("⚠️ " + "\n⚠️ ".join(problems) if problems else "")
        self.setup_warning.setVisible(bool(problems))

    def _render_shop_state(self, state: object) -> None:
        self._render_setup_warning(state)
        if not isinstance(state, dict):
            self._shop_closed = None
            self.shop_state_label.setText("وضعیت فروش گوشی از سرور خوانده نشد.")
            self.shop_state_detail.setText("")
            for btn in self.sales_buttons.values():
                btn.setVisible(False)
            return
        closed = bool(state.get("closed"))
        self._shop_closed = closed
        message = str(state.get("message_fa") or "").strip()
        if closed:
            self.shop_state_label.setText(
                "🔒 " + (message or "فروش گوشی بسته است.")
                + " ربات آخرین قیمت‌های گوشی را نشان می‌دهد ولی سفارش گوشی نمی‌گیرد؛ "
                "لوازم جانبی و سایر کالاها همچنان قابل سفارش‌اند.")
        else:
            self.shop_state_label.setText("✅ " + (message or "فروش گوشی باز است."))
        self.shop_state_detail.setText(sales_detail_text(state))
        allowed = self.context.can(SHOP_STATE)
        for action, btn in self.sales_buttons.items():
            # «باز کردن» only while closed; «بستن» and «تعطیلی» are always offered.
            btn.setVisible(allowed and (closed if action == "open" else True))

    def _sales_action(self, action: str) -> None:
        if self._shop_closed is None:
            return
        questions = {
            "open": "فروش گوشی همین حالا باز شود؟ تا رسیدن لیست قیمت جدید یا ساعت پایان فروش "
                    "(۱۳:۳۰ / ۲۰:۳۰) باز می‌ماند و هر زمان می‌توانید آن را ببندید.",
            "close": "فروش گوشی همین حالا بسته شود؟ ربات آخرین قیمت‌ها را نشان می‌دهد ولی "
                     "سفارش گوشی نمی‌گیرد، تا لیست قیمت بعدی یا تا وقتی دوباره باز کنید. "
                     "لوازم جانبی و سایر کالاها قابل سفارش می‌مانند.",
            "holiday": "امروز تعطیل اعلام شود؟ فروش گوشی تا صبح فردا بسته می‌ماند "
                       "(لوازم جانبی قابل سفارش می‌ماند).",
        }
        if not widgets.confirm(self, "وضعیت فروش گوشی", questions[action]):
            return
        for btn in self.sales_buttons.values():
            btn.setEnabled(False)
        self.run(
            lambda: self.context.api.sales_action(action),
            on_success=lambda state: self._shop_toggled(state, action),
            on_error=lambda message, kind: (
                [b.setEnabled(True) for b in self.sales_buttons.values()],
                self.default_error(message, kind),
            ),
        )

    def _toggle_shop(self) -> None:
        """Old single switch: closes when open, opens when closed."""
        if self._shop_closed is None:
            return
        self._sales_action("open" if self._shop_closed else "close")

    def _shop_toggled(self, state: object, action: str = "") -> None:
        for btn in self.sales_buttons.values():
            btn.setEnabled(True)
        self.context.audit("sales_" + (action or "state"),
                           f"closed={bool((state or {}).get('closed'))}")
        self._render_shop_state(state)

    # ------------------------------------------------------------------ nav
    def _go(self, page_key: str, filter_key: str = "") -> None:
        window = self.window()
        navigate = getattr(window, "navigate", None)
        if callable(navigate):
            navigate(page_key, filter_key)


_REASONS_FA = {
    "list": "طبق لیست قیمت",
    "manual_open": "باز شده به‌دست کاربر",
    "manual_close": "بسته شده به‌دست کاربر",
    "holiday": "تعطیلی امروز",
    "weekday_closed": "جمعه",
    "no_list": "لیست قیمتی نرسیده",
    "list_not_updated": "لیست قیمت به‌روز نشده",
    "windows_disabled": "زمان‌بندی فروش خاموش است",
}


def sales_detail_text(state: dict) -> str:
    """One Persian line: why, until when, by whom, which list."""
    parts = []
    reason = _REASONS_FA.get(str(state.get("reason") or ""))
    if reason:
        parts.append(f"علت: {reason}")
    if state.get("until"):
        parts.append(f"تا {format_datetime_shamsi(state['until'])}")
    if state.get("override_by"):
        by = str(state["override_by"]).split(":", 1)[-1]
        parts.append(f"به‌دست {by}")
    slot = {"morning": "صبح", "evening": "عصر"}.get(str(state.get("list_slot") or ""))
    if state.get("list_date"):
        parts.append(f"لیست {slot + ' ' if slot else ''}{state['list_date']}")
    if state.get("receipt_deadline_minutes"):
        parts.append(f"مهلت رسید: {state['receipt_deadline_minutes']} دقیقه")
    return to_persian_digits(" — ".join(parts))


def setup_problems(state: object) -> list[str]:
    """v2.6.0: why the bot cannot sell right now (empty = nothing to fix)."""
    if not isinstance(state, dict):
        return []
    problems = []
    if state.get("payment_ready") is False:
        problems.append("شمارهٔ کارت پرداخت تنظیم نشده است؛ ربات سفارش نهایی را نمی‌پذیرد. "
                        "در «سرور فروشگاه › تنظیمات» شمارهٔ کارت ۱۶ رقمی را وارد کنید.")
    if state.get("catalog_ready") is False:
        problems.append("هیچ گروه کالایی برای نمایش در ربات انتخاب نشده؛ ربات کالایی نشان "
                        "نمی‌دهد. از صفحهٔ «گروه‌های کالا» گروه‌ها را انتخاب کنید.")
    if state.get("phone_groups_ready") is False:
        # v2.6.1: without a phone group nothing is treated as a phone: no price-list
        # pricing and the phone sales window does not apply to any item.
        problems.append("هیچ گروهی «گروه گوشی» علامت نخورده است؛ گوشی‌ها شناخته نمی‌شوند، "
                        "قیمتشان از لیست قیمت نیست و بسته بودن فروش گوشی رویشان اثر ندارد. "
                        "در صفحهٔ «گروه‌های کالا» گروه «گوشی» را تیک «گروه گوشی» بزنید.")
    return problems


def _shop_state(api) -> dict | None:
    """Closed-mode flag; None when this server build has no such endpoint."""
    try:
        return api.shop_state()
    except ApiError:
        return None


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
