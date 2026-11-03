"""v2.17.0 «قواعد فروشگاه»: کدهای وضعیت «سازه حساب»، ساعت کار و جای «صدور خودکار فاکتور».

هر بخش تیک جدای خودش را در «کاربران سیستم» دارد و بی‌تیک اصلاً نشان داده نمی‌شود؛
همان قاعده را سرور هم اجرا می‌کند.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...permissions import (
    AUTO_INVOICE_VIEW,
    AUTO_QUOTE_EDIT,
    AUTO_QUOTE_VIEW,
    FAQ_EDIT,
    FAQ_VIEW,
    STATUS_CODES_EDIT,
    STATUS_CODES_VIEW,
    WORK_HOURS_EDIT,
    WORK_HOURS_VIEW,
)
from ...persian import format_money, format_shamsi, to_english_digits, to_persian_digits
from ...server_settings import label, local_problem, translate_field_errors
from .. import theme, widgets
from ..base_page import BasePage
from ..rtl import RIGHT, mark_ltr

#: Saturday first; the values are Python weekdays, as the server keeps them.
DAYS_FA = (("شنبه", 5), ("یکشنبه", 6), ("دوشنبه", 0), ("سه‌شنبه", 1), ("چهارشنبه", 2),
           ("پنجشنبه", 3), ("جمعه", 4))
ORDER_KEY = "ACCOUNTING_STATUS_CODE"
HANDOVER_KEY = "ACCOUNTING_HANDOVER_STATUS_CODE"
AUTO_INVOICE_NOTE = "در نسخه‌های بعد"
#: v2.18.0: how many shifts a day the form offers
SHIFT_ROWS = 3
QUOTE_HEADERS = ("زمان", "متن مشتری", "ردیف لیست", "قیمت")
FAQ_FIELDS = (("hours", "ساعت کار"), ("address", "نشانی"), ("phone", "تلفن"),
              ("instagram", "اینستاگرام"), ("telegram", "تلگرام و بله"), ("website", "وب‌سایت"))


class ShopRulesPage(BasePage):
    title = "قواعد فروشگاه"
    subtitle = "کدهای وضعیت، ساعت کار و فاکتور"
    help_text = ("کدها از «سازه حساب» می‌آیند: تا «کد وضعیت سفارش» درست نوشته نشود هیچ سفارشی در "
                 "حسابداری ثبت نمی‌شود. ساعت کار می‌گوید اعلان کارکنان چه زمانی فرستاده شود.")
    reload_on_data_change = False
    refresh_on_server_events = False
    auto_refreshable = False

    def build_body(self) -> None:
        holder = QWidget()
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(16)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(holder)
        self.body.addWidget(self._scroll, 1)
        self.status_panel = self._status_panel() if self.context.can(STATUS_CODES_VIEW) else None
        self.hours_panel = self._hours_panel() if self.context.can(WORK_HOURS_VIEW) else None
        self.quote_panel = self._quote_panel() if self.context.can(AUTO_QUOTE_VIEW) else None
        self.faq_panel = self._faq_panel() if self.context.can(FAQ_VIEW) else None
        self.invoice_panel = self._invoice_panel() if self.context.can(AUTO_INVOICE_VIEW) else None
        self.column.addStretch(1)
        self._pending_focus = False

    # ------------------------------------------------------------------ status codes
    def _status_panel(self) -> widgets.Panel:
        panel = widgets.Panel("کدهای وضعیت «سازه حساب»")
        panel.body.addWidget(widgets.label(
            "در سرور اصلی «تایید» = ۶۸۰۸ (پیش‌نیاز فروش) و «تحویل به فروش» = ۶۹۱۴. کد دوم اختیاری "
            "است و فقط برای نشان دادن مرحلهٔ هر سفارش خوانده می‌شود؛ تبدیل سفارش به فاکتور را "
            "همکاران با «مرحله بعد» در خود «سازه حساب» انجام می‌دهند. ذخیره فوراً اعمال می‌شود و "
            "نیازی به راه‌اندازی دوبارهٔ سرور نیست.", name="Muted", wrap=True))
        form = QFormLayout()
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        self.order_input = mark_ltr(QLineEdit())
        self.order_input.setPlaceholderText("6808")
        self.handover_input = mark_ltr(QLineEdit())
        self.handover_input.setPlaceholderText("6914")
        editable = self.context.can(STATUS_CODES_EDIT)
        for field in (self.order_input, self.handover_input):
            field.setEnabled(editable)
            field.setMaximumWidth(180)
        form.addRow(widgets.label(label(ORDER_KEY) + ":"), self.order_input)
        form.addRow(widgets.label(label(HANDOVER_KEY) + ":"), self.handover_input)
        panel.body.addLayout(form)
        self.status_message = widgets.label("", wrap=True)
        self.status_message.setVisible(False)
        panel.body.addWidget(self.status_message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.status_guide_button = widgets.button(
            "راهنمای کد وضعیت سفارش…", icon_name="search", on_click=self._open_guide,
            tooltip="کدهای وضعیت سفارش‌های حسابداری و تعداد هر کدام (فقط خواندن)")
        buttons.addWidget(self.status_guide_button)
        self.status_save_button = widgets.button("ذخیرهٔ کدها", icon_name="save", variant="primary",
                                                 on_click=self._save_codes)
        self.status_save_button.setVisible(editable)
        buttons.addWidget(self.status_save_button)
        panel.body.addLayout(buttons)
        self.column.addWidget(panel)
        return panel

    def _open_guide(self) -> None:
        from ..status_codes import StatusCodesDialog

        StatusCodesDialog(self, self.context.api.order_status_codes).exec()

    def focus_status_code(self) -> None:
        """The yellow banner's «تنظیم کد وضعیت سفارش»."""
        if self.status_panel is None:
            return
        self._scroll.ensureWidgetVisible(self.status_panel)
        self.order_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.order_input.selectAll()

    def _save_codes(self) -> None:
        order = to_english_digits(self.order_input.text()).strip()
        handover = to_english_digits(self.handover_input.text()).strip()
        problems = {key: problem for key, value in ((ORDER_KEY, order), (HANDOVER_KEY, handover))
                    if (problem := local_problem(key, value))}
        if problems:
            self._status_note(translate_field_errors(problems), ok=False)
            return
        if handover and handover == order:
            self._status_note("«تحویل به فروش» باید با «کد وضعیت سفارش» فرق داشته باشد.", ok=False)
            return
        self.run(lambda: self.context.api.put_status_codes(order, handover),
                 on_success=self._codes_saved,
                 on_error=lambda message, _kind: self._status_note(message, ok=False))

    def _codes_saved(self, codes: object) -> None:
        self._show_codes(codes if isinstance(codes, dict) else {})
        self._status_note("ذخیره شد و همین حالا اعمال شد.", ok=True)
        info = self.context.system_info
        info.status_code_configured = bool((codes or {}).get("configured"))
        self.context.system_info_changed.emit(info)    # the yellow banner, at once
        self.context.data_changed.emit()

    def _status_note(self, text: str, *, ok: bool) -> None:
        self.status_message.setText(text)
        self.status_message.setStyleSheet(f"color: {theme.SUCCESS_DARK if ok else theme.DANGER};")
        self.status_message.setVisible(True)

    def _show_codes(self, codes: dict) -> None:
        for field, key in ((self.order_input, "order_status"),
                           (self.handover_input, "handover_status")):
            value = codes.get(key)
            field.setText("" if value is None else str(value))

    # ------------------------------------------------------------------ working hours
    def _hours_panel(self) -> widgets.Panel:
        panel = widgets.Panel("ساعت کار")
        panel.body.addWidget(widgets.label(
            "در ساعت کار، هر سفارش، رسید یا درخواست تازهٔ بی‌صاحب به همهٔ همکارانِ وصل‌شده در بله و "
            "تلگرام می‌رود و هر ۵ دقیقه تکرار می‌شود تا کسی «برداشت» بزند. بیرون از ساعت کار پیامی "
            "نمی‌رود و هنگام شروع کار یک خلاصه فرستاده می‌شود.", name="Muted", wrap=True))
        panel.body.addWidget(widgets.label(
            "اگر میان روز تعطیل هستید، نوبت دوم را هم پر کنید (مثلاً ۰۹:۰۰ تا ۱۳:۰۰ و ۱۶:۰۰ تا ۲۱:۰۰). "
            "نوبتِ خالی به حساب نمی‌آید.", name="Muted", wrap=True))
        editable = self.context.can(WORK_HOURS_EDIT)
        # v2.18.0: up to SHIFT_ROWS shifts a day; the first row keeps the old field names
        self.shift_inputs: list[tuple[QLineEdit, QLineEdit]] = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        for index in range(SHIFT_ROWS):
            begin, end = mark_ltr(QLineEdit()), mark_ltr(QLineEdit())
            for field in (begin, end):
                field.setEnabled(editable)
                field.setMaximumWidth(120)
            grid.addWidget(widgets.label(f"نوبت {to_persian_digits(index + 1)} — شروع:"), index, 0)
            grid.addWidget(begin, index, 1)
            grid.addWidget(widgets.label("پایان:"), index, 2)
            grid.addWidget(end, index, 3)
            self.shift_inputs.append((begin, end))
        grid.setColumnStretch(4, 1)
        self.start_input, self.end_input = self.shift_inputs[0]
        panel.body.addLayout(grid)
        days = QHBoxLayout()
        days.setSpacing(14)
        self.day_checks: dict[int, QCheckBox] = {}
        for text, value in DAYS_FA:
            check = QCheckBox(text)
            check.setEnabled(editable)
            self.day_checks[value] = check
            days.addWidget(check)
        days.addStretch(1)
        panel.body.addLayout(days)
        self.hours_message = widgets.label("", wrap=True)
        self.hours_message.setVisible(False)
        panel.body.addWidget(self.hours_message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.hours_save_button = widgets.button("ذخیرهٔ ساعت کار", icon_name="save",
                                                variant="primary", on_click=self._save_hours)
        self.hours_save_button.setVisible(editable)
        buttons.addWidget(self.hours_save_button)
        panel.body.addLayout(buttons)
        self.column.addWidget(panel)
        return panel

    def _save_hours(self) -> None:
        shifts = []
        for begin, end in self.shift_inputs:
            pair = (to_english_digits(begin.text()).strip(), to_english_digits(end.text()).strip())
            if any(pair):
                shifts.append(pair)
        if not shifts:
            self._hours_note("دست‌کم یک نوبت کاری بنویسید.", ok=False)
            return
        start, end = shifts[0][0], shifts[-1][1]
        days = sorted(value for value, check in self.day_checks.items() if check.isChecked())
        self.run(lambda: self.context.api.put_work_hours(start, end, days, shifts),
                 on_success=self._hours_saved,
                 on_error=lambda message, _kind: self._hours_note(message, ok=False))

    def _hours_saved(self, hours: object) -> None:
        self._show_hours(hours if isinstance(hours, dict) else {})
        self._hours_note("ذخیره شد.", ok=True)
        self.context.data_changed.emit()

    def _hours_note(self, text: str, *, ok: bool) -> None:
        self.hours_message.setText(text)
        self.hours_message.setStyleSheet(f"color: {theme.SUCCESS_DARK if ok else theme.DANGER};")
        self.hours_message.setVisible(True)

    def _show_hours(self, hours: dict) -> None:
        shifts = list(hours.get("shifts") or ()) \
            or [{"start": hours.get("start"), "end": hours.get("end")}]
        for index, (begin, end) in enumerate(self.shift_inputs):
            shift = shifts[index] if index < len(shifts) else {}
            begin.setText(str(shift.get("start") or ""))
            end.setText(str(shift.get("end") or ""))
        chosen = set(hours.get("days") or ())
        for value, check in self.day_checks.items():
            check.setChecked(value in chosen)

    # ------------------------------------------------------------------ automatic answers
    def _faq_panel(self) -> widgets.Panel:
        panel = widgets.Panel("پاسخ‌گوی خودکار")
        panel.body.addWidget(widgets.label(
            "ربات به پرسش‌های پرتکرار (ساعت کار، نشانی، گارانتی، اقساط، …) خودش پاسخ می‌دهد. اگر "
            "پرسش را مطمئن نشناسد چیزی نمی‌گوید و منو را نشان می‌دهد. پرسش‌هایی که به همکار نیاز "
            "دارد (قیمت روز، موجودی، پیگیری) پس از پاسخ در «درخواست کالا» هم می‌آید.",
            name="Muted", wrap=True))
        editable = self.context.can(FAQ_EDIT)
        self.faq_check = QCheckBox("ربات به پرسش‌های پرتکرار خودش پاسخ بدهد")
        self.faq_check.setEnabled(editable)
        panel.body.addWidget(self.faq_check)
        form = QFormLayout()
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        self.faq_inputs: dict[str, QLineEdit] = {}
        for key, caption in FAQ_FIELDS:
            box = QLineEdit()
            box.setEnabled(editable)
            self.faq_inputs[key] = box
            form.addRow(widgets.label(caption), box)
        panel.body.addLayout(form)
        panel.body.addWidget(widgets.label(
            "جواب‌هایی که یکی از این‌ها در آن است فقط وقتی فرستاده می‌شود که پر باشد.",
            name="Muted", wrap=True))
        self.faq_message = widgets.label("", wrap=True)
        self.faq_message.setVisible(False)
        panel.body.addWidget(self.faq_message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = widgets.button("ذخیرهٔ پاسخ‌گو", icon_name="save", variant="primary",
                              on_click=self._save_faq)
        save.setVisible(editable)
        buttons.addWidget(save)
        panel.body.addLayout(buttons)
        self.column.addWidget(panel)
        return panel

    def _save_faq(self) -> None:
        values = {key: box.text().strip() for key, box in self.faq_inputs.items()}
        enabled = self.faq_check.isChecked()
        self.run(lambda: self.context.api.set_faq(enabled, values), on_success=self._faq_saved,
                 on_error=self.default_error)

    def _faq_saved(self, data: object) -> None:
        self._show_faq(data)
        self.faq_message.setText("ذخیره شد.")
        self.faq_message.setStyleSheet(f"color: {theme.SUCCESS_DARK};")
        self.faq_message.setVisible(True)

    def _show_faq(self, data: object) -> None:
        data = data if isinstance(data, dict) else {}
        self.faq_check.setChecked(bool(data.get("enabled")))
        values = data.get("values") or {}
        for key, box in self.faq_inputs.items():
            box.setText(str(values.get(key) or ""))

    # ------------------------------------------------------------------ automatic quotes
    def _quote_panel(self) -> widgets.Panel:
        panel = widgets.Panel("پاسخ خودکار قیمت کالای غیرموجود")
        panel.body.addWidget(widgets.label(
            "اگر مشتری گوشی‌ای بخواهد که در کالاهای ما نیست، ربات آن را در لیست قیمت امروز کانال "
            "(با اصلاحیه‌ها) پیدا می‌کند. اگر مدل، حافظه، رم و رنگ مطمئن باشد قیمت را خودش می‌گوید؛ "
            "اگر نه، رنگ و حافظه را می‌پرسد یا به همکار می‌سپارد. سفارش این کالاها به همکار می‌رسد. "
            "قیمت فقط در ربات گفته می‌شود، هرگز در سایت و مینی‌اپ.", name="Muted", wrap=True))
        self.quote_check = QCheckBox("ربات قیمت این کالاها را خودش بگوید")
        self.quote_check.setEnabled(self.context.can(AUTO_QUOTE_EDIT))
        self.quote_check.clicked.connect(self._quote_clicked)
        panel.body.addWidget(self.quote_check)
        panel.body.addWidget(widgets.label("قیمت‌هایی که ربات گفته است:", bold=True))
        self.quote_table = widgets.DataTable(QUOTE_HEADERS, key="auto_quotes")
        self.quote_table.set_empty_state("هنوز قیمتی نگفته است", "", "receipt")
        self.quote_table.setMinimumHeight(220)
        panel.body.addWidget(self.quote_table)
        self.column.addWidget(panel)
        return panel

    def _quote_clicked(self, on: bool) -> None:
        self.run(lambda: self.context.api.set_auto_quote(bool(on)),
                 on_success=self._show_quote, on_error=self.default_error)

    def _show_quote(self, data: object) -> None:
        data = data if isinstance(data, dict) else {}
        self.quote_check.setChecked(bool(data.get("enabled")))
        table = self.quote_table
        table.setRowCount(0)
        for quote in data.get("report") or ():
            row = table.rowCount()
            table.insertRow(row)
            table.set_cell(row, 0, format_shamsi(quote.get("created_at")))
            table.set_cell(row, 1, str(quote.get("query") or "—"))
            table.set_cell(row, 2, " ".join(p for p in (quote.get("description"),
                                                        quote.get("color")) if p))
            table.set_cell(row, 3, format_money(quote.get("price_rial") or 0))
        table._refresh_states()

    # ------------------------------------------------------------------ automatic invoices
    def _invoice_panel(self) -> widgets.Panel:
        panel = widgets.Panel("صدور خودکار فاکتور")
        self.auto_invoice_check = QCheckBox("صدور خودکار فاکتور")
        self.auto_invoice_check.setChecked(False)
        self.auto_invoice_check.setEnabled(False)
        self.auto_invoice_check.setToolTip(AUTO_INVOICE_NOTE)
        panel.body.addWidget(self.auto_invoice_check)
        panel.body.addWidget(widgets.label(AUTO_INVOICE_NOTE, name="Muted", wrap=True))
        self.column.addWidget(panel)
        return panel

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        self.run(self.context.api.shop_rules, on_success=self._loaded,
                 on_error=self.default_error)

    def _loaded(self, rules: object) -> None:
        rules = rules if isinstance(rules, dict) else {}
        if self.status_panel is not None and isinstance(rules.get("status_codes"), dict):
            self._show_codes(rules["status_codes"])
            if rules["status_codes"].get("configured") is False:
                self._status_note("«کد وضعیت سفارش» تنظیم نشده است؛ تا آن را ننویسید هیچ سفارشی "
                                  "در «سازه حساب» ثبت نمی‌شود.", ok=False)
        if self.hours_panel is not None and isinstance(rules.get("work_hours"), dict):
            self._show_hours(rules["work_hours"])
        if self.quote_panel is not None and isinstance(rules.get("auto_quote"), dict):
            self._show_quote(rules["auto_quote"])
        if self.faq_panel is not None and isinstance(rules.get("faq"), dict):
            self._show_faq(rules["faq"])


def hours_text(hours: dict) -> str:
    """«۰۹:۰۰ تا ۲۱:۰۰، شنبه، یکشنبه، …»"""
    chosen = set((hours or {}).get("days") or ())
    days = "، ".join(text for text, value in DAYS_FA if value in chosen) or "هیچ روزی"
    shifts = (hours or {}).get("shifts") or [hours or {}]
    times = " و ".join(f"{s.get('start', '')} تا {s.get('end', '')}" for s in shifts)
    return to_persian_digits(times) + f"، {days}"
