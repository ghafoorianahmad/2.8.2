"""صفحهٔ مشتریان — مدیریت حساب‌های مشتریان (نه کاربران سیستم).

مشتریان در shopapi نگهداری می‌شوند و این صفحه فقط از طریق API آن‌ها را می‌خواند.
"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...api_client import ApiError
from ...logging_setup import mask_phone
from ...permissions import CUSTOMERS_APPROVE, CUSTOMERS_REJECT
from ...persian import format_phone, format_shamsi, normalize_fa, to_english_digits, to_persian_digits
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
from ..rtl import RIGHT, mark_ltr

HEADERS = ("نام مشتری", "پلتفرم", "شماره موبایل", "کد شخص", "وضعیت", "تاریخ ثبت", "عملیات")

TABS = (
    ("all", "همهٔ مشتریان", None),
    ("pending", "در انتظار", CUSTOMER_PENDING),
    ("approved", "تأیید شده", CUSTOMER_APPROVED),
    ("rejected", "رد شده", CUSTOMER_REJECTED),
)


class CustomersPage(BasePage):
    title = "مشتریان"
    subtitle = "مشتریانی که از طریق ربات‌ها و وب‌سایت ثبت‌نام کرده‌اند"
    help_text = "مشتریانی که در ربات ثبت‌نام کرده‌اند. برای دیدن جزئیات هر مشتری روی ردیفش کلیک کنید."

    def build_body(self) -> None:
        # ---- filter tabs + search ---------------------------------------
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
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

        self.search = widgets.SearchBox("جستجو بر اساس نام یا شماره موبایل…")
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search)
        self.body.addWidget(bar_holder)

        # ---- table -------------------------------------------------------
        panel = widgets.Panel()
        self.table = widgets.DataTable(HEADERS, key="customers")
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
                self.table.set_cell(row, 2, format_phone(mask_phone(customer.get("phone"))))
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
        if not is_pending:
            # v2.6.0: a decided customer has no Approve/Reject buttons at all
            # (they used to stay visible and looked clickable).
            layout.addWidget(widgets.label("تصمیم گرفته شده", name="Muted"))
            layout.addStretch(1)
            return holder
        can_approve = self.context.can(CUSTOMERS_APPROVE)
        can_reject = self.context.can(CUSTOMERS_REJECT)

        approve = widgets.button("تأیید", variant="success", on_click=lambda c=customer: self._approve(c))
        approve.setEnabled(can_approve)
        approve.setVisible(can_approve)
        layout.addWidget(approve)

        reject = widgets.button("رد", variant="danger", on_click=lambda c=customer: self._reject(c))
        reject.setEnabled(can_reject)
        reject.setVisible(can_reject)
        layout.addWidget(reject)
        if not (can_approve or can_reject):
            layout.addWidget(widgets.label("در انتظار تأیید مدیر", name="Muted"))
        layout.addStretch(1)
        return holder

    # ------------------------------------------------------------------ actions
    def _approve(self, customer: dict) -> None:
        if customer.get("status") != CUSTOMER_PENDING:
            return
        dialog = ApproveCustomerDialog(self.context, customer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        person_code = dialog.person_code
        first_name, last_name = dialog.first_name, dialog.last_name
        if person_code is None and not last_name:
            return

        busy = "در حال تأیید مشتری…" if person_code else "در حال ساخت شخص در حسابداری…"
        self.table.set_busy(True, busy)
        run_async(
            lambda: self.context.api.approve_customer(
                int(customer["id"]), person_code, first_name=first_name, last_name=last_name
            ),
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
        if customer.get("status") != CUSTOMER_PENDING:
            return
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


#: Letters (any script), spaces, ZWNJ, hyphen, dot and apostrophe: Bale profile
#: names may hold emoji or symbols that must not reach the accounting software.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ \u200c\-.'][^\W\d_]+)*$")
MAX_NAME_PART = 50


def split_name(full_name: str) -> tuple[str, str]:
    """A suggestion for (first, last) from a profile name; symbols removed."""
    words = [w for w in re.split(r"\s+", str(full_name or "")) if w]
    words = ["".join(ch for ch in w if ch.isalpha() or ch in "\u200c-.'") for w in words]
    words = [w for w in words if w]
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""
    return words[0], " ".join(words[1:])


def name_problem(first: str, last: str) -> str:
    """'' when the name may be written to the accounting software."""
    if not last:
        return "نام خانوادگی را وارد کنید."
    for part in (first, last):
        if part and (len(part) > MAX_NAME_PART or not _NAME_RE.match(part)):
            return "نام فقط می‌تواند حروف، فاصله و نیم‌فاصله داشته باشد (بدون شکلک، عدد یا نماد)."
    return ""


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
class ApproveCustomerDialog(widgets.ResponsiveDialog):
    """تأیید مشتری: اتصال به شخص موجود (کد شخص، با پیشنهاد تطبیق موبایل) یا
    ساخت شخص جدید در حسابداری با نامی که اینجا اصلاح می‌شود."""

    def __init__(self, context: AppContext, customer: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.customer = customer
        self.person_code: Optional[int] = None
        self.first_name = ""
        self.last_name = ""

        self.setWindowTitle("تأیید مشتری")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(widgets.label("تأیید مشتری", size=14, bold=True))
        root.addWidget(widgets.label(
            "مشتری را به شخص موجود در حسابداری وصل کنید، یا اگر در حسابداری نیست، "
            "شخص جدید بسازید.",
            name="Muted", wrap=True,
        ))

        info = widgets.Panel("اطلاعات مشتری")
        form = QFormLayout()
        form.setLabelAlignment(RIGHT)
        form.setFormAlignment(RIGHT | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow(widgets.label("نام مشتری"), widgets.label(str(customer.get("name") or "—"), bold=True))
        form.addRow(widgets.label("پلتفرم"), widgets.label(platform_fa(customer.get("platform"))))
        form.addRow(
            widgets.label("شماره موبایل"),
            widgets.label(format_phone(mask_phone(customer.get("phone")))),
        )
        form.addRow(widgets.label("تاریخ ثبت"), widgets.label(format_shamsi(customer.get("created_at"))))
        form.addRow(widgets.label("وضعیت"), widgets.label(customer_status_fa(customer.get("status"))))
        info.body.addLayout(form)
        root.addWidget(info)

        mode_row = QHBoxLayout()
        self.mode_link = QRadioButton("اتصال به شخص موجود")
        self.mode_create = QRadioButton("ساخت شخص جدید در حسابداری")
        self._modes = QButtonGroup(self)
        self._modes.addButton(self.mode_link)
        self._modes.addButton(self.mode_create)
        self.mode_link.setChecked(True)
        mode_row.addWidget(self.mode_link)
        mode_row.addWidget(self.mode_create)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        code_panel = widgets.Panel("کد شخص در حسابداری")
        self.code_panel = code_panel
        code_row = QHBoxLayout()
        code_row.setSpacing(10)
        self.code_input = QSpinBox()
        self.code_input.setRange(0, 2_000_000_000)
        mark_ltr(self.code_input)
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

        # New person: the Bale profile name is only a suggestion; staff fix it
        # (it may be a nickname or emoji) before it is written to accounting.
        self.create_panel = widgets.Panel("نام شخص جدید در حسابداری")
        first, last = split_name(str(customer.get("name") or ""))
        name_form = QFormLayout()
        name_form.setLabelAlignment(RIGHT)
        self.first_name_input = QLineEdit(first)
        self.first_name_input.setMaxLength(MAX_NAME_PART)
        self.last_name_input = QLineEdit(last)
        self.last_name_input.setMaxLength(MAX_NAME_PART)
        name_form.addRow(widgets.label("نام"), self.first_name_input)
        name_form.addRow(widgets.label("نام خانوادگی"), self.last_name_input)
        self.create_panel.body.addLayout(name_form)
        self.create_panel.body.addWidget(widgets.label(
            "شخص با همین نام و شمارهٔ موبایل تأییدشدهٔ مشتری در حسابداری ساخته می‌شود. "
            "اگر شماره قبلاً در حسابداری باشد، به همان شخص وصل می‌شود.",
            name="Muted", wrap=True,
        ))
        root.addWidget(self.create_panel)
        self.mode_link.toggled.connect(self._mode_changed)

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
        self._mode_changed()
        QTimer.singleShot(0, self._fetch_suggestion)

    @property
    def creating(self) -> bool:
        return self.mode_create.isChecked()

    def _mode_changed(self, *_args) -> None:
        self.code_panel.setVisible(not self.creating)
        self.create_panel.setVisible(self.creating)
        self.confirm_button.setText("ساخت شخص و تأیید" if self.creating else "تأیید مشتری")
        self.error_label.setVisible(False)

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
        # nobody in accounting has this mobile: a new person is the usual case
        if not self.code_input.value():
            self.mode_create.setChecked(True)

    def _suggestion_failed(self, message: str, _kind: str) -> None:
        self._no_suggestion(f"بررسی تطبیق انجام نشد: {message}")

    def _apply_suggestion(self) -> None:
        if self._suggested_code is not None:
            self.code_input.setValue(self._suggested_code)

    # ---- submit ----------------------------------------------------------
    def _show_error(self, message: str, widget: QWidget) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        widget.setProperty("error", "true")
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _submit(self) -> None:
        if self.creating:
            first = " ".join(self.first_name_input.text().split())
            last = " ".join(self.last_name_input.text().split())
            problem = name_problem(first, last)
            if problem:
                self._show_error(problem, self.last_name_input)
                return
            self.person_code = None
            self.first_name, self.last_name = first, last
            self.accept()
            return
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


class RejectCustomerDialog(widgets.ResponsiveDialog):
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
