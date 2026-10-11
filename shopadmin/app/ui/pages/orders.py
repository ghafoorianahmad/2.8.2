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

from ...permissions import ORDERS_APPROVE_PAYMENT, ORDERS_REJECT_PAYMENT, ORDERS_SHIP
from ...persian import (
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

HEADERS = ("شماره سفارش", "نام مشتری", "تعداد اقلام", "مبلغ کل", "وضعیت", "مهلت پرداخت", "تاریخ ثبت")

TABS = (
    ("awaiting_payment", "در انتظار پرداخت", ORDER_AWAITING_PAYMENT),
    ("receipt_uploaded", "فیش ارسال‌شده", ORDER_RECEIPT_UPLOADED),
    ("approved", "تأییدشده", ORDER_APPROVED),
    ("rejected", "ردشده", ORDER_REJECTED),
    ("expired", "منقضی", ORDER_EXPIRED),
    ("written", "نوشته‌شده در حسابداری", ORDER_WRITTEN),
)

EMPTY_HINTS = {
    "awaiting_payment": "سفارش‌هایی که در انتظار واریز مبلغ توسط مشتری هستند اینجا نمایش داده می‌شوند.",
    "receipt_uploaded": "به‌محض ارسال فیش توسط مشتری، سفارش در این زبانه قرار می‌گیرد.",
    "approved": "سفارش‌های تأییدشده در این زبانه دیده می‌شوند.",
    "rejected": "سفارش‌هایی که پرداختشان رد شده است اینجا نمایش داده می‌شوند.",
    "expired": "سفارش‌هایی که مهلت پرداختشان تمام شده است.",
    "written": "سفارش‌هایی که در نرم‌افزار حسابداری ثبت شده‌اند.",
}


class OrdersPage(BasePage):
    title = "سفارش‌ها"
    subtitle = "بررسی فیش‌های پرداخت و تأیید سفارش‌ها"

    def build_body(self) -> None:
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

        self.search = widgets.SearchBox("جستجو بر اساس نام مشتری یا شمارهٔ سفارش…")
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search)
        self.body.addWidget(bar_holder)

        panel = widgets.Panel()
        hint = widgets.label(
            "برای دیدن اقلام سفارش و تأیید یا رد پرداخت، روی ردیف مورد نظر کلیک کنید.",
            name="Muted", wrap=True,
        )
        panel.body.addWidget(hint)

        self.table = widgets.DataTable(HEADERS, selectable_rows=True, key="orders")
        self.table.set_empty_state("هیچ سفارشی در این وضعیت وجود ندارد", "", "orders")
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
        self.run(
            lambda: self.context.api.list_orders(status),
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
                self.table.set_cell(row, 5, format_shamsi(order.get("reserve_until")) if order.get("reserve_until") else "—")
                self.table.set_cell(row, 6, format_shamsi(order.get("created_at")))
        finally:
            self.table.setUpdatesEnabled(True)

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
                    f"هیچ سفارشی در وضعیت «{status_fa}» وجود ندارد",
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
        name = order.get("user_name")
        if name:
            return str(name)
        return f"مشتری #{to_persian_digits(order.get('user_id', '—'))}"

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


class OrderDetailDialog(QDialog):
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
        left.addWidget(_kv("تاریخ ثبت", format_shamsi(order.get("created_at"))))
        left.addWidget(_kv("مهلت پرداخت", format_shamsi(order.get("reserve_until"))
                           if order.get("reserve_until") else "—"))
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(_kv("مبلغ کل", format_money(order.get("total", 0))))
        right.addWidget(_kv("سطح قیمت", price_level_label(order.get("price_level", 0))))
        right.addWidget(_kv("شمارهٔ حسابداری", to_persian_digits(order.get("accounting_order_no"))
                            if order.get("accounting_order_no") else "—"))
        right.addWidget(_kv("پیگیری", tracking_fa(order)))
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
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.items_table.setItem(index, column, cell)
        items_panel.body.addWidget(self.items_table)
        items_panel.body.addWidget(widgets.label(
            f"تعداد اقلام: {to_persian_digits(len(items))} — "
            f"مبلغ کل: {format_money(order.get('total', 0))}",
            name="Muted",
        ))
        root.addWidget(items_panel, 1)

        # ---- receipt -----------------------------------------------------
        receipt_ref = order.get("receipt_ref") or self._payment_ref(order)
        ref_panel = widgets.Panel("فیش پرداخت مشتری")
        ref_row = QHBoxLayout()
        ref_row.addWidget(widgets.label("شمارهٔ پیگیری فیش:", name="Muted"))
        ref_row.addWidget(widgets.label(
            to_persian_digits(receipt_ref) if receipt_ref else "فیشی ثبت نشده است", bold=bool(receipt_ref)
        ))
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
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.approve_button = widgets.button(
            "تأیید پرداخت", variant="success", icon_name="check", on_click=self._approve
        )
        self.reject_button = widgets.button(
            "رد پرداخت", variant="danger", icon_name="close", on_click=self._reject
        )
        can_approve = context.can(ORDERS_APPROVE_PAYMENT)
        can_reject = context.can(ORDERS_REJECT_PAYMENT)
        actionable = order.get("status") == ORDER_RECEIPT_UPLOADED

        self.approve_button.setEnabled(actionable and can_approve)
        self.reject_button.setEnabled(actionable and can_reject)
        if not can_approve:
            self.approve_button.setToolTip("نقش شما اجازهٔ تأیید پرداخت را ندارد")
        if not can_reject:
            self.reject_button.setToolTip("نقش شما اجازهٔ رد پرداخت را ندارد")
        if not actionable and can_approve:
            tip = f"این سفارش در وضعیت «{order_status_fa(order.get('status'))}» است"
            self.approve_button.setToolTip(tip)
            self.reject_button.setToolTip(tip)

        self.ship_button = widgets.button(
            "ثبت ارسال", icon_name="check", on_click=self._ship
        )
        can_ship = context.can(ORDERS_SHIP)
        shippable = order.get("status") in SHIPPABLE and not order.get("shipped_at")
        self.ship_button.setEnabled(can_ship and shippable)
        if not can_ship:
            self.ship_button.setToolTip("نقش شما اجازهٔ ثبت ارسال را ندارد")
        elif order.get("shipped_at"):
            self.ship_button.setToolTip("این سفارش قبلاً ارسال شده است")
        elif not shippable:
            self.ship_button.setToolTip("فقط سفارش پرداخت‌شده و تأییدشده قابل ارسال است")

        actions.addWidget(self.approve_button)
        actions.addWidget(self.reject_button)
        actions.addWidget(self.ship_button)
        actions.addStretch(1)
        close = widgets.button("بستن", on_click=self.reject)
        actions.addWidget(close)
        root.addLayout(actions)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        self._detail_label = widgets.label("", name="Muted", wrap=True)
        self._detail_label.setVisible(False)
        root.addWidget(self._detail_label)

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _customer_label(order: dict) -> str:
        name = order.get("user_name")
        if name:
            return str(name)
        return f"مشتری #{to_persian_digits(order.get('user_id', '—'))}"

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

    # ---- actions ---------------------------------------------------------
    def _approve(self) -> None:
        order_id = int(self.order["id"])
        self.approve_button.setEnabled(False)
        self.approve_button.setText("در حال تأیید…")

        def restore() -> None:
            self.approve_button.setText("تأیید پرداخت")
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
        widgets.error(self, "تأیید پرداخت انجام نشد", message)

    def _dry_run_hint(self) -> str:
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
            self.reject_button.setText("رد پرداخت")
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
        if not widgets.confirm(
            self, "ثبت ارسال",
            f"سفارش {to_persian_digits(order_id)} ارسال شد؟ به مشتری در بله خبر داده می‌شود.",
        ):
            return
        self.ship_button.setEnabled(False)
        run_async(
            lambda: self.context.api.ship_order(order_id),
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


def tracking_fa(order: dict) -> str:
    """The furthest step after payment: shipped > invoiced > partially invoiced."""
    if order.get("shipped_at"):
        return f"ارسال شده ({format_shamsi(order.get('shipped_at'))})"
    if order.get("invoice_state") == "full":
        return "فاکتور شده"
    if order.get("invoice_state") == "partial":
        return "بخشی فاکتور شده"
    return "—"


class ReceiptImageDialog(QDialog):
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


class RejectPaymentDialog(QDialog):
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
        self.reason_input.setPlaceholderText("مثلاً: مبلغ فیش با مبلغ سفارش هم‌خوانی ندارد")
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
