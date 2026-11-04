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
from ... import validators
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

HEADERS = ("نام مشتری", "پلتفرم", "شماره موبایل", "شخص در «سازه حساب»", "وضعیت", "تاریخ ثبت",
           "عملیات")

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

        self.search = widgets.SearchBox("نام یا شماره موبایل…")
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
                # v2.18.0: the whole number: staff call it, and search by it
                self.table.set_cell(row, 2, format_phone(customer.get("phone")))
                self.table.set_cell(row, 3, person_text(customer))
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
            if self.context.can(CUSTOMERS_APPROVE):
                layout.addWidget(widgets.button("اطلاعات", icon_name="edit",
                                                on_click=lambda c=customer: self._edit_details(c)))
            else:
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
        values = dialog.values
        if person_code is None and not values:
            return

        busy = "در حال تأیید مشتری…" if person_code else "در حال ساخت شخص در حسابداری…"
        self.table.set_busy(True, busy)
        run_async(
            lambda: self.context.api.approve_customer(int(customer["id"]), person_code, **values),
            on_success=lambda result: self._approved(customer, result),
            on_error=self._approve_failed,
            on_done=lambda: self.table.set_busy(False),
        )

    def _edit_details(self, customer: dict) -> None:
        """v2.18.0: what the customer told staff; an order needs all four to be written."""
        dialog = CustomerDetailsDialog(customer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values
        run_async(
            lambda: self.context.api.put_customer_details(int(customer["id"]), **values),
            on_success=lambda _r: self._details_saved(customer),
            on_error=self._approve_failed,
        )

    def _details_saved(self, customer: dict) -> None:
        self.context.audit("customer_details", f"customer id={customer.get('id')}")
        self.notify_success("اطلاعات مشتری ثبت شد")
        self.load()

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


def person_text(customer: dict) -> str:
    """v2.18.0: the linked person as «سازه حساب» has it: name and code."""
    code = customer.get("person_code")
    if not code:
        return "—"
    name = str(customer.get("person_name") or "").strip()
    code_fa = to_persian_digits(code)
    return f"{name} (کد {code_fa})" if name else f"کد {code_fa}"


#: v2.18.0: names are Persian letters only (validators.py = the form's own rules): Bale
#: profile names may hold emoji or Latin that must not reach the accounting software.
MAX_NAME_PART = validators.MAX_NAME


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
    for check in (validators.validate_first_name(first), validators.validate_last_name(last)):
        if not check.valid:
            return check.error
    return ""


class CustomerFields(QWidget):
    """The four details, the same in the approval dialog and in «اطلاعات»."""

    FIELDS = (("first_name", "نام"), ("last_name", "نام خانوادگی"),
              ("national_code", "کد ملی (یا شناسهٔ ۱۱ رقمی اتباع)"), ("address", "نشانی"))

    def __init__(self, customer: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        first, last = split_name(str(customer.get("name") or ""))
        # what the customer typed in the bot beats the guess from the profile
        known = {"first_name": str(customer.get("first_name") or first),
                 "last_name": str(customer.get("last_name") or last),
                 "national_code": str(customer.get("national_code") or ""),
                 "address": str(customer.get("address") or "")}
        self.inputs: dict[str, QLineEdit] = {}
        # v2.18.1: without the tick the server sends a masked code and no address, and refuses
        # both if sent: they stay out of this form and out of its checks
        hidden = bool(customer.get("private_hidden"))
        self.locked = ("national_code", "address") if hidden else ()
        on_file = {"national_code": customer.get("national_code_on_file"),
                   "address": customer.get("address_on_file")}
        for field, caption in self.FIELDS:
            box = QLineEdit(known[field])
            if field == "national_code":
                box.setText(to_persian_digits(known[field]))
            if field in self.locked:
                box.setEnabled(False)
                box.setText(to_persian_digits(known[field]) if on_file[field]
                            and known[field] else "ثبت شده (بدون دسترسی دیدن)"
                            if on_file[field] else "مشتری باید در ربات بنویسد")
            self.inputs[field] = box
            form.addRow(widgets.label(caption), box)

    def problem(self, *, required: bool) -> tuple[str, QWidget | None]:
        """The first broken rule (the form's own words) and its box."""
        for field, box in self.inputs.items():
            if field in self.locked:
                continue
            text = box.text()
            if not required and not text.strip():
                continue
            check = validators.VALIDATORS[field](text)
            if not check.valid:
                return check.error, box
        return "", None

    def values(self) -> dict:
        """{field: clean value} of the filled ones."""
        out = {}
        for field, box in self.inputs.items():
            if field in self.locked:
                continue
            check = validators.VALIDATORS[field](box.text())
            if box.text().strip() and check.valid:
                out[field] = check.normalized
        return out


def _matches(customer: dict, needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        normalize_fa(customer.get(field) or "")
        for field in ("name", "phone", "chat_id", "person_name", "first_name", "last_name")
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
        self.values: dict = {}

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
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(RIGHT | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow(widgets.label("نام مشتری"), widgets.label(str(customer.get("name") or "—"), bold=True))
        form.addRow(widgets.label("پلتفرم"), widgets.label(platform_fa(customer.get("platform"))))
        form.addRow(
            widgets.label("شماره موبایل"),
            widgets.label(format_phone(customer.get("phone"))),
        )
        form.addRow(widgets.label("تاریخ ثبت"), widgets.label(format_shamsi(customer.get("created_at"))))
        form.addRow(widgets.label("وضعیت"), widgets.label(customer_status_fa(customer.get("status"))))
        info.body.addLayout(form)
        root.addWidget(info)

        # v2.18.0: is this somebody «سازه حساب» already knows?
        # (the answer comes from the server, so its panel is built then and put in this slot)
        self.candidates_panel: Optional[widgets.Panel] = None
        self.candidates_slot = QVBoxLayout()
        root.addLayout(self.candidates_slot)

        # New person: the Bale profile name is only a suggestion; staff fix it
        # (it may be a nickname or emoji) before it is written to accounting.
        self.create_panel = widgets.Panel("اطلاعات مشتری برای «سازه حساب»")
        self.fields = CustomerFields(customer)
        self.first_name_input = self.fields.inputs["first_name"]
        self.last_name_input = self.fields.inputs["last_name"]
        self.create_panel.body.addWidget(self.fields)
        self.create_panel.body.addWidget(widgets.label(
            "برای ساخت شخص تازه هر چهار مورد لازم است. اگر به شخص موجود وصل کنید، فقط جاهای خالی "
            "همان شخص پر می‌شود و شمارهٔ این مشتری به شماره‌های او اضافه می‌شود. "
            "برای جدا کردن دو نفر هم‌نام چیزی به نام اضافه نکنید.",
            name="Muted", wrap=True,
        ))
        root.addWidget(self.create_panel)

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
        QTimer.singleShot(0, self._fetch_candidates)

    @property
    def creating(self) -> bool:
        return self.mode_create.isChecked()

    def _mode_changed(self, *_args) -> None:
        self.code_panel.setVisible(not self.creating)
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

    # ---- v2.18.0: the same person, by national code or by name --------------
    def _fetch_candidates(self) -> None:
        if not hasattr(self.context.api, "person_candidates"):
            return
        run_async(
            lambda: self.context.api.person_candidates(int(self.customer["id"])),
            on_success=self._got_candidates,
            on_error=lambda _message, _kind: None,   # staff can still type a code
        )

    def _got_candidates(self, result: object) -> None:
        result = result if isinstance(result, dict) else {}
        owner = result.get("national_code")
        found = [c for c in result.get("candidates") or () if isinstance(c, dict) and c.get("code")]
        if not found and not (isinstance(owner, dict) and owner.get("code")):
            return
        panel = widgets.Panel("شاید همین شخص در حسابداری باشد")
        self.candidates_panel = panel
        if isinstance(owner, dict) and owner.get("code"):
            # the same national code: this IS that person
            panel.body.addWidget(self._candidate_line(
                f"کد ملی این مشتری در حسابداری به نام «{owner.get('name') or '—'}» "
                f"(کد {to_persian_digits(owner['code'])}) ثبت است؛ مشتری به همین شخص وصل می‌شود."))
            self._link_to(int(owner["code"]))
        else:
            for candidate in found:
                self._add_candidate(panel, candidate)
            if found[0].get("verdict") == "same":
                self._link_to(int(found[0]["code"]))
        self.candidates_slot.addWidget(panel)

    @staticmethod
    def _candidate_line(text: str) -> QWidget:
        return widgets.label(text, wrap=True, color=theme.WARNING_TEXT)

    def _add_candidate(self, panel: widgets.Panel, candidate: dict) -> None:
        tail = str(candidate.get("phone_tail") or "")
        phone = f" با شمارهٔ …{to_persian_digits(tail)}" if tail else ""
        panel.body.addWidget(self._candidate_line(
            f"«{candidate.get('name') or '—'}»{phone} در حسابداری هست. همین شخص است؟"))
        row = QHBoxLayout()
        code = int(candidate["code"])
        row.addWidget(widgets.button("همین شخص است", icon_name="check", variant="success",
                                     on_click=lambda c=code: self._link_to(c)))
        row.addWidget(widgets.button("شخص دیگری است", on_click=self._not_this_person))
        row.addStretch(1)
        panel.body.addLayout(row)

    def _link_to(self, code: int) -> None:
        self.mode_link.setChecked(True)
        self.code_input.setValue(code)

    def _not_this_person(self) -> None:
        self.code_input.setValue(0)
        self.mode_create.setChecked(True)

    # ---- submit ----------------------------------------------------------
    def _show_error(self, message: str, widget: QWidget) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        widget.setProperty("error", "true")
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _submit(self) -> None:
        problem, box = self.fields.problem(required=self.creating)
        if problem:
            self._show_error(problem, box)
            return
        if self.creating:
            self.person_code = None
            self.values = self.fields.values()
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
        self.values = self.fields.values()
        self.accept()


class CustomerDetailsDialog(widgets.ResponsiveDialog):
    """v2.18.0 «اطلاعات»: staff type what a customer told them. All four are required, with
    the same rules as the bot's form; a person in «سازه حساب» only gets its empty fields filled."""

    def __init__(self, customer: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: dict = {}
        self.setWindowTitle("اطلاعات مشتری")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("اطلاعات مشتری", size=14, bold=True))
        root.addWidget(widgets.label(
            f"{customer.get('name') or '—'} — {format_phone(customer.get('phone'))}", wrap=True))
        root.addWidget(widgets.label(
            "تا هر چهار مورد کامل نشود، سفارش این مشتری در «سازه حساب» ثبت نمی‌شود.",
            name="Muted", wrap=True))
        self.fields = CustomerFields(customer)
        root.addWidget(self.fields)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("ذخیره", icon_name="save", variant="primary",
                                         on_click=self._submit))
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        root.addLayout(buttons)

    def _submit(self) -> None:
        problem, _box = self.fields.problem(required=True)
        if problem:
            self.error_label.setText(problem)
            self.error_label.setVisible(True)
            return
        self.values = self.fields.values()
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
