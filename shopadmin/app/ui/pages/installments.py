"""v2.18.1 «محاسبهٔ اقساط».

برنامه اول حساب می‌کند و نتیجه را نشان می‌دهد؛ بعد همه‌چیز (مبلغ و تاریخ هر چک، پیش‌پرداخت، جمع‌ها)
دستی قابل تغییر است و اختلاف با محاسبهٔ اولیه همیشه دیده می‌شود. گرد کردن فقط پیشنهاد است.

حساب با همان ``installments.py`` سرور است (هر دو یکی‌اند و تست این را نگه می‌دارد)؛ کارت مشتری را
سرور می‌سازد و هرگز سود یا نرخ روی آن نیست.
"""
from __future__ import annotations

import base64
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import installments as inst
from ...permissions import INSTALLMENT_EDIT, INSTALLMENT_RULES_EDIT
from ...persian import format_datetime_shamsi, to_persian_digits
from .. import widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..rtl import RIGHT
from ..widgets_shamsi import ShamsiDateEdit

ROUND_CHOICES = (("بدون گرد کردن", inst.ROUND_NONE, 0),
                 ("هر چک رو به بالا تا ۱۰۰٬۰۰۰ ریال، همهٔ چک‌ها برابر", inst.ROUND_EQUAL, 100_000),
                 ("هر چک رو به بالا تا ۱٬۰۰۰٬۰۰۰ ریال، همهٔ چک‌ها برابر", inst.ROUND_EQUAL, 1_000_000),
                 ("گرد تا ۱۰۰٬۰۰۰ ریال، اختلاف روی چک آخر", inst.ROUND_LAST, 100_000),
                 ("گرد تا ۱٬۰۰۰٬۰۰۰ ریال، اختلاف روی چک آخر", inst.ROUND_LAST, 1_000_000))
STATUS_FA = {"saved": "ذخیره‌شده", "pending": "در صف ارسال", "sent": "ارسال شد", "failed": "ارسال نشد"}
SCHEDULE_HEADERS = ("شماره", "تاریخ چک", "مبلغ (ریال)")
COMPARE_HEADERS = ("ماه", "هر چک", "سود", "جمع اقساط", "جمع کل")
HISTORY_HEADERS = ("زمان", "کاربر", "مشتری", "گوشی", "نقد", "چک‌ها", "سود", "جمع کل", "وضعیت")
_PICK_DELAY_MS = 300


def money(value: int) -> str:
    return inst.fa_money(int(value))


def _next_month() -> date:
    today = date.today()
    return date(today.year + today.month // 12, today.month % 12 + 1, min(today.day, 28))


class InstallmentsPage(BasePage):
    title = "محاسبهٔ اقساط"
    subtitle = "حساب، ویرایش دستی و کارت برای مشتری"
    help_text = ("قیمت، پیش‌پرداخت و تعداد ماه را بنویسید؛ برنامه حساب می‌کند. بعد هر مبلغ و تاریخی "
                 "را می‌توانید دستی عوض کنید. روی کارت مشتری سود و نرخ نوشته نمی‌شود.")
    reload_on_data_change = False
    refresh_on_server_events = False
    auto_refreshable = False

    def build_body(self) -> None:
        self.quote: inst.Quote | None = None
        self.down = 0
        self.checks: list[int] = []
        self.dates: list[str] = []
        self._updating = False
        self.card_png: bytes = b""
        self.card_text = ""
        self.can_edit = self.context.can(INSTALLMENT_EDIT)

        holder = QWidget()
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, 1)

        self._inputs_panel()
        self._result_panel()
        self._schedule_panel()
        self._compare_panel()
        self._output_panel()
        self.column.addStretch(1)
        self._recalculate()

    # ---- inputs --------------------------------------------------------------------------
    def _inputs_panel(self) -> None:
        panel = widgets.Panel("ورودی‌ها")
        form = QFormLayout()
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(10)

        name_row = QHBoxLayout()
        self.phone_name = QLineEdit()
        self.phone_name.setPlaceholderText("مثال: Galaxy S25")
        self.phone_name.setMaxLength(200)
        name_row.addWidget(self.phone_name, 1)
        name_row.addWidget(widgets.button("انتخاب از کالاها…", on_click=self._pick_item))
        form.addRow(widgets.label("نام گوشی:"), name_row)

        self.price = widgets.MoneyInput()
        self.price.textChanged.connect(self._recalculate)
        form.addRow(widgets.label("قیمت گوشی:"), self.price)

        down_box = QVBoxLayout()
        down_box.setSpacing(4)
        self.down_input = widgets.AmountEdit()
        self.down_input.setPlaceholderText("مبلغ یا درصد، مثل ۱۰۰٬۰۰۰٬۰۰۰ یا ۵۰٪")
        self.down_input.textChanged.connect(self._recalculate)
        down_box.addWidget(self.down_input)
        self.down_note = widgets.label("", name="Muted", wrap=True)
        down_box.addWidget(self.down_note)
        form.addRow(widgets.label("پیش‌پرداخت:"), down_box)

        self.months = QSpinBox()
        self.months.setRange(inst.MIN_MONTHS, inst.MAX_MONTHS)
        self.months.setValue(5)
        self.months.valueChanged.connect(self._recalculate)
        form.addRow(widgets.label("تعداد ماه:"), self.months)

        rate_row = QHBoxLayout()
        self.rate = QLineEdit(inst.DEFAULT_RATE)
        self.rate.setMaximumWidth(120)
        self.rate.textChanged.connect(self._recalculate)
        rate_row.addWidget(self.rate)
        rate_row.addWidget(widgets.label("٪ در ماه"))
        self.save_rate_button = None
        if self.context.can(INSTALLMENT_RULES_EDIT):
            self.save_rate_button = widgets.button(
                "ذخیره به‌عنوان پیش‌فرض", tooltip="نرخ پیش‌فرض همهٔ کاربران",
                on_click=self._save_rate)
            rate_row.addWidget(self.save_rate_button)
        rate_row.addStretch(1)
        form.addRow(widgets.label("نرخ ماهانه:"), rate_row)

        self.first_date = ShamsiDateEdit(_next_month())
        self.first_date.date_changed.connect(self._dates_from_first)
        form.addRow(widgets.label("تاریخ اولین چک:"), self.first_date)

        panel.body.addLayout(form)
        self.problem = widgets.label("", wrap=True)
        self.problem.setVisible(False)
        panel.body.addWidget(self.problem)
        self.column.addWidget(panel)

    def _first_text(self) -> str:
        return inst.jalali_text(*inst.jalali_from_date(self.first_date.date()))

    def _read_inputs(self) -> tuple[int, int, int, str, str]:
        """(price, down, months, rate, the first thing wrong)."""
        price = self.price.value() or 0
        typed = self.down_input.text().strip()
        down = inst.parse_down(typed, price) if typed else 0
        rate = self.rate.text()
        if down is None:
            return price, 0, self.months.value(), rate, "پیش‌پرداخت درست نیست."
        self.down_note.setText(f"= {money(down)} ریال" if typed else "")
        return price, down, self.months.value(), rate, inst.problem(price, down,
                                                                    self.months.value(), rate)

    def _recalculate(self, *_args) -> None:
        """A change in the inputs: a new calculation; hand edits start over."""
        price, down, months, rate, problem = self._read_inputs()
        filled = bool(self.price.text().strip())
        self._say(problem if filled else "")
        if problem:
            self.quote = None
            self.checks, self.dates, self.down = [], [], 0
        else:
            self.quote = inst.calculate(price, down, months, rate)
            self.down = self.quote.down
            self.checks = list(self.quote.checks)
            self.dates = inst.schedule(self._first_text(), months)
        self._forget_card()
        self._fill_schedule()
        self._fill_compare(price, down, rate, not problem)
        self._show_totals()
        self._show_rounding()

    def _dates_from_first(self, *_args) -> None:
        if self.quote is None:
            return
        self.dates = inst.schedule(self._first_text(), len(self.checks))
        self._forget_card()
        self._fill_schedule()

    def _say(self, text: str) -> None:
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    # ---- result ----------------------------------------------------------------------------
    def _result_panel(self) -> None:
        panel = widgets.Panel("نتیجه")
        form = QFormLayout()
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)
        self.remaining_value = widgets.label("—")
        form.addRow(widgets.label("مانده پس از پیش‌پرداخت:"), self.remaining_value)
        self.interest_value = widgets.label("—", bold=True)
        form.addRow(widgets.label("سود:"), self.interest_value)
        self.each_value = widgets.label("—")
        form.addRow(widgets.label("هر چک:"), self.each_value)
        self.down_edit = widgets.AmountEdit()
        self.down_edit.textEdited.connect(self._down_edited)
        form.addRow(widgets.label("پیش‌پرداخت (قابل تغییر):"), self.down_edit)
        self.total_edit = widgets.AmountEdit()
        self.total_edit.textEdited.connect(self._total_edited)
        form.addRow(widgets.label("جمع اقساط (قابل تغییر):"), self.total_edit)
        self.grand_edit = widgets.AmountEdit()
        self.grand_edit.textEdited.connect(self._grand_edited)
        form.addRow(widgets.label("جمع کل (قابل تغییر):"), self.grand_edit)
        panel.body.addLayout(form)
        self.difference = widgets.label("", bold=True, wrap=True)
        panel.body.addWidget(self.difference)

        row = QHBoxLayout()
        self.reset_button = widgets.button("بازگشت به محاسبهٔ اولیه", icon_name="refresh",
                                           on_click=self._recalculate)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        panel.body.addLayout(row)

        panel.body.addWidget(widgets.hline())
        panel.body.addWidget(widgets.label("پیشنهاد گرد کردن (فقط اگر خودتان بخواهید اعمال می‌شود)",
                                           name="SectionTitle"))
        rounding = QHBoxLayout()
        self.round_choice = QComboBox()
        for text, _mode, _step in ROUND_CHOICES:
            self.round_choice.addItem(text)
        self.round_choice.currentIndexChanged.connect(self._show_rounding)
        rounding.addWidget(self.round_choice, 1)
        self.round_button = widgets.button("اعمال", on_click=self._apply_rounding)
        rounding.addWidget(self.round_button)
        panel.body.addLayout(rounding)
        self.round_note = widgets.label("", name="Muted", wrap=True)
        panel.body.addWidget(self.round_note)
        self.column.addWidget(panel)

    def _show_totals(self) -> None:
        self._updating = True
        try:
            if self.quote is None:
                for box in (self.down_edit, self.total_edit, self.grand_edit):
                    box.clear()
                for shown in (self.remaining_value, self.interest_value, self.each_value):
                    shown.setText("—")
                self.difference.clear()
                return
            now = inst.totals(self.quote, self.down, self.checks)
            self.remaining_value.setText(f"{money(self.quote.price - self.down)} ریال")
            self.interest_value.setText(f"{money(now.interest)} ریال")
            self.each_value.setText(self._each_text())
            for box, value in ((self.down_edit, self.down), (self.total_edit, now.installments_total),
                               (self.grand_edit, now.grand_total)):
                if not box.hasFocus():
                    box.setText(money(value))
            self.difference.setText(f"اختلاف با محاسبه: {inst.difference_text(now.difference)}")
        finally:
            self._updating = False

    def _each_text(self) -> str:
        groups = inst.check_groups(self.checks)
        return "، ".join(f"{to_persian_digits(g.count)} چک × {money(g.amount)} ریال" for g in groups)

    def _edited(self) -> None:
        self._forget_card()
        self._show_totals()

    def _down_edited(self, text: str) -> None:
        if self._updating or self.quote is None:
            return
        value = inst.parse_amount(text)
        if value is None:
            self._say("پیش‌پرداخت درست نیست.")
            return
        self._say(inst.edit_problem(self.quote.price, value, self.checks))
        self.down = value
        self._edited()

    def _total_edited(self, text: str) -> None:
        if self._updating or self.quote is None:
            return
        value = inst.parse_amount(text)
        if value is None or not self.checks:
            self._say("جمع اقساط درست نیست.")
            return
        self.checks = inst.with_total(self.checks, value)
        self._say("" if sum(self.checks) == value else "چک آخر نمی‌تواند صفر یا منفی شود.")
        self._fill_schedule()
        self._edited()

    def _grand_edited(self, text: str) -> None:
        if self._updating or self.quote is None:
            return
        value = inst.parse_amount(text)
        if value is None or not self.checks:
            self._say("جمع کل درست نیست.")
            return
        self.checks = inst.with_total(self.checks, value - self.down)
        self._say("" if self.down + sum(self.checks) == value
                  else "چک آخر نمی‌تواند صفر یا منفی شود.")
        self._fill_schedule()
        self._edited()

    def _chosen_rounding(self) -> inst.Rounded | None:
        if self.quote is None:
            return None
        _text, mode, step = ROUND_CHOICES[self.round_choice.currentIndex()]
        return inst.rounded(self.quote, mode, step)

    def _show_rounding(self, *_args) -> None:
        result = self._chosen_rounding()
        self.round_button.setEnabled(result is not None)
        if result is None:
            self.round_note.clear()
            return
        groups = inst.check_groups(result.checks)
        parts = "، ".join(f"{to_persian_digits(g.count)} چک × {money(g.amount)}" for g in groups)
        extra = f"؛ {money(result.extra)} ریال به سود اضافه می‌شود" if result.extra else ""
        self.round_note.setText(f"{parts}؛ جمع کل {money(result.grand_total)} ریال{extra}")

    def _apply_rounding(self) -> None:
        result = self._chosen_rounding()
        if result is None:
            return
        self.checks = list(result.checks)
        self._fill_schedule()
        self._edited()

    # ---- the check schedule ----------------------------------------------------------------
    def _schedule_panel(self) -> None:
        panel = widgets.Panel("برنامهٔ چک‌ها (هر تاریخ و مبلغ را می‌توانید تغییر دهید)")
        self.schedule = widgets.RoundTable(0, len(SCHEDULE_HEADERS))
        self.schedule.setHorizontalHeaderLabels(SCHEDULE_HEADERS)
        self.schedule.verticalHeader().setVisible(False)
        self.schedule.horizontalHeader().setStretchLastSection(True)
        self.schedule.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.schedule.setItemDelegateForColumn(2, widgets.AmountDelegate(self.schedule))
        self.schedule.setMinimumHeight(240)
        self.schedule.itemChanged.connect(self._cell_changed)
        panel.body.addWidget(self.schedule)
        self.column.addWidget(panel)

    def _fill_schedule(self) -> None:
        self._updating = True
        try:
            self.schedule.setRowCount(len(self.checks))
            for row, amount in enumerate(self.checks):
                number = QTableWidgetItem(to_persian_digits(row + 1))
                number.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.schedule.setItem(row, 0, number)
                day = self.dates[row] if row < len(self.dates) else ""
                self.schedule.setItem(row, 1, QTableWidgetItem(to_persian_digits(day)))
                self.schedule.setItem(row, 2, QTableWidgetItem(money(amount)))
        finally:
            self._updating = False

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row, column = item.row(), item.column()
        if column == 2:
            value = inst.parse_amount(item.text())
            if value is None or value <= 0:
                self._say("مبلغ چک باید عددی بیشتر از صفر باشد؛ مقدار قبلی برگشت.")
                self._fill_schedule()
                return
            self.checks[row] = value
        elif column == 1:
            day = inst.parse_jalali(item.text())
            if day is None:
                self._say("تاریخ درست نیست (مثل ۱۴۰۵/۰۹/۱۵)؛ مقدار قبلی برگشت.")
                self._fill_schedule()
                return
            self.dates[row] = inst.jalali_text(*day)
        self._say("")
        self._fill_schedule()
        self._edited()

    # ---- comparison ---------------------------------------------------------------------------
    def _compare_panel(self) -> None:
        panel = widgets.Panel("مقایسهٔ ۱ تا ۱۲ ماه با همین پیش‌پرداخت")
        self.compare = widgets.DataTable(COMPARE_HEADERS, fit_width=True, stretch_column=4)
        self.compare.setMinimumHeight(420)
        self.compare.set_empty_state("قیمت و پیش‌پرداخت را بنویسید.")
        self.compare.row_activated.connect(self._compare_activated)
        panel.body.addWidget(self.compare)
        self.column.addWidget(panel)

    def _fill_compare(self, price: int, down: int, rate: str, ok: bool) -> None:
        rows = []
        if ok:
            for quote in inst.comparison(price, down, rate):
                rows.append([to_persian_digits(quote.months), money(quote.each_check),
                             money(quote.interest), money(quote.installments_total),
                             money(quote.grand_total)])
        self.compare.fill(rows)

    def _compare_activated(self, row: int) -> None:
        self.months.setValue(row + 1)

    # ---- outputs --------------------------------------------------------------------------
    def _output_panel(self) -> None:
        panel = widgets.Panel("خروجی")
        panel.body.addWidget(widgets.label("برای مشتری (بدون سود و نرخ):", name="SectionTitle"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.make_card_button = widgets.button("ساخت کارت", variant="primary",
                                               on_click=self._make_card)
        self.save_png_button = widgets.button("ذخیرهٔ تصویر…", on_click=self._save_png)
        self.print_button = widgets.button("چاپ…", on_click=self._print)
        self.copy_button = widgets.button("کپی متن", on_click=self._copy_customer)
        self.send_button = widgets.button("ارسال به مشتری…", on_click=self._send)
        self.send_button.setVisible(self.can_edit)
        for button in (self.make_card_button, self.save_png_button, self.print_button,
                       self.copy_button, self.send_button):
            row.addWidget(button)
        row.addStretch(1)
        panel.body.addLayout(row)
        self.card_preview = widgets.label("")
        self.card_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card_preview.setVisible(False)
        panel.body.addWidget(self.card_preview)

        panel.body.addWidget(widgets.hline())
        panel.body.addWidget(widgets.label("برای همکاران (با سود و نرخ):", name="SectionTitle"))
        staff_row = QHBoxLayout()
        staff_row.setSpacing(8)
        self.copy_staff_button = widgets.button("کپی جزئیات کامل", on_click=self._copy_staff)
        self.save_quote_button = widgets.button("ذخیره در تاریخچه", on_click=self._save_quote)
        self.save_quote_button.setVisible(self.can_edit)
        self.history_button = widgets.button("تاریخچه…", on_click=self._open_history)
        for button in (self.copy_staff_button, self.save_quote_button, self.history_button):
            staff_row.addWidget(button)
        staff_row.addStretch(1)
        panel.body.addLayout(staff_row)
        self.column.addWidget(panel)
        self._forget_card()

    def current_sheet(self) -> inst.Sheet | None:
        """What is on the page now, or None (with the reason said) when it cannot be right."""
        if self.quote is None:
            self._say(self.problem.text() or "اول قیمت و پیش‌پرداخت را بنویسید.")
            return None
        today = inst.jalali_text(*inst.jalali_from_date(date.today()))
        sheet = inst.Sheet(phone_name=self.phone_name.text().strip(), price=self.quote.price,
                           down=self.down, rate=self.quote.rate, checks=tuple(self.checks),
                           dates=tuple(self.dates), date=today)
        wrong = inst.sheet_problem(sheet)
        if wrong:
            self._say(wrong)
            return None
        return sheet

    @staticmethod
    def _payload(sheet: inst.Sheet) -> dict:
        return {"phone_name": sheet.phone_name, "price": sheet.price, "down": sheet.down,
                "rate": sheet.rate, "checks": list(sheet.checks), "dates": list(sheet.dates)}

    def _forget_card(self) -> None:
        """Something changed: the card made earlier no longer says the same."""
        self.card_png = b""
        self.card_text = ""
        self.card_preview.clear()
        self.card_preview.setVisible(False)
        self.save_png_button.setEnabled(False)
        self.print_button.setEnabled(False)

    def _make_card(self) -> None:
        sheet = self.current_sheet()
        if sheet is None:
            return
        self.make_card_button.setEnabled(False)
        run_async(lambda: self.context.api.installment_card(self._payload(sheet)),
                  on_success=self._got_card, on_error=self._card_failed,
                  on_done=lambda: self.make_card_button.setEnabled(True))

    def _got_card(self, answer: object) -> None:
        answer = answer if isinstance(answer, dict) else {}
        self.card_text = str(answer.get("text") or "")
        data = str(answer.get("png_b64") or "")
        if not data:
            self.toasts.show_error("تصویر کارت روی سرور ساخته نشد (مرورگر Edge لازم است). "
                                   "«کپی متن» کار می‌کند.")
            return
        self.card_png = base64.b64decode(data)
        picture = QPixmap()
        picture.loadFromData(self.card_png)
        self.card_preview.setPixmap(picture.scaledToWidth(
            420, Qt.TransformationMode.SmoothTransformation))
        self.card_preview.setVisible(True)
        self.save_png_button.setEnabled(True)
        self.print_button.setEnabled(True)

    def _card_failed(self, message: str, _kind: str) -> None:
        self.toasts.show_error(message)

    def _save_png(self) -> None:
        if not self.card_png:
            return
        name = "".join(c for c in self.phone_name.text().strip() if c.isalnum() or c in " -_")
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ کارت", f"اقساط {name}.png".replace("  ", " "), "PNG (*.png)")
        if path:
            with open(path, "wb") as stream:
                stream.write(self.card_png)
            self.toasts.show_success("کارت ذخیره شد.")

    def _print(self) -> None:
        if not self.card_png:
            return
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        picture = QPixmap()
        picture.loadFromData(self.card_png)
        painter = QPainter(printer)
        area = painter.viewport()
        size = picture.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        painter.setViewport(area.x(), area.y(), size.width(), size.height())
        painter.setWindow(picture.rect())
        painter.drawPixmap(0, 0, picture)
        painter.end()

    def _copy_customer(self) -> None:
        sheet = self.current_sheet()
        if sheet is not None:
            QGuiApplication.clipboard().setText(inst.customer_text(sheet, "عصر ارتباطات ۲"))
            self.toasts.show_success("متن مشتری کپی شد.")

    def _copy_staff(self) -> None:
        sheet = self.current_sheet()
        if sheet is not None:
            QGuiApplication.clipboard().setText(inst.staff_text(sheet, self.quote))
            self.toasts.show_success("جزئیات کامل کپی شد.")

    def _save_quote(self) -> None:
        sheet = self.current_sheet()
        if sheet is None:
            return
        run_async(lambda: self.context.api.installment_save(self._payload(sheet)),
                  on_success=lambda _row: self.toasts.show_success("در تاریخچه ذخیره شد."),
                  on_error=self._card_failed)

    def _send(self) -> None:
        sheet = self.current_sheet()
        if sheet is None:
            return
        dialog = CustomerPickDialog(self.context, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.user_id is None:
            return
        payload = self._payload(sheet)
        user_id = dialog.user_id
        run_async(lambda: self.context.api.installment_send(user_id, payload),
                  on_success=lambda _row: self.toasts.show_success(
                      "در صف ارسال است؛ نتیجه را در «تاریخچه» ببینید."),
                  on_error=self._card_failed)

    def _open_history(self) -> None:
        dialog = QuoteHistoryDialog(self.context, self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.chosen:
            self.show_quote(dialog.chosen)

    def show_quote(self, row: dict) -> None:
        """A saved quote back on the page, with its own amounts and dates."""
        checks = [int(c) for c in row.get("checks") or ()]
        if not checks:
            return
        self.phone_name.setText(str(row.get("phone_name") or ""))
        for box in (self.price, self.down_input, self.months, self.rate):
            box.blockSignals(True)
        self.price.setText(str(int(row.get("price") or 0)))
        self.down_input.setText(str(int(row.get("down") or 0)))
        self.months.setValue(len(checks))
        self.rate.setText(str(row.get("rate") or inst.DEFAULT_RATE))
        for box in (self.price, self.down_input, self.months, self.rate):
            box.blockSignals(False)
        self._recalculate()
        if self.quote is not None:
            self.checks = checks
            self.dates = [str(d) for d in row.get("dates") or ()] or self.dates
            self._fill_schedule()
            self._edited()

    def _pick_item(self) -> None:
        dialog = ItemPickDialog(self.context, self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.chosen:
            self.phone_name.setText(str(dialog.chosen.get("name") or ""))
            self.price.setText(str(int(dialog.chosen.get("price") or 0)))

    def _save_rate(self) -> None:
        rate = self.rate.text()
        run_async(lambda: self.context.api.set_installment_settings(rate=rate),
                  on_success=lambda _a: self.toasts.show_success("نرخ پیش‌فرض ذخیره شد."),
                  on_error=self._card_failed)

    def load(self) -> None:
        run_async(self.context.api.installment_settings, on_success=self._got_settings,
                  on_error=lambda _m, _k: None)   # the page still calculates with what is typed

    def _got_settings(self, answer: object) -> None:
        rate = str((answer or {}).get("rate") or "") if isinstance(answer, dict) else ""
        if rate and not self.rate.hasFocus() and self.rate.text() == inst.DEFAULT_RATE:
            self.rate.setText(rate)


class _PickDialog(widgets.ResponsiveDialog):
    """A search box and a list; a search runs a moment after the last key press."""

    def __init__(self, context, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        column = QVBoxLayout(self)
        self.search = widgets.SearchBox(hint)
        column.addWidget(self.search)
        self.rows = QListWidget()
        self.rows.setMinimumHeight(320)
        self.rows.itemDoubleClicked.connect(lambda _item: self._accept())
        column.addWidget(self.rows, 1)
        self.note = widgets.label("", name="Muted", wrap=True)
        column.addWidget(self.note)
        self.ok_button = widgets.button("انتخاب", variant="primary", on_click=self._accept)
        column.addLayout(widgets.footer(self.ok_button, close=widgets.button(
            "انصراف", on_click=self.reject)))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_PICK_DELAY_MS)
        self._timer.timeout.connect(self._search)
        self.search.textChanged.connect(lambda _text: self._timer.start())

    def _search(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _accept(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _fill(self, rows, text_of) -> None:
        self.rows.clear()
        for row in rows if isinstance(rows, list) else ():
            item = QListWidgetItem(text_of(row))
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.rows.addItem(item)
        self.note.setText("" if self.rows.count() else "چیزی پیدا نشد.")

    def _current(self) -> dict | None:
        item = self.rows.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None


class ItemPickDialog(_PickDialog):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(context, "انتخاب از کالاها", "نام کالا…", parent)
        self.chosen: dict | None = None
        self._search()

    def _search(self) -> None:
        query = self.search.text().strip()
        run_async(lambda: self.context.api.installment_items(query),
                  on_success=lambda rows: self._fill(
                      rows, lambda r: f"{r.get('name')} — {money(r.get('price') or 0)} ریال"),
                  on_error=lambda message, _kind: self.note.setText(message))

    def _accept(self) -> None:
        self.chosen = self._current()
        if self.chosen:
            self.accept()


class CustomerPickDialog(_PickDialog):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(context, "ارسال کارت به مشتری", "نام یا شمارهٔ مشتری…", parent)
        self.user_id: int | None = None
        self.ok_button.setText("ارسال کارت")
        self.note.setText("کارت در گفت‌وگوی مشتری در بله یا تلگرام فرستاده می‌شود.")

    def _search(self) -> None:
        query = self.search.text().strip()
        run_async(lambda: self.context.api.installment_customers(query),
                  on_success=lambda rows: self._fill(rows, self._row_text),
                  on_error=lambda message, _kind: self.note.setText(message))

    @staticmethod
    def _row_text(row: dict) -> str:
        where = {"bale": "بله", "telegram": "تلگرام"}.get(str(row.get("platform")), "")
        tail = to_persian_digits(row.get("phone_tail") or "")
        return f"{row.get('name') or '—'} ({where}، شماره به {tail} ختم می‌شود)"

    def _accept(self) -> None:
        row = self._current()
        if row:
            self.user_id = int(row["id"])
            self.accept()


class QuoteHistoryDialog(widgets.ResponsiveDialog):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.chosen: dict | None = None
        self.quotes: list[dict] = []
        self.setWindowTitle("تاریخچهٔ محاسبهٔ اقساط")
        self.setMinimumWidth(860)
        column = QVBoxLayout(self)
        self.table = widgets.DataTable(HISTORY_HEADERS, selectable_rows=True)
        self.table.setMinimumHeight(380)
        self.table.set_empty_state("هنوز چیزی ذخیره نشده است.")
        self.table.row_activated.connect(self._activated)
        column.addWidget(self.table, 1)
        self.open_button = widgets.button("نمایش در صفحه", variant="primary",
                                          on_click=self._open_selected)
        column.addLayout(widgets.footer(self.open_button, close=widgets.button(
            "بستن", on_click=self.reject)))
        run_async(context.api.installment_quotes, on_success=self._got,
                  on_error=lambda message, _kind: self.table.set_error_state(message))

    def _got(self, rows: object) -> None:
        self.quotes = rows if isinstance(rows, list) else []
        self.table.fill([[
            format_datetime_shamsi(row.get("created_at")), str(row.get("actor") or ""),
            str(row.get("customer_name") or "—"), str(row.get("phone_name") or "—"),
            money(row.get("down") or 0), to_persian_digits(len(row.get("checks") or ())),
            money(row.get("interest") or 0), money(row.get("grand_total") or 0),
            STATUS_FA.get(str(row.get("status")), str(row.get("status") or "")),
        ] for row in self.quotes])

    def _activated(self, row: int) -> None:
        if 0 <= row < len(self.quotes):
            self.chosen = self.quotes[row]
            self.accept()

    def _open_selected(self) -> None:
        self._activated(self.table.currentRow())
