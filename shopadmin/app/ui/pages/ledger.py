"""v2.18.2 «گردش سال‌های قبل» (فقط‌خواندنی).

همهٔ اشخاص «سازه حساب» (نه فقط مشتریان ربات و سایت) در هر پایگاه‌دادهٔ سال مالی که سرور اجازهٔ
خواندنش را دارد، با جستجوی نام، تلفن یا کد ملی و گردش حساب هر شخص. چیزی نوشته نمی‌شود و خواندن و
نوشتن اصلی برنامه همان پایگاه‌دادهٔ «تنظیمات سرور» می‌ماند.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

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



def _table_item(text: str) -> QTableWidgetItem:
    """Read-only table cell with the given text."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item
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
        self.detailed: bool = False
        self._statement_rows: list[dict] = []
        #: ("data", statement index) or ("detail", statement index), per visual row
        self._visual: list[tuple[str, int]] = []
        #: statement index -> visual row holding its collapsible line detail
        self._invoice_detail_row: dict[int, int] = {}
        #: statement index -> current detail cell widget (rebuilt on every refill)
        self._detail_target: dict[int, QWidget] = {}
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
        self.detail_switch = widgets.button("خلاصه", variant="ghost")
        self.detail_switch.setCheckable(True)
        self.detail_switch.setToolTip(
            "«خلاصه»: فقط ردیف‌های گردش. «تفصیلی»: زیر هر فاکتور، ردیف‌های آن "
            "فاکتور (کالا، تعداد، قیمت واحد، تخفیف و مبلغ ردیف) را باز و بسته می‌کند.")
        self.detail_switch.toggled.connect(self._detail_toggled)
        bar.addWidget(self.detail_switch)
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
        self.row_table.itemPressed.connect(self._on_row_pressed)
        self.body.addWidget(self.row_table, 3)

    def load(self) -> None:
        run_async(self.context.api.ledger_databases, on_success=self._got_databases,
                  on_error=self._failed)

    def _detail_toggled(self, detailed: bool) -> None:
        self.detailed = bool(detailed)
        self.detail_switch.setText("تفصیلی" if self.detailed else "خلاصه")
        if self._shown_code is not None:
            self._refresh_statement()

    def _refresh_statement(self) -> None:
        code = self._shown_code
        person = next((p for p in self.persons if int(p["code"]) == code), None)
        if person is None:
            return
        self.summary.setText(f"در حال خواندن گردش {person.get('name') or ''}…")
        run_async(lambda: self.context.api.ledger_statement(self.database.currentData(), code),
                  on_success=lambda answer, p=person, c=code: self._got_statement(p, c, answer),
                  on_error=self._failed)

    def _on_row_pressed(self, index) -> None:
        if not self.detailed:
            return
        vr = index.row()
        if vr < 0 or vr >= len(self._visual):
            return
        kind, si = self._visual[vr]
        if kind != "data":
            return                          # clicked on a detail row: do nothing
        row = self._statement_rows[si]
        if row.get("kind") != "f" or not str(row.get("doc_no") or "").strip():
            return                          # not an invoice row: nothing to show
        dvr = self._invoice_detail_row.get(si)
        if dvr is None:
            return
        if self.row_table.isRowHidden(dvr):
            cell = self.row_table.cellWidget(dvr, 0)
            if cell is not None:
                self.row_table.setRowHeight(dvr, cell.sizeHint().height() + 8)
            self.row_table.setRowHidden(dvr, False)
        else:
            self.row_table.setRowHidden(dvr, True)

    @staticmethod
    def _numfact_of(row: dict) -> int | None:
        try:
            return int(str(row.get("doc_no") or "").strip())
        except ValueError:
            return None

    def _got_invoice_lines(self, si: int, answer: object, code: int) -> None:
        if code != self._shown_code:
            return                          # another person was chosen meanwhile
        container = self._detail_target.get(si)
        if container is None:
            return                          # the statement was refilled meanwhile
        layout = container.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        lines = list((answer or {}).get("lines") or [])
        table = QTableWidget(len(lines) + 1, 6)
        table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        table.setHorizontalHeaderLabels(["ردیف", "کالا", "تعداد", "قیمت واحد", "تخفیف",
                                         "مبلغ ردیف"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = table.horizontalHeader()
        for c in range(5):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for r, line in enumerate(lines):
            values = [
                to_persian_digits(line.get("radif", "")),
                str(line.get("name") or ""),
                self._qty_text(line.get("qty", 0)),
                format_money(line.get("unit_price", 0), False),
                format_money(line.get("discount", 0), False),
                format_money(line.get("line_total", 0), False),
            ]
            table.setRowHeight(r, self.row_table.ROW_HEIGHT)
            for c, text in enumerate(values):
                table.setItem(r, c, _table_item(text))
        last = len(lines)
        total = float((answer or {}).get("total") or 0)
        table.setRowHeight(last, self.row_table.ROW_HEIGHT)
        for c, text in enumerate(["", "", "", "", "مجموع فاکتور:",
                                  format_money(total, False)]):
            table.setItem(last, c, _table_item(text))
        layout.addWidget(table)
        table.setFixedHeight(table.sizeHint().height() + 6)
        container.adjustSize()
        dvr = self._invoice_detail_row.get(si)
        if dvr is not None and not self.row_table.isRowHidden(dvr):
            self.row_table.setRowHeight(dvr, container.sizeHint().height() + 8)

    def _detail_error(self, _message: str, si: int = -1) -> None:
        container = self._detail_target.get(si)
        if container is None:
            return
        layout = container.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        layout.addWidget(widgets.label("خواندن ردیف‌های فاکتور شکست خورد", name="Muted"))

    @staticmethod
    def _qty_text(value) -> str:
        try:
            q = float(value or 0)
        except (TypeError, ValueError):
            return "۰"
        if q == int(q):
            return to_persian_digits(int(q))
        return to_persian_digits(f"{q:g}")

    def _detail_cell(self, si: int, numfact: int | None) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        waiting = widgets.label("در حال خواندن ردیف‌های فاکتور…", name="Muted", wrap=True)
        layout.addWidget(waiting)
        self._detail_target[si] = container
        database = self.database.currentData()
        code = self._shown_code
        if numfact is None:
            waiting.setText("شماره فاکتور نامعتبر است")
            return container
        run_async(lambda: self.context.api.ledger_invoice_lines(database, code, numfact),
                  on_success=lambda answer, s=si, c=code: self._got_invoice_lines(s, answer, c),
                  on_error=lambda _message, s=si: self._detail_error(s))
        return container
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
        self._statement_rows = list(answer.get("rows") or [])
        self._visual = []
        self._invoice_detail_row = {}
        self._detail_target = {}
        self.row_table.setUpdatesEnabled(False)
        try:
            self.row_table.setRowCount(0)
            for si, row in enumerate(self._statement_rows):
                self._visual.append(("data", si))
                vr = self.row_table.rowCount()
                self.row_table.insertRow(vr)
                self.row_table.setItem(vr, 0, _table_item(to_persian_digits(row.get("date") or "")))
                self.row_table.setItem(vr, 1, _table_item(row.get("kind") or ""))
                self.row_table.setItem(vr, 2, _table_item(to_persian_digits(row.get("doc_no") or "")))
                self.row_table.setItem(vr, 3, _table_item(row.get("description") or ""))
                self.row_table.setItem(vr, 4, _table_item(format_money(row.get("debit") or 0, False)))
                self.row_table.setItem(vr, 5, _table_item(format_money(row.get("credit") or 0, False)))
                self.row_table.setItem(vr, 6, _table_item(format_money(row.get("balance") or 0, False)))
                self.row_table.setItem(vr, 7, _table_item(SIDE_FA.get(row.get("side"), "—")))
                if self.detailed and row.get("kind") == "f" and row.get("doc_no"):
                    self._visual.append(("detail", si))
                    dvr = self.row_table.rowCount()
                    self.row_table.insertRow(dvr)
                    self.row_table.setRowHidden(dvr, True)
                    self.row_table.setCellWidget(dvr, 0,
                                                 self._detail_cell(si, self._numfact_of(row)))
                    self.row_table.setSpan(dvr, 0, 1, self.row_table.columnCount())
                    self._invoice_detail_row[si] = dvr
        finally:
            self.row_table.setUpdatesEnabled(True)
        parts = [f"{person.get('name') or ''}، {answer.get('database') or ''}",
                 f"مانده: {format_money(answer.get('balance') or 0)} "
                 f"({SIDE_FA.get(answer.get('side'), '—')})"]
        if answer.get("opening_balance"):
            parts.append(f"ماندهٔ پیش از ردیف‌ها: {format_money(answer['opening_balance'])} "
                         f"({SIDE_FA.get(answer.get('opening_side'), '—')})")
        if answer.get("truncated"):
            parts.append("فقط تازه‌ترین ردیف‌ها نشان داده شده است")
        self.summary.setText("؛ ".join(parts))
