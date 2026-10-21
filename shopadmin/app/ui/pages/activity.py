"""صفحهٔ «گزارش فعالیت» (نسخهٔ ۲٫۸٫۰؛ ۲٫۸٫۳: غیرمدیر فقط کارهای خودش).

چه کسی، چه کاری، روی کدام سفارش / مشتری / درخواست و چه زمانی انجام داد:
تأیید مشتری، تأیید یا رد رسید، ارسال، لغو، پاسخ، برداشتن و ارجاع کار.
فیلتر: کاربر، مشتری و بازهٔ تاریخ (شمسی). سرور این فهرست را فقط به مدیر می‌دهد.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from PySide6.QtWidgets import QComboBox, QWidget

from ...activity import actor_fa, sentence, target_fa
from ...persian import format_datetime_shamsi, to_persian_digits
from .. import widgets
from ..base_page import BasePage
from ..widgets_shamsi import ShamsiRangePicker

HEADERS = ("زمان", "کاربر", "کار", "مورد", "مشتری")
#: Iran time for the day bounds of the date filter.
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def day_bounds(start: date, end: date) -> tuple[str, str]:
    """[start 00:00, end+1 00:00) Iran time as UTC ISO strings (the server compares)."""
    begin = datetime.combine(start, time(0, 0), tzinfo=TEHRAN)
    finish = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=TEHRAN)
    return (begin.astimezone(timezone.utc).isoformat(timespec="seconds"),
            finish.astimezone(timezone.utc).isoformat(timespec="seconds"))


class ActivityPage(BasePage):
    title = "گزارش فعالیت"
    subtitle = "چه کسی، چه کاری، روی کدام سفارش یا مشتری و چه زمانی"
    help_text = ("کارهای انجام‌شده: تأیید مشتری و رسید، ارسال، لغو، پاسخ، برداشتن و ارجاع "
                 "کار. مدیر کارهای همه را می‌بیند و بقیه فقط کارهای خودشان را. با فیلترها "
                 "مشتری یا بازهٔ تاریخ را انتخاب کنید.")
    auto_refreshable = True

    def build_body(self) -> None:
        filters_holder = QWidget()
        filters = widgets.FlowLayout(filters_holder, spacing=10)
        principal = self.context.principal
        #: v2.8.3: a user who is not a manager sees only their own actions (the
        #: server enforces it); no «کاربر» filter and no list of colleagues
        self.own_only = not (principal is not None and principal.is_manager)
        self.user_caption = widgets.label("کاربر:", name="Muted")
        filters.addWidget(self.user_caption)
        self.user_combo = QComboBox()
        self.user_combo.addItem("همهٔ کاربران", None)
        self.user_combo.setMinimumWidth(170)
        filters.addWidget(self.user_combo)
        self.user_caption.setVisible(not self.own_only)
        self.user_combo.setVisible(not self.own_only)
        filters.addWidget(widgets.label("مشتری:", name="Muted"))
        self.customer_combo = QComboBox()
        self.customer_combo.addItem("همهٔ مشتریان", None)
        self.customer_combo.setMinimumWidth(190)
        filters.addWidget(self.customer_combo)
        self.range_picker = ShamsiRangePicker()
        filters.addWidget(self.range_picker)
        self.body.addWidget(filters_holder)
        for combo in (self.user_combo, self.customer_combo):
            combo.currentIndexChanged.connect(lambda _i: self.load())
        self.range_picker.changed.connect(self.load)

        panel = widgets.Panel()
        self.table = widgets.DataTable(HEADERS, key="activity_v280", keep_columns=(0,))
        self.table.set_empty_state("فعالیتی در این بازه نیست", "فیلترها را عوض کنید.", "inbox")
        self.table.setMinimumHeight(360)
        panel.body.addWidget(self.table, 1)
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)
        self.rows: list[dict] = []
        self._filters_loaded = False

    # ------------------------------------------------------------------ data
    def _load_filters(self) -> None:
        self._filters_loaded = True
        api = self.context.api

        own_only = self.own_only

        def work():
            staff = [] if own_only else api.list_staff()
            customers = api.list_customers()
            return staff, customers

        self.run(work, on_success=self._filters_ready, on_error=lambda _m, _k: None)

    def _filters_ready(self, result) -> None:
        staff, customers = result
        for combo in (self.user_combo, self.customer_combo):
            combo.blockSignals(True)
        for row in staff or []:
            self.user_combo.addItem(str(row.get("full_name") or row.get("username") or ""),
                                    int(row["id"]))
        for row in customers or []:
            label = str(row.get("name") or "").strip() or f"مشتری {to_persian_digits(row['id'])}"
            self.customer_combo.addItem(label, int(row["id"]))
        for combo in (self.user_combo, self.customer_combo):
            combo.blockSignals(False)

    def query(self) -> dict:
        start, end = self.range_picker.range()
        date_from, date_to = day_bounds(start, end)
        return {"staff_id": None if self.own_only else self.user_combo.currentData(),
                "customer_id": self.customer_combo.currentData(),
                "date_from": date_from, "date_to": date_to}

    def load(self) -> None:
        if not self._filters_loaded:
            self._load_filters()
        params = self.query()
        self.table.set_busy(True)
        self.run(lambda: self.context.api.activity(**params), on_success=self._loaded,
                 on_error=lambda m, _k: (self.table.set_busy(False), self.show_table_error(m)))

    def _loaded(self, rows) -> None:
        self.rows = [r for r in (rows or []) if isinstance(r, dict)]
        self.table.set_busy(False)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for entry in self.rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, format_datetime_shamsi(entry.get("ts")))
                self.table.set_cell(row, 1, actor_fa(entry), bold=True)
                self.table.set_cell(row, 2, sentence(entry, with_actor=False))
                self.table.set_cell(row, 3, target_fa(entry))
                self.table.set_cell(row, 4, str(entry.get("customer_name") or "—"))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        self.summary.setText(f"{to_persian_digits(len(self.rows))} فعالیت")
