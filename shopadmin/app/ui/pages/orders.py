"""صفحهٔ سفارش‌ها — بررسی فیش‌ها و تأیید یا رد پرداخت."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QScrollArea,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...activity import timeline_text
from ...permissions import (
    ORDERS_APPROVE_PAYMENT,
    ORDERS_ASSIGN,
    ORDERS_CANCEL,
    ORDERS_REJECT_PAYMENT,
    ORDERS_SHIP,
    SETTINGS_VIEW,
)
from ...persian import (
    format_datetime_shamsi,
    format_money,
    format_qty,
    format_shamsi,
    normalize_fa,
    price_level_label,
    to_persian_digits,
)
from ...statuses import (
    ORDER_APPROVED,
    ORDER_AWAITING_PAYMENT,
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_RECEIPT_UPLOADED,
    ORDER_REJECTED,
    ORDER_WRITTEN,
    order_status_fa,
)
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..context import AppContext
from ..rtl import RIGHT

HEADERS = ("شماره سفارش", "نام مشتری", "تعداد اقلام", "مبلغ کل", "وضعیت", "مسئول",
           "مهلت ارسال رسید", "تاریخ ثبت")

#: v2.8.0: a receipt waiting longer than this is highlighted (and counted).
WAITING_MINUTES = 10
WAITING_STATUSES = ("receipt_uploaded",)


def waiting_too_long(row: dict, now=None, minutes: int = WAITING_MINUTES,
                     statuses=WAITING_STATUSES) -> bool:
    """A receipt (or a new request) nobody has handled for ``minutes``."""
    from datetime import datetime, timezone

    if row.get("status") not in statuses:
        return False
    stamp = row.get("updated_at") or row.get("created_at")
    try:
        when = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - when).total_seconds() >= minutes * 60


def owner_label(row: dict) -> str:
    """«من» / the colleague's name (manager only) / «همکار» / «آزاد»."""
    if row.get("owned_by_me"):
        return "من"
    if row.get("owner_name"):
        return str(row["owner_name"])
    return "همکار" if row.get("owned") else "آزاد"


def copy_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText(str(text or ""))

TABS = (
    ("awaiting_payment", "در انتظار پرداخت", ORDER_AWAITING_PAYMENT),
    ("receipt_uploaded", "رسید رسیده", ORDER_RECEIPT_UPLOADED),
    ("approved", "تأییدشده", ORDER_APPROVED),
    ("rejected", "ردشده", ORDER_REJECTED),
    # v2.5.0: no receipt within the deadline (30 min) -> cancelled on the shop server
    ("cancelled", "لغوشده", ORDER_CANCELLED),
    ("expired", "منقضی", ORDER_EXPIRED),
    ("written", "ثبت‌شده در حسابداری", ORDER_WRITTEN),
)

#: v2.7.0: friendly empty states («سفارش جدیدی نیست»).
EMPTY_TITLES = {
    "awaiting_payment": "سفارش جدیدی نیست",
    "receipt_uploaded": "رسید تازه‌ای نرسیده است",
    "approved": "سفارش تأییدشده‌ای نیست",
    "rejected": "سفارش ردشده‌ای نیست",
    "cancelled": "سفارش لغوشده‌ای نیست",
    "expired": "سفارش منقضی‌ای نیست",
    "written": "سفارشی در حسابداری ثبت نشده است",
}
EMPTY_HINTS = {
    "awaiting_payment": "سفارش‌هایی که در انتظار واریز مبلغ توسط مشتری هستند اینجا نمایش داده می‌شوند.",
    "receipt_uploaded": "به‌محض اینکه مشتری رسید پرداخت را بفرستد، سفارش اینجا می‌آید.",
    "approved": "سفارش‌های تأییدشده در این زبانه دیده می‌شوند.",
    "rejected": "سفارش‌هایی که پرداختشان رد شده است اینجا نمایش داده می‌شوند.",
    "cancelled": "سفارش‌هایی که لغو شده‌اند (به‌دست مشتری، همکاران، یا چون رسیدشان "
                 "به‌موقع نرسید). در حسابداری چیزی حذف نمی‌شود.",
    "expired": "سفارش‌های قدیمی که مهلت پرداختشان تمام شده است.",
    "written": "سفارش‌هایی که در نرم‌افزار حسابداری ثبت شده‌اند.",
}


class OrdersPage(BasePage):
    title = "سفارش‌ها"
    subtitle = "رسیدهای پرداخت، تأیید، ارسال و لغو سفارش‌ها"
    help_text = "سفارش‌های مشتریان. روی هر سفارش کلیک کنید تا رسید را ببینید، تأیید کنید، «ارسال شد» بزنید یا آن را لغو کنید."
    #: v2.8.0: lists refresh by themselves (the server's events refresh them too)
    auto_refreshable = True

    def build_body(self) -> None:
        # v2.8.0: «کارهای من» (default for sales users) / «همه»
        scope_holder = QWidget()
        scope_bar = widgets.FlowLayout(scope_holder, spacing=8)
        principal = self.context.principal
        self._mine = principal is not None and not principal.is_manager
        self._scope_buttons = {}
        from .item_requests import _filter_caption

        scope_bar.addWidget(_filter_caption("نمایش:"))
        # v2.8.1: «همهٔ سفارش‌ها», not a bare «همه»
        for key, text in (("mine", "کارهای من"), ("all", "همهٔ سفارش‌ها")):
            btn = widgets.button(text, variant="ghost")
            btn.setObjectName("Tab")
            btn.setCheckable(True)
            btn.setChecked((key == "mine") == self._mine)
            btn.clicked.connect(lambda _checked=False, k=key: self.set_scope(k == "mine"))
            self._scope_buttons[key] = btn
            scope_bar.addWidget(btn)
        self.waiting_label = widgets.label("", color=theme.WARNING_TEXT, bold=True)
        self.waiting_label.setVisible(False)
        scope_bar.addWidget(self.waiting_label)
        self.body.addWidget(scope_holder)

        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
        self._tab_buttons: dict[str, object] = {}
        self._active_tab = "receipt_uploaded"
        for key, label_text, _status in TABS:
            tab = widgets.button(label_text, variant="ghost")
            tab.setObjectName("Tab")
            tab.setCheckable(True)
            tab.setChecked(key == self._active_tab)
            tab.clicked.connect(lambda _checked=False, k=key: self._select_tab(k))
            self._tab_buttons[key] = tab
            bar.addWidget(tab)

        self.search = widgets.SearchBox("نام مشتری یا شمارهٔ سفارش")
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search)
        self.body.addWidget(bar_holder)

        panel = widgets.Panel()


        self.table = widgets.DataTable(HEADERS, selectable_rows=True, key="orders")
        self.table.set_empty_state("سفارش جدیدی نیست", "", "orders")
        self.table.setMinimumHeight(360)
        self.table.row_activated.connect(self._open_row)
        panel.body.addWidget(self.table, 1)

        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)

        self._orders: list[dict] = []
        self._visible: list[dict] = []

    # ------------------------------------------------------------------ state
    def _select_tab(self, key: str) -> None:
        self._active_tab = key
        for tab_key, widget in self._tab_buttons.items():
            widget.setChecked(tab_key == key)
        self.load()

    def set_filter(self, key: str) -> None:
        if key in self._tab_buttons:
            self._select_tab(key)

    def set_scope(self, mine: bool) -> None:
        self._mine = bool(mine)
        for key, btn in self._scope_buttons.items():
            btn.setChecked((key == "mine") == self._mine)
        self.load()

    def _on_search(self, _text: str) -> None:
        self._render()

    def _status_for_tab(self) -> Optional[str]:
        for key, _label, status in TABS:
            if key == self._active_tab:
                return status
        return None

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        self.table.set_busy(True)
        status = self._status_for_tab()
        mine = self._mine
        self.run(
            lambda: self.context.api.list_orders(status, mine=mine),
            on_success=self._on_loaded,
            on_error=self._on_error,
        )

    def _on_error(self, message: str, kind: str) -> None:
        self._orders = []
        self._visible = []
        self.table.fill([])
        self.show_table_error(message)
        self.default_error(message, kind)

    def _on_loaded(self, orders: list) -> None:
        self._orders = list(orders or [])
        self.table.set_busy(False)
        self._render()

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        needle = normalize_fa(self.search.text())
        rows = []
        for order in self._orders:
            haystack = " ".join([
                normalize_fa(order.get("id", "")),
                normalize_fa(order.get("user_name") or ""),
                normalize_fa(order.get("accounting_order_no") or ""),
            ])
            if needle and needle not in haystack:
                continue
            rows.append(order)
        self._visible = rows

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for order in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, to_persian_digits(order.get("id", "")), bold=True)
                self.table.set_cell(row, 1, self._customer_label(order))
                self.table.set_cell(row, 2, to_persian_digits(len(order.get("items") or [])))
                self.table.set_cell(row, 3, format_money(order.get("total", 0)))
                self.table.set_widget(row, 4, widgets.pill_cell(
                    widgets.StatusPill(order_status_fa(order.get("status")), order.get("status"))
                ))
                self.table.set_cell(row, 5, owner_label(order),
                                    bold=bool(order.get("owned_by_me")))
                self.table.set_cell(row, 6, format_shamsi(order.get("reserve_until")) if order.get("reserve_until") else "—")
                self.table.set_cell(row, 7, format_shamsi(order.get("created_at")))
                if waiting_too_long(order):
                    # v2.8.0: a receipt nobody checked for 10 minutes stands out
                    late = self.table.set_cell(
                        row, 0, to_persian_digits(order.get("id", "")), bold=True,
                        color=theme.WARNING_TEXT,
                        tooltip=f"بیش از {to_persian_digits(WAITING_MINUTES)} دقیقه منتظر بررسی است")
                    late.setData(Qt.ItemDataRole.UserRole, "late")
        finally:
            self.table.setUpdatesEnabled(True)
        late_count = sum(1 for order in rows if waiting_too_long(order))
        self.waiting_label.setText(
            f"⏱ {to_persian_digits(late_count)} رسید بیش از "
            f"{to_persian_digits(WAITING_MINUTES)} دقیقه منتظر بررسی است" if late_count else "")
        self.waiting_label.setVisible(bool(late_count))

        status_fa = order_status_fa(self._status_for_tab())
        if not rows:
            if needle:
                self.table.set_empty_state(
                    "سفارشی با این جستجو پیدا نشد",
                    "شمارهٔ سفارش یا نام مشتری را بررسی کنید.",
                    "search",
                )
            else:
                self.table.set_empty_state(
                    EMPTY_TITLES.get(self._active_tab, f"سفارشی در بخش «{status_fa}» نیست"),
                    EMPTY_HINTS.get(self._active_tab, ""),
                    "orders",
                )
        self.table._refresh_states()
        total = sum(float(order.get("total") or 0) for order in rows)
        self.summary.setText(
            f"{to_persian_digits(len(rows))} سفارش — مجموع مبلغ: {format_money(total)}"
        )

    @staticmethod
    def _customer_label(order: dict) -> str:
        return customer_label(order)

    # ------------------------------------------------------------------ detail
    def _open_row(self, row: int) -> None:
        if 0 <= row < len(self._visible):
            self.open_order(self._visible[row])

    def open_order(self, order: dict) -> None:
        dialog = OrderDetailDialog(self.context, order, self)
        dialog.exec()
        if dialog.changed:
            self.load()

    def expire_orders(self) -> None:
        run_async(
            self.context.api.expire_orders,
            on_success=lambda result: self._expired(result),
            on_error=lambda message, kind: self.default_error(message, kind),
        )

    def _expired(self, result: object) -> None:
        count = int((result or {}).get("expired", 0)) if isinstance(result, dict) else 0
        self.notify_success(f"{to_persian_digits(count)} سفارش منقضی علامت خورد")
        self.load()


class OrderDetailDialog(widgets.ResponsiveDialog):
    """جزئیات کامل یک سفارش با امکان تأیید یا رد پرداخت."""

    def __init__(self, context: AppContext, order: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.order = order
        self.changed = False

        self.setWindowTitle(f"جزئیات سفارش {to_persian_digits(order.get('id', ''))}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ---- header ------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(widgets.label(
            f"سفارش شمارهٔ {to_persian_digits(order.get('id', ''))}", size=14, bold=True
        ), 1)
        self.status_pill = widgets.StatusPill(
            order_status_fa(order.get("status")), order.get("status")
        )
        header.addWidget(self.status_pill)
        root.addLayout(header)

        # ---- meta --------------------------------------------------------
        meta = widgets.Panel()
        grid = QHBoxLayout()
        grid.setSpacing(28)
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(_kv("مشتری", self._customer_label(order)))
        if order.get("user_phone"):
            phone_row = QHBoxLayout()
            phone_row.addWidget(_kv("موبایل مشتری", to_persian_digits(order["user_phone"])), 1)
            self.copy_phone_button = widgets.button(
                "کپی", icon_name="copy", tooltip="کپی شمارهٔ موبایل مشتری",
                on_click=lambda: (copy_to_clipboard(order["user_phone"]),
                                  self._show_info("شمارهٔ موبایل کپی شد.")))
            phone_row.addWidget(self.copy_phone_button)
            left.addLayout(phone_row)
        left.addWidget(_kv("مسئول", owner_label(order)))
        code = order.get("user_person_code")
        left.addWidget(_kv("کد شخص در حسابداری",
                           to_persian_digits(code) if code is not None else "هنوز وصل نشده"))
        left.addWidget(_kv("تاریخ ثبت", format_shamsi(order.get("created_at"))))
        left.addWidget(_kv("مهلت ارسال رسید", format_datetime_shamsi(order.get("reserve_until"))
                           if order.get("reserve_until") else "—"))
        if context.can(SETTINGS_VIEW):
            left.addWidget(_kv("پایگاه‌دادهٔ حسابداری", str(order.get("accounting_db") or "—")))
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(_kv("مبلغ کل", format_money(order.get("total", 0))))
        if context.can(SETTINGS_VIEW):
            right.addWidget(_kv("سطح قیمت", price_level_label(order.get("price_level", 0))))
        right.addWidget(_kv("شمارهٔ حسابداری", to_persian_digits(order.get("accounting_order_no"))
                            if order.get("accounting_order_no") else "—"))
        right.addWidget(_kv("پیگیری", tracking_fa(order)))
        if order.get("courier_name") or order.get("courier_phone"):
            right.addWidget(_kv("پیک", courier_text(order)))
        grid.addLayout(right)
        grid.addLayout(left)
        grid.addStretch(1)
        meta.body.addLayout(grid)
        root.addWidget(meta)

        # ---- items -------------------------------------------------------
        items_panel = widgets.Panel("اقلام سفارش")
        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(("کد کالا", "نام کالا", "تعداد", "قیمت واحد"))
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setShowGrid(False)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.items_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.items_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.items_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.items_table.verticalHeader().setDefaultSectionSize(38)
        self.items_table.setMinimumHeight(160)
        widgets.show_full_headers(self.items_table)
        items = order.get("items") or []
        self.items_table.setRowCount(len(items))
        for index, item in enumerate(items):
            values = (
                to_persian_digits(item.get("kala_code", "")),
                str(item.get("name") or "—"),
                format_qty(item.get("qty", 0)),
                format_money(item.get("unit_price", 0)),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
                self.items_table.setItem(index, column, cell)
        items_panel.body.addWidget(self.items_table)
        items_panel.body.addWidget(widgets.label(
            f"تعداد اقلام: {to_persian_digits(len(items))} — "
            f"مبلغ کل: {format_money(order.get('total', 0))}",
            name="Muted",
        ))
        root.addWidget(items_panel, 1)

        # ---- v2.8.0: what was done so far (names only for the manager) ------
        self.timeline_label = widgets.label("…", wrap=True)
        timeline_panel = widgets.Panel("کارهای انجام‌شده")
        timeline_panel.body.addWidget(self.timeline_label)
        root.addWidget(timeline_panel)
        if order.get("request_id"):
            timeline_panel.body.addWidget(widgets.label(
                f"این سفارش از «درخواست خرید» شمارهٔ {to_persian_digits(order['request_id'])} "
                "ساخته شده است.", name="Muted", wrap=True))
        self._load_timeline()

        # ---- receipt -----------------------------------------------------
        receipt_ref = order.get("receipt_ref") or self._payment_ref(order)
        ref_panel = widgets.Panel("رسید پرداخت مشتری")
        ref_row = QHBoxLayout()
        ref_row.addWidget(widgets.label("شمارهٔ پیگیری رسید:", name="Muted"))
        self.receipt_ref_label = widgets.label(receipt_ref_text(order, receipt_ref),
                                               bold=bool(receipt_ref))
        ref_row.addWidget(self.receipt_ref_label)
        ref_row.addStretch(1)
        self.receipt_button = widgets.button(
            "نمایش تصویر رسید", icon_name="receipt", on_click=self._show_receipt
        )
        self.receipt_button.setEnabled(bool(order.get("has_receipt")))
        if not order.get("has_receipt"):
            self.receipt_button.setToolTip("تصویری از رسید روی سرور ذخیره نشده است")
        ref_row.addWidget(self.receipt_button)
        ref_panel.body.addLayout(ref_row)
        if order.get("customer_pending"):
            ref_panel.body.addWidget(widgets.label(
                "مشتری این سفارش هنوز تأیید نشده است؛ پرداخت پس از تأیید مشتری قابل تأیید است.",
                color=theme.WARNING_TEXT,
                wrap=True,
            ))
        root.addWidget(ref_panel)

        # ---- actions -----------------------------------------------------
        actions_holder = QWidget()
        actions = widgets.FlowLayout(actions_holder, spacing=10)
        self.approve_button = widgets.button(
            "تأیید رسید", variant="success", icon_name="check", on_click=self._approve
        )
        self.reject_button = widgets.button(
            "رد رسید", variant="danger", icon_name="close", on_click=self._reject
        )
        can_approve = context.can(ORDERS_APPROVE_PAYMENT)
        can_reject = context.can(ORDERS_REJECT_PAYMENT)
        actionable = order.get("status") == ORDER_RECEIPT_UPLOADED

        self.approve_button.setEnabled(actionable and can_approve)
        self.reject_button.setEnabled(actionable and can_reject)
        if not can_approve:
            self.approve_button.setToolTip("شما اجازهٔ تأیید رسید را ندارید")
        if not can_reject:
            self.reject_button.setToolTip("شما اجازهٔ رد رسید را ندارید")
        if not actionable and can_approve:
            tip = f"این سفارش در وضعیت «{order_status_fa(order.get('status'))}» است"
            self.approve_button.setToolTip(tip)
            self.reject_button.setToolTip(tip)

        self.ship_button = widgets.button(
            "ارسال شد", variant="primary", icon_name="check", on_click=self._ship
        )
        can_ship = context.can(ORDERS_SHIP)
        shippable = order.get("status") in SHIPPABLE and not order.get("shipped_at")
        self.ship_button.setEnabled(can_ship and shippable)
        if not can_ship:
            self.ship_button.setToolTip("شما اجازهٔ ثبت ارسال را ندارید")
        elif order.get("shipped_at"):
            self.ship_button.setToolTip("این سفارش قبلاً ارسال شده است")
        elif not shippable:
            self.ship_button.setToolTip("فقط سفارش پرداخت‌شده و تأییدشده قابل ارسال است")

        # v2.7.0: the customer's order can be cancelled until it is confirmed
        self.cancel_button = widgets.button(
            "لغو سفارش", icon_name="trash", on_click=self._cancel_order
        )
        cancellable = order.get("status") in CANCELLABLE
        self.cancel_button.setEnabled(context.can(ORDERS_CANCEL) and cancellable)
        if not context.can(ORDERS_CANCEL):
            self.cancel_button.setToolTip("شما اجازهٔ لغو سفارش را ندارید")
        elif not cancellable:
            self.cancel_button.setToolTip("سفارشِ تأییدشده یا ثبت‌شده لغو نمی‌شود")

        # v2.8.0: «برمی‌دارم» (a free order) and «ارجاع» (manager, «ارجاع سفارش»,
        # or the owner); a finished order is read-only for everyone
        finished = bool(order.get("finished") or order.get("archived"))
        self.claim_button = widgets.button("برمی‌دارم", icon_name="check",
                                           on_click=self._claim)
        self.claim_button.setVisible(not finished and not order.get("owned")
                                     and context.principal is not None)
        self.assign_button = widgets.button("ارجاع به همکار", icon_name="users",
                                            on_click=self._assign)
        may_assign = context.can(ORDERS_ASSIGN) or bool(order.get("owned_by_me"))
        self.assign_button.setVisible(not finished and may_assign)
        close = widgets.button("بستن", on_click=self.reject)
        if finished:
            for widget in (self.approve_button, self.reject_button, self.ship_button,
                           self.cancel_button):
                widget.setEnabled(False)
                widget.setToolTip("سفارش تمام شده است؛ تغییرات فقط در «سازه حساب» انجام می‌شود")
            root.addWidget(widgets.label(
                "این سفارش تمام شده و فقط‌خواندنی است. هر تغییری فقط در «سازه حساب» انجام می‌شود.",
                name="Muted", wrap=True))
        for widget in (self.approve_button, self.reject_button, self.ship_button,
                       self.cancel_button, self.claim_button, self.assign_button, close):
            widget.setProperty("big", True)
            # hidden, not disabled, when this account may never do it
            actions.addWidget(widget)
        self.approve_button.setVisible(can_approve and not finished)
        self.reject_button.setVisible(can_reject and not finished)
        self.ship_button.setVisible(can_ship and not finished)
        self.cancel_button.setVisible(context.can(ORDERS_CANCEL) and not finished)
        root.addWidget(actions_holder)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        self._detail_label = widgets.label("", name="Muted", wrap=True)
        self._detail_label.setVisible(False)
        root.addWidget(self._detail_label)

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _customer_label(order: dict) -> str:
        return customer_label(order)

    @staticmethod
    def _payment_ref(order: dict) -> str:
        payments = order.get("payments") or []
        if payments and isinstance(payments, list):
            return str(payments[0].get("receipt_ref") or "")
        return ""

    def _show_error(self, message: str, detail: str = "") -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        self._detail_label.setText(detail)
        self._detail_label.setVisible(bool(detail))

    def _show_info(self, message: str) -> None:
        self._detail_label.setText(message)
        self._detail_label.setVisible(True)

    # ---- v2.8.0: timeline, claim, handover ---------------------------------
    def _load_timeline(self) -> None:
        order_id = int(self.order.get("id") or 0)
        api = self.context.api
        if not hasattr(api, "order_timeline"):
            self.timeline_label.setText("—")
            return
        run_async(
            lambda: api.order_timeline(order_id),
            on_success=lambda rows: self.timeline_label.setText(timeline_text(list(rows or []))),
            on_error=lambda _m, _k: self.timeline_label.setText("—"),
        )

    def _claim(self) -> None:
        order_id = int(self.order["id"])
        self.claim_button.setEnabled(False)
        run_async(
            lambda: self.context.api.claim_order(order_id),
            on_success=lambda _r: self._changed_and_close(),
            on_error=lambda message, kind: (self.claim_button.setEnabled(True),
                                            self._failed(message, kind)),
        )

    def _assign(self) -> None:
        dialog = AssignDialog(self.context, self, f"سفارش {to_persian_digits(self.order['id'])}")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.staff_id is None:
            return
        order_id, staff_id = int(self.order["id"]), dialog.staff_id
        run_async(
            lambda: self.context.api.assign_order(order_id, staff_id),
            on_success=lambda _r: self._changed_and_close(),
            on_error=lambda message, kind: self._failed(message, kind),
        )

    def _changed_and_close(self) -> None:
        self.changed = True
        self.context.data_changed.emit()
        self.accept()

    # ---- actions ---------------------------------------------------------
    def _approve(self) -> None:
        order_id = int(self.order["id"])
        if not widgets.confirm(
            self, "تأیید رسید",
            f"رسید سفارش {to_persian_digits(order_id)} درست است و مبلغ واریز شده؟\n"
            "با تأیید، سفارش برای فروش ثبت می‌شود و به مشتری خبر داده می‌شود.",
            confirm_text="بله، تأیید کن",
        ):
            return
        self.approve_button.setEnabled(False)
        self.approve_button.setText("در حال تأیید…")

        def restore() -> None:
            self.approve_button.setText("تأیید رسید")
            self.approve_button.setEnabled(True)

        run_async(
            lambda: self.context.api.approve_payment(order_id),
            on_success=self._approved,
            on_error=lambda message, kind: (restore(), self._failed(message, kind)),
        )

    def _approved(self, result: object) -> None:
        written = isinstance(result, dict) and result.get("status") == ORDER_WRITTEN
        self.changed = True
        self.context.audit("approve_payment", f"order id={self.order.get('id')}")
        self.context.data_changed.emit()
        if written:
            self.accept()
        else:
            # shopapi answered 200 but did not commit (dry-run): never claim success.
            self._show_error(
                "پرداخت تأیید شد اما در حسابداری ثبت نشد (حالت آزمایشی).",
                self._dry_run_hint(),
            )
            self.accept()

    def _failed(self, message: str, kind: str) -> None:
        self._show_error(message, self._dry_run_hint() if self._looks_like_dry_run(kind) else "")
        widgets.error(self, "کار انجام نشد", message)

    def _dry_run_hint(self) -> str:
        if self.context.dry_run_mode and not self.context.can(SETTINGS_VIEW):
            return "برنامه در حالت آزمایشی است و سفارش واقعاً در حسابداری ثبت نمی‌شود."
        if self.context.dry_run_mode:
            return ("حالت آزمایشی فعال است؛ سفارش‌ها واقعاً در حسابداری ثبت نمی‌شوند. "
                    "برای ثبت واقعی، ACCOUNTING_WRITE_ENABLED را در سرور فروشگاه فعال کنید.")
        return ""

    @staticmethod
    def _looks_like_dry_run(_kind: str) -> bool:
        return False

    def _reject(self) -> None:
        order_id = int(self.order["id"])
        dialog = RejectPaymentDialog(self, to_persian_digits(order_id))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reason = dialog.reason
        self.reject_button.setEnabled(False)
        self.reject_button.setText("در حال رد کردن…")

        def restore() -> None:
            self.reject_button.setText("رد رسید")
            self.reject_button.setEnabled(True)

        run_async(
            lambda: self.context.api.reject_payment(order_id, reason),
            on_success=self._rejected,
            on_error=lambda message, kind: (restore(), self._failed(message, kind)),
        )

    def _rejected(self, _result: object) -> None:
        self.changed = True
        self.context.audit("reject_payment", f"order id={self.order.get('id')}")
        self.context.data_changed.emit()
        self.accept()

    def _ship(self) -> None:
        order_id = int(self.order["id"])
        dialog = ShipDialog(self, to_persian_digits(order_id))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, phone = dialog.courier_name, dialog.courier_phone
        self.ship_button.setEnabled(False)
        run_async(
            lambda: self.context.api.ship_order(order_id, name, phone),
            on_success=self._shipped,
            on_error=lambda message, kind: (
                self.ship_button.setEnabled(True), self._show_error(message)
            ),
        )

    def _shipped(self, _result: object) -> None:
        self.changed = True
        self.context.audit("order_ship", f"order id={self.order.get('id')}")
        self.context.data_changed.emit()
        self.accept()

    def _cancel_order(self) -> None:
        order_id = int(self.order["id"])
        if not widgets.confirm(
            self, "لغو سفارش",
            f"سفارش {to_persian_digits(order_id)} لغو شود؟ این کار برگشت ندارد.\n"
            "سفارش فقط در برنامهٔ فروشگاه لغو می‌شود؛ در حسابداری چیزی پاک نمی‌شود.",
            confirm_text="بله، لغو کن", kind="warning",
        ):
            return
        self.cancel_button.setEnabled(False)
        run_async(
            lambda: self.context.api.cancel_order(order_id),
            on_success=self._cancelled,
            on_error=lambda message, kind: (
                self.cancel_button.setEnabled(True), self._failed(message, kind)
            ),
        )

    def _cancelled(self, _result: object) -> None:
        self.changed = True
        self.context.audit("order_cancel", f"order id={self.order.get('id')}")
        self.context.data_changed.emit()
        self.accept()

    def _show_receipt(self) -> None:
        order_id = int(self.order["id"])
        self.receipt_button.setEnabled(False)
        run_async(
            lambda: self.context.api.receipt_image(order_id),
            on_success=self._got_receipt,
            on_error=lambda message, _kind: self._show_error(message),
            on_done=lambda: self.receipt_button.setEnabled(True),
        )

    def _got_receipt(self, data: object) -> None:
        pixmap = QPixmap()
        if not isinstance(data, (bytes, bytearray)) or not pixmap.loadFromData(bytes(data)):
            self._show_error("تصویر رسید پیدا نشد یا قابل نمایش نیست.")
            return
        ReceiptImageDialog(pixmap, to_persian_digits(self.order.get("id", "")), self).exec()


#: Paid orders that may be marked as shipped (server: SHIPPABLE_STATUSES).
SHIPPABLE = (ORDER_APPROVED, ORDER_WRITTEN)
#: v2.7.0: orders staff may cancel (server: STAFF_CANCELLABLE).
CANCELLABLE = (ORDER_AWAITING_PAYMENT, ORDER_RECEIPT_UPLOADED)


class AssignDialog(widgets.ResponsiveDialog):
    """«ارجاع به همکار»: pick the colleague (only their display names are shown)."""

    def __init__(self, context: AppContext, parent: QWidget | None, what: str) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox

        self.staff_id: Optional[int] = None
        self.setWindowTitle(f"ارجاع {what}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label(f"ارجاع {what}", size=14, bold=True))
        root.addWidget(widgets.label(
            "همکار انتخاب‌شده کار را ادامه می‌دهد و کارهای انجام‌شده را می‌بیند. "
            "این ارجاع در گزارش فعالیت ثبت می‌شود.", name="Muted", wrap=True))
        self.combo = QComboBox()
        self.combo.setMinimumHeight(40)
        self.combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root.addWidget(self.combo)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = widgets.button("ارجاع بده", variant="primary", icon_name="check",
                                        on_click=self._accept)
        self.ok_button.setEnabled(False)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        root.addLayout(buttons)
        run_async(context.api.list_assignees, on_success=self._fill,
                  on_error=lambda message, _k: self._error(message))

    def _fill(self, rows) -> None:
        self.combo.clear()
        for row in rows or []:
            self.combo.addItem(str(row.get("name") or ""), int(row["id"]))
        self.ok_button.setEnabled(self.combo.count() > 0)
        if not self.combo.count():
            self._error("همکار دیگری برای ارجاع نیست.")

    def _error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept(self) -> None:
        self.staff_id = self.combo.currentData()
        self.accept()


def courier_text(order: dict) -> str:
    name = str(order.get("courier_name") or "").strip()
    phone = to_persian_digits(str(order.get("courier_phone") or "").strip())
    return " — ".join(p for p in (name, phone) if p) or "—"


class ShipDialog(widgets.ResponsiveDialog):
    """«ارسال شد» with an OPTIONAL courier: when filled, the customer's message
    names them; when empty, the usual «sent» message only."""

    def __init__(self, parent: QWidget | None, order_label: str) -> None:
        super().__init__(parent)
        self.courier_name = ""
        self.courier_phone = ""
        self.setWindowTitle(f"ارسال سفارش {order_label}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label(f"سفارش {order_label} ارسال شد", size=14, bold=True))
        root.addWidget(widgets.label(
            "اگر پیک یا باربری دارد، نام و تلفن او را بنویسید تا در پیام «ارسال شد» به مشتری "
            "گفته شود. اگر خالی بماند، فقط پیام «ارسال شد» فرستاده می‌شود.",
            name="Muted", wrap=True))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("نام پیک (اختیاری)")
        self.name_input.setMaxLength(60)
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("تلفن پیک (اختیاری)، مثلاً ۰۹۱۲۳۴۵۶۷۸۹")
        self.phone_input.setMaxLength(30)
        for caption, field in (("نام پیک", self.name_input), ("تلفن پیک", self.phone_input)):
            root.addWidget(widgets.label(caption))
            field.setMinimumHeight(40)
            root.addWidget(field)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = widgets.button("ثبت «ارسال شد»", variant="primary", icon_name="check",
                                        on_click=self._accept)
        self.ok_button.setProperty("big", True)
        buttons.addWidget(self.ok_button)
        cancel = widgets.button("انصراف", on_click=self.reject)
        cancel.setProperty("big", True)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _accept(self) -> None:
        from ...persian import to_english_digits

        phone = "".join(ch for ch in to_english_digits(self.phone_input.text()) if ch.isdigit())
        if self.phone_input.text().strip() and not 7 <= len(phone) <= 15:
            self.error_label.setText("شمارهٔ تلفن پیک درست نیست. فقط رقم بنویسید، مثلاً "
                                     "۰۹۱۲۳۴۵۶۷۸۹؛ یا آن را خالی بگذارید.")
            self.error_label.setVisible(True)
            return
        self.courier_name = " ".join(self.name_input.text().split())
        self.courier_phone = phone
        self.accept()


def customer_label(order: dict) -> str:
    """v2.6.0: the person's name in «سازه حساب» + the person code; before the
    customer is linked (or without the name grant) the registration name."""
    code = order.get("user_person_code")
    name = str(order.get("person_name") or order.get("user_name") or "").strip()
    if code is not None:
        code_fa = to_persian_digits(code)
        return f"{name} (کد شخص {code_fa})" if name else f"کد شخص {code_fa}"
    if name:
        return name
    return f"مشتری #{to_persian_digits(order.get('user_id', '—'))}"


def receipt_ref_text(order: dict, receipt_ref: str) -> str:
    """v2.6.0: a receipt image without a typed tracking number is not «no receipt»."""
    if receipt_ref:
        return to_persian_digits(receipt_ref)
    if order.get("has_receipt"):
        return "شمارهٔ پیگیری وارد نشده"
    return "رسیدی نیامده است"


CANCEL_REASON_FA = {"customer": "لغو توسط مشتری (پیش از ارسال رسید)",
                    "receipt_timeout": "لغو خودکار (رسید در مهلت نرسید)"}


def tracking_fa(order: dict) -> str:
    """The furthest step after payment: shipped > invoiced > partially invoiced;
    for a cancelled order, who cancelled it (v2.6.2)."""
    if order.get("status") == "cancelled" and order.get("cancel_reason") in CANCEL_REASON_FA:
        return CANCEL_REASON_FA[order["cancel_reason"]]
    if order.get("shipped_at"):
        return f"ارسال شده ({format_shamsi(order.get('shipped_at'))})"
    if order.get("invoice_state") == "full":
        return "فاکتور شده"
    if order.get("invoice_state") == "partial":
        return "بخشی فاکتور شده"
    return "—"


class ReceiptImageDialog(widgets.ResponsiveDialog):
    """تصویر رسید پرداخت که مشتری در بله فرستاده است."""

    def __init__(self, pixmap: QPixmap, order_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"رسید سفارش {order_label}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(640, 760)
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setPixmap(pixmap.scaledToWidth(
            min(pixmap.width(), 600), Qt.TransformationMode.SmoothTransformation
        ))
        scroll.setWidget(image)
        root.addWidget(scroll, 1)
        close = widgets.button("بستن", on_click=self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


def _kv(key: str, value: str) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(widgets.label(f"{key}:", name="Muted"))
    layout.addWidget(widgets.label(value, bold=True))
    layout.addStretch(1)
    return holder


class RejectPaymentDialog(widgets.ResponsiveDialog):
    def __init__(self, parent: QWidget | None, order_label: str) -> None:
        super().__init__(parent)
        self.reason = ""
        self.setWindowTitle("رد پرداخت")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("رد پرداخت", size=14, bold=True))
        root.addWidget(widgets.label(
            f"آیا از رد کردن پرداخت سفارش شمارهٔ {order_label} مطمئن هستید؟", wrap=True
        ))
        root.addWidget(widgets.label("دلیل (اختیاری):", name="Muted"))
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("مثلاً: مبلغ رسید با مبلغ سفارش یکی نیست")
        self.reason_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root.addWidget(self.reason_input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = widgets.button("رد پرداخت", variant="danger", on_click=self._submit)
        cancel = widgets.button("انصراف", on_click=self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _submit(self) -> None:
        self.reason = self.reason_input.text().strip()
        self.accept()
