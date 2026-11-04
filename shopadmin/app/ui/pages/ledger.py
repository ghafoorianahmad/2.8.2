"""v2.18.2 «گردش سال‌های قبل» (فقط‌خواندنی).

همهٔ اشخاص «سازه حساب» (نه فقط مشتریان ربات و سایت) در هر پایگاه‌دادهٔ سال مالی که سرور اجازهٔ
خواندنش را دارد، با جستجوی نام، تلفن یا کد ملی و گردش حساب هر شخص. چیزی نوشته نمی‌شود و خواندن و
نوشتن اصلی برنامه همان پایگاه‌دادهٔ «تنظیمات سرور» می‌ماند.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout

from ...persian import format_int, format_money, to_persian_digits
from .. import widgets
from ..async_utils import run_async
from ..base_page import BasePage

PERSON_HEADERS = ("کد", "نام", "کد ملی", "تلفن")
ROW_HEADERS = ("تاریخ", "نوع", "شماره سند", "شرح", "بدهکار", "بستانکار", "مانده", "تشخیص")
SIDE_FA = {"debtor": "بدهکار", "creditor": "بستانکار", "zero": "بی‌حساب"}
NO_DATABASE = ("هنوز پایگاه‌داده‌ای برای خواندن نیست. مدیر باید اسکریپت grant_ledger_readonly.sql "
               "را با sa اجرا کند.")
_SEARCH_DELAY_MS = 350


class LedgerPage(BasePage):
    title = "گردش سال‌های قبل"
    subtitle = "همهٔ اشخاص «سازه حساب»، در هر سال مالی (فقط دیدن)"
    help_text = ("سال مالی را انتخاب کنید و نام، تلفن یا کد ملی را بنویسید؛ با کلیک روی هر نفر گردش "
                 "حسابش در همان سال را می‌بینید. اینجا چیزی نوشته یا تغییر داده نمی‌شود.")
    reload_on_data_change = False
    refresh_on_server_events = False
    auto_refreshable = False

    def build_body(self) -> None:
        self.persons: list[dict] = []
        self._shown_code: int | None = None
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(widgets.label("سال مالی:"))
        self.database = QComboBox()
        self.database.setMinimumWidth(180)
        self.database.currentIndexChanged.connect(self._database_changed)
        bar.addWidget(self.database)
        self.search = widgets.SearchBox("نام، تلفن یا کد ملی")
        self.search.textChanged.connect(lambda _text: self._timer.start())
        bar.addWidget(self.search, 1)
        self.body.addLayout(bar)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SEARCH_DELAY_MS)
        self._timer.timeout.connect(self._search)

        self.note = widgets.label("", name="Muted", wrap=True)
        self.body.addWidget(self.note)
        self.person_table = widgets.DataTable(PERSON_HEADERS, selectable_rows=True, fit_width=True,
                                              stretch_column=1)
        self.person_table.set_empty_state("کسی پیدا نشد", "", "customers")
        self.person_table.itemSelectionChanged.connect(self._person_selected)
        self.body.addWidget(self.person_table, 2)

        self.summary = widgets.label("یک نفر را انتخاب کنید.", bold=True, wrap=True)
        self.body.addWidget(self.summary)
        self.row_table = widgets.DataTable(ROW_HEADERS, fit_width=True, stretch_column=3)
        self.row_table.set_empty_state("گردشی نیست", "", "receipt")
        self.body.addWidget(self.row_table, 3)

    def load(self) -> None:
        run_async(self.context.api.ledger_databases, on_success=self._got_databases,
                  on_error=self._failed)

    def _failed(self, message: str, _kind: str) -> None:
        self.toasts.show_error(message)

    def _got_databases(self, rows: object) -> None:
        rows = rows if isinstance(rows, list) else []
        chosen = self.database.currentData()
        self.database.blockSignals(True)
        self.database.clear()
        for row in rows:
            name = str(row.get("name") or "")
            self.database.addItem(f"{name} (سال جاری)" if row.get("current") else name, name)
        at = self.database.findData(chosen)
        if at >= 0:
            self.database.setCurrentIndex(at)
        else:                               # a previous year is what this page is for
            older = next((i for i, row in enumerate(rows) if not row.get("current")), 0)
            self.database.setCurrentIndex(older)
        self.database.blockSignals(False)
        self.note.setText("" if rows else NO_DATABASE)
        if rows:
            self._search()

    def _database_changed(self, *_args) -> None:
        self._search()

    def _search(self) -> None:
        database = self.database.currentData()
        if not database:
            return
        query = self.search.text().strip()
        run_async(lambda: self.context.api.ledger_persons(database, query),
                  on_success=self._got_persons, on_error=self._failed)

    def _got_persons(self, answer: object) -> None:
        answer = answer if isinstance(answer, dict) else {}
        self.persons = list(answer.get("items") or [])
        total = int(answer.get("total") or 0)
        self.note.setText(f"{format_int(total)} نفر؛ فقط {format_int(len(self.persons))} نفر نشان "
                          "داده شد، جستجو را دقیق‌تر کنید." if total > len(self.persons)
                          else f"{format_int(total)} نفر")
        self.person_table.fill(
            [to_persian_digits(p.get("code")), p.get("name") or "—",
             f"‎{to_persian_digits(p['national_code'])}" if p.get("national_code") else "—",
             f"…{to_persian_digits(p['phone_tail'])}" if p.get("phone_tail") else "—"]
            for p in self.persons)
        self._show_nothing()

    def _show_nothing(self) -> None:
        self._shown_code = None
        self.summary.setText("یک نفر را انتخاب کنید.")
        self.row_table.fill([])

    def _person_selected(self) -> None:
        rows = {index.row() for index in self.person_table.selectionModel().selectedRows()}
        if len(rows) != 1 or min(rows) >= len(self.persons):
            return
        person = self.persons[min(rows)]
        code, database = int(person["code"]), self.database.currentData()
        if code == self._shown_code:
            return
        self._shown_code = code
        self.summary.setText(f"در حال خواندن گردش {person.get('name') or ''}…")
        run_async(lambda: self.context.api.ledger_statement(database, code),
                  on_success=lambda answer: self._got_statement(person, code, answer),
                  on_error=self._failed)

    def _got_statement(self, person: dict, code: int, answer: object) -> None:
        if code != self._shown_code or not isinstance(answer, dict):
            return                          # another person was chosen in the meantime
        self.row_table.fill(
            [to_persian_digits(row.get("date") or ""), row.get("kind") or "",
             to_persian_digits(row.get("doc_no") or ""), row.get("description") or "",
             format_money(row.get("debit") or 0, False), format_money(row.get("credit") or 0, False),
             format_money(row.get("balance") or 0, False), SIDE_FA.get(row.get("side"), "—")]
            for row in answer.get("rows") or [])
        parts = [f"{person.get('name') or ''}، {answer.get('database') or ''}",
                 f"مانده: {format_money(answer.get('balance') or 0)} "
                 f"({SIDE_FA.get(answer.get('side'), '—')})"]
        if answer.get("opening_balance"):
            parts.append(f"ماندهٔ پیش از ردیف‌ها: {format_money(answer['opening_balance'])} "
                         f"({SIDE_FA.get(answer.get('opening_side'), '—')})")
        if answer.get("truncated"):
            parts.append("فقط تازه‌ترین ردیف‌ها نشان داده شده است")
        self.summary.setText("؛ ".join(parts))
