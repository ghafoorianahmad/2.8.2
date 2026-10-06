"""صفحهٔ مشتریان — مدیریت حساب‌های مشتریان (نه کاربران سیستم).

مشتریان در shopapi نگهداری می‌شوند و این صفحه فقط از طریق API آن‌ها را می‌خواند.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...api_client import ApiError
from ...logging_setup import mask_phone
from ...permissions import CUSTOMERS_APPROVE, CUSTOMERS_REJECT
from ...persian import format_shamsi, normalize_fa, to_english_digits, to_persian_digits
from ...statuses import (
    CUSTOMER_APPROVED,
    CUSTOMER_PENDING,
    CUSTOMER_REJECTED,
    customer_status_fa,
    platform_fa,
)
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..context import AppContext

HEADERS = ("نام مشتری", "پلتفرم", "شماره موبایل", "کد شخص", "وضعیت", "تاریخ ثبت", "عملیات")

TABS = (
    ("all", "همه", None),
    ("pending", "در انتظار", CUSTOMER_PENDING),
    ("approved", "تأیید شده", CUSTOMER_APPROVED),
    ("rejected", "رد شده", CUSTOMER_REJECTED),
)


class CustomersPage(BasePage):
    title = "مشتریان"
    subtitle = "مشتریانی که از طریق ربات‌ها و وب‌سایت ثبت‌نام کرده‌اند"

    def build_body(self) -> None:
        # ---- filter tabs + search ---------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._tab_buttons: dict[str, object] = {}
        self._active_tab = "all"
        for key, label_text, _status in TABS:
            tab = widgets.button(label_text, variant="ghost")
            tab.setObjectName("Tab")
            tab.setCheckable(True)
            tab.setChecked(key == self._active_tab)
            tab.clicked.connect(lambda _checked=False, k=key: self._select_tab(k))
            self._tab_buttons[key] = tab
            bar.addWidget(tab)
        bar.addStretch(1)

        self.search = widgets.SearchBox("جستجو بر اساس نام یا شماره موبایل…")
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search)
        self.body.addLayout(bar)

        # ---- table -------------------------------------------------------
        panel = widgets.Panel()
        self.table = widgets.DataTable(HEADERS)
        self.table.set_empty_state(
            "هیچ مشتری‌ای در این وضعیت وجود ندارد",
            "با تغییر زبانه‌های بالا یا پاک کردن جستجو، نتیجهٔ دیگری ببینید.",
            "customers",
        )
        self.table.setMinimumHeight(360)
        panel.body.addWidget(self.table, 1)

        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)

        self._customers: list[dict] = []

    # ------------------------------------------------------------------ state
    def _select_tab(self, key: str) -> None:
        self._active_tab = key
        for tab_key, widget in self._tab_buttons.items():
            widget.setChecked(tab_key == key)
        self.load()

    def set_filter(self, key: str) -> None:
        """Called by the dashboard cards to deep-link into a tab."""
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
            lambda: self.context.api.list_customers(status),
            on_success=self._on_loaded,
            on_error=self._on_error,
        )

    def _on_error(self, message: str, kind: str) -> None:
        self._customers = []
        self.table.fill([])
        self.show_table_error(message)
        self.default_error(message, kind)

    def _on_loaded(self, customers: list) -> None:
        self._customers = list(customers or [])
        self.table.set_busy(False)
        self._render()

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        needle = normalize_fa(self.search.text())
        rows = [c for c in self._customers if _matches(c, needle)]

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for customer in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, str(customer.get("name") or "—"), bold=True)
                self.table.set_cell(row, 1, platform_fa(customer.get("platform")))
                self.table.set_cell(row, 2, to_persian_digits(mask_phone(customer.get("phone"))))
                code = customer.get("person_code")
                self.table.set_cell(
                    row, 3, to_persian_digits(code) if code else "—"
                )
                self.table.set_widget(row, 4, widgets.pill_cell(
                    widgets.StatusPill(
                        customer_status_fa(customer.get("status")), customer.get("status")
                    )
                ))
                self.table.set_cell(row, 5, format_shamsi(customer.get("created_at")))
                self.table.set_widget(row, 6, self._actions_for(customer))
        finally:
            self.table.setUpdatesEnabled(True)

        if not rows:
            if needle:
                self.table.set_empty_state(
                    "مشتری‌ای با این جستجو پیدا نشد",
                    "املای نام یا شمارهٔ موبایل را بررسی کنید.",
                    "search",
                )
            else:
                self.table.set_empty_state(
                    "هیچ مشتری‌ای در این وضعیت وجود ندارد",
                    "با تغییر زبانه‌های بالا نتیجهٔ دیگری ببینید.",
                    "customers",
                )
        self.table._refresh_states()
        self.summary.setText(
            f"{to_persian_digits(len(rows))} مشتری از "
            f"{to_persian_digits(len(self._customers))} مشتری بارگذاری‌شده"
        )

    def _actions_for(self, customer: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        is_pending = customer.get("status") == CUSTOMER_PENDING
        can_approve = self.context.can(CUSTOMERS_APPROVE)
        can_reject = self.context.can(CUSTOMERS_REJECT)

        approve = widgets.button("تأیید", variant="success", on_click=lambda c=customer: self._approve(c))
        approve.setEnabled(is_pending and can_approve)
        if is_pending and not can_approve:
            approve.setToolTip("نقش شما اجازهٔ تأیید مشتری را ندارد")
        layout.addWidget(approve)

        reject = widgets.button("رد", variant="danger", on_click=lambda c=customer: self._reject(c))
        reject.setEnabled(is_pending and can_reject)
        if is_pending and not can_reject:
            reject.setToolTip("نقش شما اجازهٔ رد کردن مشتری را ندارد")
        layout.addWidget(reject)
        layout.addStretch(1)
        return holder

    # ------------------------------------------------------------------ actions
    def _approve(self, customer: dict) -> None:
        dialog = ApproveCustomerDialog(self.context, customer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        person_code = dialog.person_code
        if person_code is None:
            return

        self.table.set_busy(True, "در حال تأیید مشتری…")
        run_async(
            lambda: self.context.api.approve_customer(int(customer["id"]), int(person_code)),
            on_success=lambda result: self._approved(customer, result),
            on_error=self._approve_failed,
            on_done=lambda: self.table.set_busy(False),
        )

    def _approved(self, customer: dict, _result: object) -> None:
        name = str(customer.get("name") or "")
        self.context.audit("customer_approve", f"customer id={customer.get('id')}")
        self.notify_success(f"مشتری «{name}» با موفقیت تأیید شد")
        self.context.data_changed.emit()
        self.load()

    def _approve_failed(self, message: str, kind: str) -> None:
        widgets.error(self, "تأیید مشتری انجام نشد", message)
        if kind in ("connection", "timeout"):
            self.context.mark_offline()

    def _reject(self, customer: dict) -> None:
        name = str(customer.get("name") or "")
        dialog = RejectCustomerDialog(self, name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reason = dialog.reason
        self.table.set_busy(True, "در حال رد کردن مشتری…")
        run_async(
            lambda: self.context.api.reject_customer(int(customer["id"]), reason),
            on_success=lambda _r: self._rejected(customer),
            on_error=self._reject_failed,
            on_done=lambda: self.table.set_busy(False),
        )

    def _rejected(self, customer: dict) -> None:
        name = str(customer.get("name") or "")
        self.context.audit("customer_reject", f"customer id={customer.get('id')}")
        self.notify_success(f"مشتری «{name}» رد شد")
        self.context.data_changed.emit()
        self.load()

    def _reject_failed(self, message: str, kind: str) -> None:
        widgets.error(self, "رد کردن مشتری انجام نشد", message)
        if kind in ("connection", "timeout"):
            self.context.mark_offline()


def _matches(customer: dict, needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        normalize_fa(customer.get(field, "")) for field in ("name", "phone", "chat_id")
    )
    return needle in haystack


# --------------------------------------------------------------------------
# dialogs
# --------------------------------------------------------------------------
class ApproveCustomerDialog(QDialog):
    """تأیید مشتری: نمایش اطلاعات، ورود کد شخص و پیشنهاد تطبیق با موبایل."""

    def __init__(self, context: AppContext, customer: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.customer = customer
        self.person_code: Optional[int] = None

        self.setWindowTitle("تأیید مشتری")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(widgets.label("تأیید مشتری", size=14, bold=True))
        root.addWidget(widgets.label(
            "برای تأیید، کد شخص مشتری در نرم‌افزار حسابداری را وارد کنید.",
            name="Muted", wrap=True,
        ))

        info = widgets.Panel("اطلاعات مشتری")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow(widgets.label("نام مشتری"), widgets.label(str(customer.get("name") or "—"), bold=True))
        form.addRow(widgets.label("پلتفرم"), widgets.label(platform_fa(customer.get("platform"))))
        form.addRow(
            widgets.label("شماره موبایل"),
            widgets.label(to_persian_digits(mask_phone(customer.get("phone")))),
        )
        form.addRow(widgets.label("تاریخ ثبت"), widgets.label(format_shamsi(customer.get("created_at"))))
        form.addRow(widgets.label("وضعیت"), widgets.label(customer_status_fa(customer.get("status"))))
        info.body.addLayout(form)
        root.addWidget(info)

        code_panel = widgets.Panel("کد شخص در حسابداری")
        code_row = QHBoxLayout()
        code_row.setSpacing(10)
        self.code_input = QSpinBox()
        self.code_input.setRange(0, 2_000_000_000)
        self.code_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_input.setMinimumWidth(180)
        self.code_input.setSpecialValueText("—")
        code_row.addWidget(self.code_input)
        code_row.addStretch(1)
        code_panel.body.addLayout(code_row)

        self.suggestion_label = widgets.label(
            "در حال بررسی تطبیق شمارهٔ موبایل با حسابداری…", name="Muted", wrap=True
        )
        code_panel.body.addWidget(self.suggestion_label)

        self.use_suggestion = widgets.button(
            "استفاده از این کد", icon_name="check", on_click=self._apply_suggestion
        )
        self.use_suggestion.setVisible(False)
        suggestion_row = QHBoxLayout()
        suggestion_row.addWidget(self.use_suggestion)
        suggestion_row.addStretch(1)
        code_panel.body.addLayout(suggestion_row)
        root.addWidget(code_panel)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.confirm_button = widgets.button("تأیید مشتری", variant="primary", on_click=self._submit)
        cancel = widgets.button("انصراف", on_click=self.reject)
        buttons.addWidget(self.confirm_button)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self._suggested_code: Optional[int] = None
        self._suggested_name = ""
        QTimer.singleShot(0, self._fetch_suggestion)

    # ---- suggestion ------------------------------------------------------
    def _fetch_suggestion(self) -> None:
        phone = str(self.customer.get("phone") or "")
        if not phone:
            self._no_suggestion("شمارهٔ موبایلی برای تطبیق ثبت نشده است.")
            return
        run_async(
            lambda: self.context.api.match_person(to_english_digits(phone)),
            on_success=self._got_suggestion,
            on_error=self._suggestion_failed,
        )

    def _got_suggestion(self, result: object) -> None:
        if not isinstance(result, dict) or not result.get("code"):
            self._no_suggestion("شخصی با این شمارهٔ موبایل در حسابداری پیدا نشد.")
            return
        self._suggested_code = int(result["code"])
        self._suggested_name = str(result.get("masked_name") or "")
        text = f"پیشنهاد حسابداری: کد شخص {to_persian_digits(self._suggested_code)}"
        if self._suggested_name:
            text += f" ({self._suggested_name})"
        self.suggestion_label.setText(text)
        self.suggestion_label.setStyleSheet(f"color: {theme.SUCCESS_DARK};")
        self.use_suggestion.setVisible(True)
        # Pre-fill so the common case is one click.
        self.code_input.setValue(self._suggested_code)

    def _no_suggestion(self, message: str) -> None:
        self.suggestion_label.setText(message)
        self.suggestion_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.use_suggestion.setVisible(False)

    def _suggestion_failed(self, message: str, _kind: str) -> None:
        self._no_suggestion(f"بررسی تطبیق انجام نشد: {message}")

    def _apply_suggestion(self) -> None:
        if self._suggested_code is not None:
            self.code_input.setValue(self._suggested_code)

    # ---- submit ----------------------------------------------------------
    def _submit(self) -> None:
        code = int(self.code_input.value())
        if code <= 0:
            self.error_label.setText("کد شخص را وارد کنید (عدد بزرگ‌تر از صفر).")
            self.error_label.setVisible(True)
            self.code_input.setProperty("error", "true")
            self.code_input.style().unpolish(self.code_input)
            self.code_input.style().polish(self.code_input)
            return
        self.person_code = code
        self.accept()


class RejectCustomerDialog(QDialog):
    """رد مشتری همراه با دلیل اختیاری."""

    def __init__(self, parent: QWidget | None, customer_name: str) -> None:
        super().__init__(parent)
        self.reason = ""
        self.setWindowTitle("رد مشتری")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("رد مشتری", size=14, bold=True))
        root.addWidget(widgets.label(
            f"آیا از رد کردن مشتری «{customer_name}» مطمئن هستید؟", wrap=True
        ))
        root.addWidget(widgets.label("دلیل (اختیاری):", name="Muted"))
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("مثلاً: اطلاعات ناقص است")
        self.reason_input.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root.addWidget(self.reason_input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm = widgets.button("رد کردن", variant="danger", on_click=self._submit)
        cancel = widgets.button("انصراف", on_click=self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _submit(self) -> None:
        self.reason = self.reason_input.text().strip()
        self.accept()
