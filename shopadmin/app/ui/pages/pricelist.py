"""صفحهٔ لیست قیمت پخش‌کننده — ردیف‌های PDF، نگاشت به کالا، نادیده گرفتن،
لیست‌های دریافتی (تأیید/رد لیست نگه‌داشته‌شده، بارگذاری دستی PDF) و پراکسی‌های تلگرام.

فقط ردیف‌های نگاشت‌شده به مشتری می‌رسند؛ ردیف نگاشت‌شده یا نادیده‌گرفته در لیست‌های بعدی
هرگز دوباره پرسیده نمی‌شود. از نسخهٔ ۲٫۶٫۲ ردیف‌های تازه خودکار تطبیق داده می‌شوند (همان
ردیف با املای کمی متفاوت، یا رنگ/پارت تازهٔ مدلی که قبلاً نگاشت شده) و با وضعیت «خودکار»
برای بازبینی نشان داده می‌شوند. فایل PDF را می‌توان روی همین صفحه کشید و رها کرد.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...persian import format_int, format_money, format_shamsi, to_persian_digits
from ...permissions import PRICELIST_MANAGE, PROXIES_MANAGE
from .. import theme, widgets
from ..base_page import BasePage

ROW_HEADERS = ("بخش", "مدل", "نوع", "رنگ", "نقد", "روال", "قیمت مشتری (ریال)", "وضعیت", "کالا")
LIST_HEADERS = ("شماره", "تاریخ لیست", "منبع", "وضعیت", "ردیف‌ها", "زمان دریافت", "توضیح")
PROXY_HEADERS = ("میزبان", "پورت", "نوع", "وضعیت", "پایداری", "روز خوب / بررسی", "آخرین اتصال موفق",
                 "الان")

FILTERS = (
    ("unmapped", "نگاشت‌نشده"),
    ("auto", "خودکار (بازبینی)"),
    ("mapped", "نگاشت‌شده"),
    ("ignored", "نادیده"),
    ("all", "همه"),
)
#: Largest PDF accepted (same rule for the button and for drag & drop).
MAX_PDF_BYTES = 10 * 1024 * 1024
LIST_STATUS_FA = {
    "active": "فعال",
    "held": "نگه‌داشته (منتظر تأیید)",
    "rejected": "رد شده",
    "superseded": "قدیمی",
    "failed": "خوانده نشد",
}
LIST_STATUS_COLOR = {"active": "success", "held": "warning", "failed": "danger",
                     "rejected": "danger", "superseded": ""}
SOURCE_FA = {"telegram": "کانال تلگرام", "manual": "بارگذاری دستی"}
PROXY_STATE_FA = {"main": "اصلی", "probation": "آزمایشی", "retired": "کنار گذاشته", "disabled": "غیرفعال"}
OUTCOME_FA = {
    "active": "لیست جدید فعال شد.",
    "held": "لیست نگه داشته شد: تغییر قیمت زیاد یا ردیف‌های گم‌شده. بررسی و تأیید کنید.",
    "failed": "PDF خوانده نشد (قالب ناشناخته). قیمت‌های قبلی فعال ماند.",
    "duplicate": "این فایل قبلاً دریافت شده بود.",
    "older": "این لیست از لیست فعال قدیمی‌تر است و اعمال نشد.",
}


# ---- pure helpers (tested without a window) ----------------------------------------
def row_state(row: dict) -> str:
    action = row.get("action")
    if action in ("map", "ignore") and row.get("auto"):
        return "auto_mapped" if action == "map" else "auto_ignored"
    return "mapped" if action == "map" else "ignored" if action == "ignore" else "unmapped"


ROW_STATE_FA = {"mapped": "نگاشت‌شده", "ignored": "نادیده", "unmapped": "نگاشت‌نشده",
                "auto_mapped": "نگاشت خودکار", "auto_ignored": "نادیدهٔ خودکار"}
ROW_STATE_COLOR = {"mapped": theme.SUCCESS_DARK, "ignored": theme.TEXT_MUTED,
                   "unmapped": theme.WARNING_TEXT, "auto_mapped": theme.PRIMARY,
                   "auto_ignored": theme.PRIMARY}
AUTO_REASON_FA = {"same_row": "همان ردیف با املای دیگر",
                  "same_model": "رنگ یا پارت تازهٔ همین مدل"}


def row_state_fa(row: dict) -> str:
    return ROW_STATE_FA[row_state(row)]


def dropped_pdf(urls) -> Optional[str]:
    """The local PDF among dropped URLs (drag & drop), or ``None``."""
    for url in urls or ():
        path = url.toLocalFile() if hasattr(url, "toLocalFile") else str(url)
        if path and path.lower().endswith(".pdf"):
            return path
    return None


def pdf_price(value) -> str:
    """PDF cell (thousand Toman) for display; empty = «—»."""
    return format_int(value) if value else "—"


def matches(row: dict, text: str) -> bool:
    """Client-side search in model, color and section (Persian/Arabic letters alike)."""
    needle = _norm(text)
    if not needle:
        return True
    haystack = _norm(" ".join(str(row.get(k) or "") for k in
                              ("section", "description", "kind", "color", "color_label")))
    return all(part in haystack for part in needle.split())


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("ي", "ی").replace("ك", "ک").lower().split())


def filter_label(key: str, counts: dict) -> str:
    title = dict(FILTERS)[key]
    count = counts.get(key)
    return f"{title} ({to_persian_digits(count)})" if count is not None else title


class PriceListPage(BasePage):
    title = "لیست قیمت"
    subtitle = "قیمت گوشی‌ها از لیست پخش‌کننده — فقط ردیف‌های نگاشت‌شده به مشتری نمایش داده می‌شوند"

    def build_body(self) -> None:
        self.can_manage = self.context.can(PRICELIST_MANAGE)
        # v2.6.2: a PDF dropped anywhere on the page is uploaded like «بارگذاری PDF».
        self.setAcceptDrops(self.can_manage)
        self.can_proxies = self.context.can(PROXIES_MANAGE)
        self._rows: list[dict] = []
        self._lists: list[dict] = []
        self._proxies: list[dict] = []
        self._counts: dict = {}

        self.banner = widgets.label("", wrap=True)
        self.banner.setVisible(False)
        self.body.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tabs.addTab(self._build_rows_tab(), "ردیف‌ها و نگاشت")
        self.tabs.addTab(self._build_lists_tab(), "لیست‌های دریافتی")
        if self.can_proxies:
            self.tabs.addTab(self._build_proxies_tab(), "پراکسی‌های تلگرام")
        self.tabs.currentChanged.connect(lambda _i: self.load())
        self.body.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------ tabs
    def _build_rows_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)

        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=10)
        self.filter_combo = QComboBox()
        for key, title in FILTERS:
            self.filter_combo.addItem(title, key)
        self.filter_combo.currentIndexChanged.connect(lambda _i: self.load())
        bar.addWidget(self._labeled("نمایش:", self.filter_combo))
        self.section_combo = QComboBox()
        self.section_combo.setMinimumWidth(180)
        self.section_combo.addItem("همهٔ بخش‌ها / برندها", None)
        self.section_combo.currentIndexChanged.connect(lambda _i: self.load())
        bar.addWidget(self._labeled("بخش / برند:", self.section_combo))
        self.row_search = widgets.SearchBox("جستجوی مدل یا رنگ…")
        self.row_search.textChanged.connect(lambda _t: self._render_rows())
        bar.addWidget(self.row_search)
        layout.addWidget(bar_holder)

        panel = widgets.Panel()
        self.rows_table = widgets.DataTable(ROW_HEADERS, selectable_rows=True, key="price_rows")
        self.rows_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rows_table.set_empty_state("ردیفی برای نمایش نیست",
                                        "فیلتر را عوض کنید یا یک لیست PDF بارگذاری کنید.", "file")
        self.rows_table.setMinimumHeight(360)
        self.rows_table.row_activated.connect(lambda _r: self._map_selected())
        panel.body.addWidget(self.rows_table, 1)
        self.rows_summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.rows_summary)

        # A flow layout: six buttons wrap on a narrow window instead of widening it.
        actions_holder = QWidget()
        actions = widgets.FlowLayout(actions_holder, spacing=10)
        self.map_button = widgets.button("نگاشت به کالا…", icon_name="link", variant="primary",
                                         on_click=self._map_selected)
        self.ignore_button = widgets.button(
            "نادیده بگیر (فروش نداریم)", icon_name="eye_off", on_click=self._ignore_selected,
            tooltip="این ردیف‌ها در لیست‌های بعدی هم نگاشت‌نشده حساب نمی‌شوند.")
        self.clear_button = widgets.button("حذف نگاشت / نادیده", icon_name="trash",
                                           on_click=self._clear_selected)
        self.confirm_auto_button = widgets.button(
            "تأیید نگاشت خودکار", icon_name="check", variant="success",
            on_click=self._confirm_selected,
            tooltip="ردیف‌های «خودکار» انتخاب‌شده عادی می‌شوند.")
        self.undo_auto_button = widgets.button(
            "لغو نگاشت خودکار", icon_name="close", on_click=self._undo_selected,
            tooltip="ردیف دوباره «نگاشت‌نشده» می‌شود و دیگر خودکار تطبیق داده نمی‌شود.")
        self.auto_button = widgets.button(
            "تطبیق خودکار", icon_name="refresh", on_click=self._run_auto,
            tooltip="ردیف‌های نگاشت‌نشده را با تصمیم‌های قبلی تطبیق بده.")
        for b in (self.map_button, self.ignore_button, self.clear_button,
                  self.confirm_auto_button, self.undo_auto_button, self.auto_button):
            b.setEnabled(self.can_manage)
            actions.addWidget(b)
        panel.body.addWidget(actions_holder)
        layout.addWidget(panel, 1)
        return tab

    def _build_lists_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        panel = widgets.Panel()
        self.lists_table = widgets.DataTable(LIST_HEADERS, selectable_rows=True, key="price_lists")
        self.lists_table.set_empty_state("هنوز لیستی دریافت نشده",
                                         "لیست‌ها از کانال تلگرام می‌آیند یا با «بارگذاری PDF».",
                                         "file")
        self.lists_table.setMinimumHeight(300)
        panel.body.addWidget(self.lists_table, 1)
        actions = QHBoxLayout()
        self.upload_button = widgets.button("بارگذاری PDF…", icon_name="download",
                                            variant="primary", on_click=self._upload_pdf)
        self.upload_button.setToolTip("یا فایل PDF را روی همین صفحه بکشید و رها کنید.")
        self.approve_button = widgets.button("تأیید لیست نگه‌داشته", icon_name="check",
                                             variant="success", on_click=self._approve_list)
        self.reject_button = widgets.button("رد لیست", icon_name="close", variant="danger",
                                            on_click=self._reject_list)
        for b in (self.upload_button, self.approve_button, self.reject_button):
            b.setEnabled(self.can_manage)
            actions.addWidget(b)
        actions.addStretch(1)
        panel.body.addLayout(actions)
        layout.addWidget(panel, 1)
        return tab

    def _build_proxies_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.addWidget(widgets.label(
            "پراکسی‌ها بر اساس پایداری چندروزه رتبه می‌گیرند. پراکسی تازه چند روز آزمایشی "
            "است؛ پراکسی اصلی فقط بعد از چند روز خرابی پشت‌سرهم کنار گذاشته می‌شود.",
            name="Muted", wrap=True))
        panel = widgets.Panel()
        self.proxy_table = widgets.DataTable(PROXY_HEADERS, selectable_rows=True, key="proxies")
        self.proxy_table.set_empty_state("پراکسی‌ای ثبت نشده",
                                         "یک لینک tg://proxy یا t.me/proxy اضافه کنید.", "wifi")
        self.proxy_table.setMinimumHeight(300)
        panel.body.addWidget(self.proxy_table, 1)
        actions = QHBoxLayout()
        actions.addWidget(widgets.button("افزودن پراکسی…", icon_name="plus", variant="primary",
                                         on_click=self._add_proxy))
        actions.addWidget(widgets.button("فعال / غیرفعال", icon_name="lock",
                                         on_click=self._toggle_proxy))
        actions.addWidget(widgets.button("حذف", icon_name="trash", on_click=self._delete_proxy))
        actions.addStretch(1)
        panel.body.addLayout(actions)
        layout.addWidget(panel, 1)
        return tab

    @staticmethod
    def _labeled(text: str, widget: QWidget) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(widgets.label(text))
        row.addWidget(widget)
        return box

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        index = self.tabs.currentIndex()
        if index == 0:
            self._load_rows()
        elif index == 1:
            self._load_lists()
        else:
            self._load_proxies()

    def _load_rows(self) -> None:
        self.rows_table.set_busy(True)
        filter_key = self.filter_combo.currentData() or "unmapped"
        section = self.section_combo.currentData()
        self.run(lambda: self.context.api.pricelist_rows(filter_key=filter_key, section=section),
                 on_success=self._on_rows, on_error=self._table_error(self.rows_table))

    def _load_lists(self) -> None:
        self.lists_table.set_busy(True)
        self.run(lambda: self.context.api.list_pricelists(),
                 on_success=self._on_lists, on_error=self._table_error(self.lists_table))

    def _load_proxies(self) -> None:
        self.proxy_table.set_busy(True)
        self.run(lambda: self.context.api.list_proxies(),
                 on_success=self._on_proxies, on_error=self._table_error(self.proxy_table))

    def _table_error(self, table):
        def handler(message: str, kind: str) -> None:
            table.set_busy(False)
            table.fill([])
            table.set_error_state(hint=message)
            self.default_error(message, kind)
        return handler

    def _on_rows(self, payload: dict) -> None:
        self.rows_table.set_busy(False)
        self._rows = list(payload.get("rows") or [])
        self._counts = dict(payload.get("counts") or {})
        plist = payload.get("list") or None
        self._update_sections(payload.get("sections") or [])
        self._update_filter_labels()
        self._update_banner(plist)
        self._render_rows()

    def _update_sections(self, sections: list) -> None:
        current = self.section_combo.currentData()
        self.section_combo.blockSignals(True)
        self.section_combo.clear()
        self.section_combo.addItem("همهٔ بخش‌ها / برندها", None)
        for name in sections:
            self.section_combo.addItem(str(name), str(name))
        self.section_combo.setCurrentIndex(max(0, self.section_combo.findData(current)))
        self.section_combo.blockSignals(False)

    def _update_filter_labels(self) -> None:
        for i, (key, _title) in enumerate(FILTERS):
            self.filter_combo.setItemText(i, filter_label(key, self._counts))

    def _update_banner(self, plist: Optional[dict]) -> None:
        if not plist:
            self.banner.setText("هنوز لیست قیمتی دریافت نشده است. از برگهٔ «لیست‌های دریافتی» "
                                "یک PDF بارگذاری کنید.")
            self.banner.setVisible(True)
            return
        status = plist.get("status")
        text = (f"لیست {to_persian_digits(plist.get('list_date') or '')} — "
                f"{LIST_STATUS_FA.get(status, status)}")
        if status == "held":
            text += f"\nدلیل: {plist.get('reason') or '—'}"
        unmapped = self._counts.get("unmapped") or 0
        if unmapped:
            text += f"\n{to_persian_digits(unmapped)} ردیف هنوز نگاشت یا نادیده نشده است."
        self.banner.setText(text)
        color = theme.WARNING_TEXT if status == "held" or unmapped else theme.SUCCESS_DARK
        self.banner.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.banner.setVisible(True)

    def _visible_rows(self) -> list[dict]:
        text = self.row_search.text()
        return [r for r in self._rows if matches(r, text)]

    def _render_rows(self) -> None:
        rows = self._visible_rows()
        table = self.rows_table
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(0)
            for row in rows:
                i = table.rowCount()
                table.insertRow(i)
                table.set_cell(i, 0, str(row.get("section") or "—"))
                table.set_cell(i, 1, str(row.get("description") or "—"), bold=True)
                table.set_cell(i, 2, str(row.get("kind") or "—"))
                color = str(row.get("color") or "—")
                if row.get("color_label"):
                    color = f"{color} ← {row['color_label']}"
                table.set_cell(i, 3, color)
                table.set_cell(i, 4, pdf_price(row.get("naghd")))
                table.set_cell(i, 5, pdf_price(row.get("raval")))
                price = row.get("price_rial")
                table.set_cell(i, 6, format_money(price) if price else "ناموجود",
                               color=None if price else theme.DANGER)
                state = row_state(row)
                table.set_cell(i, 7, row_state_fa(row), bold=True, color=ROW_STATE_COLOR[state],
                               tooltip=AUTO_REASON_FA.get(str(row.get("auto_reason") or ""), ""))
                table.set_cell(i, 8, to_persian_digits(row["kala_code"])
                               if row.get("kala_code") else "—")
        finally:
            table.setUpdatesEnabled(True)
        table._refresh_states()
        self.rows_summary.setText(f"{format_int(len(rows))} ردیف")

    def _on_lists(self, lists: list) -> None:
        self.lists_table.set_busy(False)
        self._lists = list(lists or [])
        table = self.lists_table
        table.setRowCount(0)
        for item in self._lists:
            i = table.rowCount()
            table.insertRow(i)
            status = item.get("status") or ""
            table.set_cell(i, 0, to_persian_digits(item.get("id")))
            table.set_cell(i, 1, to_persian_digits(item.get("list_date") or "—"), bold=True)
            table.set_cell(i, 2, SOURCE_FA.get(item.get("source"), item.get("source") or ""))
            table.set_widget(i, 3, widgets.pill_cell(widgets.StatusPill(
                LIST_STATUS_FA.get(status, status), LIST_STATUS_COLOR.get(status, ""))))
            table.set_cell(i, 4, format_int(item.get("row_count") or 0))
            table.set_cell(i, 5, format_shamsi(item.get("created_at")))
            table.set_cell(i, 6, str(item.get("reason") or ""))
        table._refresh_states()

    def _on_proxies(self, proxies: list) -> None:
        self.proxy_table.set_busy(False)
        self._proxies = list(proxies or [])
        table = self.proxy_table
        table.setRowCount(0)
        for p in self._proxies:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, str(p.get("host") or ""), bold=True)
            table.set_cell(i, 1, to_persian_digits(p.get("port")))
            table.set_cell(i, 2, str(p.get("kind") or ""))
            table.set_cell(i, 3, PROXY_STATE_FA.get(p.get("state"), p.get("state") or ""))
            table.set_cell(i, 4, to_persian_digits(f"{round(float(p.get('stability') or 0) * 100)}٪"))
            table.set_cell(i, 5, to_persian_digits(
                f"{p.get('good_days') or 0} / {p.get('checked_days') or 0}"))
            table.set_cell(i, 6, format_shamsi(p.get("last_ok_at")) if p.get("last_ok_at") else "—")
            failing = bool(p.get("failing_now"))
            table.set_cell(i, 7, "قطع" if failing else "سالم",
                           color=theme.DANGER if failing else theme.SUCCESS_DARK, bold=True)
        table._refresh_states()

    # ------------------------------------------------------------------ actions
    def _selected(self, table, items: list[dict]) -> list[dict]:
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        return [items[r] for r in rows if 0 <= r < len(items)]

    def _selected_rows(self) -> list[dict]:
        return self._selected(self.rows_table, self._visible_rows())

    def _map_selected(self) -> None:
        if not self.can_manage:
            return
        rows = self._selected_rows()
        if len(rows) != 1:
            self.notify_warning("برای نگاشت یک ردیف را انتخاب کنید.")
            return
        dialog = MapRowDialog(self.context, rows[0], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row, code, label = rows[0], dialog.kala_code, dialog.color_label
        self.run(lambda: self.context.api.map_price_row(row["row_key"], code, label),
                 on_success=lambda _r: (self.notify_success("نگاشت ذخیره شد."), self._load_rows()))

    def _ignore_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self.notify_warning("ردیف‌هایی را که نمی‌فروشید انتخاب کنید.")
            return
        message = (f"{to_persian_digits(len(rows))} ردیف نادیده گرفته شود؟ این ردیف‌ها به مشتری "
                   "نمایش داده نمی‌شوند و در لیست‌های بعدی هم نگاشت‌نشده حساب نمی‌شوند.")
        if not widgets.confirm(self, "نادیده گرفتن ردیف‌ها", message, confirm_text="نادیده بگیر"):
            return
        keys = [r["row_key"] for r in rows]
        self.run(lambda: self.context.api.ignore_price_rows(keys),
                 on_success=lambda _r: (self.notify_success("ردیف‌ها نادیده گرفته شدند."),
                                        self._load_rows()))

    def _clear_selected(self) -> None:
        rows = [r for r in self._selected_rows() if r.get("mapping_id")]
        if not rows:
            self.notify_warning("ردیف نگاشت‌شده یا نادیده‌ای انتخاب نشده است.")
            return
        if not widgets.confirm(self, "حذف نگاشت",
                               f"نگاشت {to_persian_digits(len(rows))} ردیف حذف شود؟ "
                               "ردیف‌های نگاشت‌شده دیگر به مشتری نمایش داده نمی‌شوند.",
                               confirm_text="حذف", kind="warning"):
            return
        ids = [int(r["mapping_id"]) for r in rows]

        def work():
            for mapping_id in ids:
                self.context.api.delete_price_mapping(mapping_id)

        self.run(work, on_success=lambda _r: (self.notify_success("نگاشت حذف شد."),
                                              self._load_rows()))

    # ---- v2.6.2: automatic mappings ------------------------------------------
    def _auto_rows(self) -> list[dict]:
        rows = [r for r in self._selected_rows() if r.get("mapping_id") and r.get("auto")]
        if not rows:
            self.notify_warning("ردیف «خودکار» انتخاب نشده است.")
        return rows

    def _confirm_selected(self) -> None:
        ids = [int(r["mapping_id"]) for r in self._auto_rows()]
        if not ids:
            return

        def work():
            for mapping_id in ids:
                self.context.api.confirm_price_mapping(mapping_id)

        self.run(work, on_success=lambda _r: (self.notify_success("نگاشت خودکار تأیید شد."),
                                              self._load_rows()))

    def _undo_selected(self) -> None:
        ids = [int(r["mapping_id"]) for r in self._auto_rows()]
        if not ids:
            return

        def work():
            for mapping_id in ids:
                self.context.api.delete_price_mapping(mapping_id)

        self.run(work, on_success=lambda _r: (self.notify_success(
            "نگاشت خودکار لغو شد؛ این ردیف‌ها را دستی تصمیم بگیرید."), self._load_rows()))

    def _run_auto(self) -> None:
        def done(result: dict) -> None:
            count = int((result or {}).get("auto_mapped") or 0)
            self.notify_success(f"{to_persian_digits(count)} ردیف خودکار تطبیق داده شد."
                                if count else "ردیف تازه‌ای برای تطبیق خودکار نبود.")
            self._load_rows()

        self.run(lambda: self.context.api.auto_match_prices(), on_success=done)

    # ---- upload: the button and drag & drop ------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.can_manage and dropped_pdf(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        path = dropped_pdf(event.mimeData().urls()) if self.can_manage else None
        if not path:
            event.ignore()
            return
        event.acceptProposedAction()
        self.upload_pdf_file(path)

    def _upload_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب لیست قیمت (PDF)", "",
                                              "PDF (*.pdf)")
        if not path:
            return
        self.upload_pdf_file(path)

    def upload_pdf_file(self, path: str) -> None:
        """The one upload path of the button and of a dropped file."""
        if not self.can_manage:
            return
        try:
            data = Path(path).read_bytes()
        except OSError:
            self.notify_error("فایل خوانده نشد.")
            return
        if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
            self.notify_error("فایل باید PDF و کمتر از ۱۰ مگابایت باشد.")
            return
        name = Path(path).name

        def done(result: dict) -> None:
            outcome = str(result.get("outcome") or "")
            text = OUTCOME_FA.get(outcome, outcome)
            auto = int(result.get("auto_mapped") or 0)
            if auto:
                text += (f"\n{to_persian_digits(auto)} ردیف خودکار نگاشت شد؛ "
                         "در فیلتر «خودکار» بازبینی کنید.")
            if outcome == "active":
                self.notify_success(text)
            else:
                widgets.info(self, "نتیجهٔ بارگذاری", text,
                             kind="warning" if outcome in ("held", "failed") else "info",
                             detail="\n".join(result.get("reasons") or []))
            self.load()

        self.run(lambda: self.context.api.upload_pricelist(data, name), on_success=done,
                 busy_message="در حال خواندن لیست…")

    def _held_selection(self) -> Optional[dict]:
        chosen = self._selected(self.lists_table, self._lists)
        if len(chosen) != 1 or chosen[0].get("status") != "held":
            self.notify_warning("یک لیست «نگه‌داشته» را انتخاب کنید.")
            return None
        return chosen[0]

    def _approve_list(self) -> None:
        plist = self._held_selection()
        if plist is None:
            return
        if not widgets.confirm(self, "تأیید لیست",
                               "قیمت‌های این لیست برای مشتری‌ها فعال شود؟",
                               detail=str(plist.get("reason") or ""), confirm_text="فعال کن"):
            return
        self.run(lambda: self.context.api.approve_pricelist(plist["id"]),
                 on_success=lambda _r: (self.notify_success("لیست فعال شد."), self.load()))

    def _reject_list(self) -> None:
        plist = self._held_selection()
        if plist is None:
            return
        if not widgets.confirm(self, "رد لیست", "این لیست رد شود؟ قیمت‌های فعلی می‌ماند.",
                               confirm_text="رد کن", kind="warning"):
            return
        self.run(lambda: self.context.api.reject_pricelist(plist["id"]),
                 on_success=lambda _r: (self.notify_success("لیست رد شد."), self.load()))

    def _add_proxy(self) -> None:
        dialog = AddProxyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        link, main = dialog.link, dialog.main
        self.run(lambda: self.context.api.add_proxy(link, main),
                 on_success=lambda _r: (self.notify_success("پراکسی اضافه شد."),
                                        self._load_proxies()))

    def _one_proxy(self) -> Optional[dict]:
        chosen = self._selected(self.proxy_table, self._proxies)
        if len(chosen) != 1:
            self.notify_warning("یک پراکسی را انتخاب کنید.")
            return None
        return chosen[0]

    def _toggle_proxy(self) -> None:
        proxy = self._one_proxy()
        if proxy is None:
            return
        state = "probation" if proxy.get("state") in ("disabled", "retired") else "disabled"
        self.run(lambda: self.context.api.set_proxy_state(proxy["id"], state),
                 on_success=lambda _r: self._load_proxies())

    def _delete_proxy(self) -> None:
        proxy = self._one_proxy()
        if proxy is None:
            return
        if not widgets.confirm(self, "حذف پراکسی", f"پراکسی {proxy.get('host')} حذف شود؟",
                               confirm_text="حذف", kind="warning"):
            return
        self.run(lambda: self.context.api.delete_proxy(proxy["id"]),
                 on_success=lambda _r: self._load_proxies())


class MapRowDialog(QDialog):
    """نگاشت یک ردیف PDF به کالای حسابداری + نام رنگی که مشتری می‌بیند."""

    def __init__(self, context, row: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.row = row
        self.kala_code: int = int(row.get("kala_code") or 0)
        self.color_label: str = str(row.get("color_label") or "")
        self._found: list[dict] = []

        self.setWindowTitle("نگاشت ردیف لیست قیمت")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("نگاشت ردیف به کالا", size=14, bold=True))

        info = widgets.Panel("ردیف لیست پخش‌کننده")
        form = QFormLayout()
        form.addRow(widgets.label("بخش"), widgets.label(str(row.get("section") or "—")))
        form.addRow(widgets.label("مدل"), widgets.label(str(row.get("description") or "—"), bold=True))
        form.addRow(widgets.label("نوع"), widgets.label(str(row.get("kind") or "—")))
        form.addRow(widgets.label("رنگ"), widgets.label(str(row.get("color") or "—")))
        price = row.get("price_rial")
        form.addRow(widgets.label("قیمت مشتری"),
                    widgets.label(format_money(price) if price else "ناموجود"))
        info.body.addLayout(form)
        root.addWidget(info)

        pick = widgets.Panel("کالای فروشگاه")
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("نام کالا در حسابداری…")
        self.search.setText(str(row.get("description") or "").split(" ")[0])
        self.search.returnPressed.connect(self._search)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(widgets.button("جستجو", icon_name="search", on_click=self._search))
        pick.body.addLayout(search_row)
        self.results = QListWidget()
        self.results.setMinimumHeight(160)
        self.results.currentItemChanged.connect(self._picked)
        pick.body.addWidget(self.results)
        code_row = QHBoxLayout()
        code_row.addWidget(widgets.label("کد کالا:"))
        self.code_input = QSpinBox()
        self.code_input.setRange(0, 2_000_000_000)
        self.code_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code_input.setSpecialValueText("—")
        self.code_input.setValue(self.kala_code)
        code_row.addWidget(self.code_input)
        code_row.addStretch(1)
        pick.body.addLayout(code_row)
        color_row = QHBoxLayout()
        color_row.addWidget(widgets.label("نام رنگ برای مشتری:"))
        self.color_input = QLineEdit(self.color_label or "")
        self.color_input.setPlaceholderText(str(row.get("color") or ""))
        self.color_input.setMaxLength(60)
        color_row.addWidget(self.color_input, 1)
        pick.body.addLayout(color_row)
        pick.body.addWidget(widgets.label(
            "چند رنگِ یک مدل را به یک کالا نگاشت کنید؛ ربات رنگ‌ها را نشان می‌دهد و قیمت "
            "را بعد از انتخاب رنگ اعلام می‌کند. خالی = همان رنگ لیست.", name="Muted", wrap=True))
        root.addWidget(pick)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        buttons.addWidget(widgets.button("ذخیره", icon_name="check", variant="primary",
                                         on_click=self._accept))
        root.addLayout(buttons)

    def _search(self) -> None:
        query = self.search.text().strip()
        if not query:
            return
        try:
            payload = self.context.api.list_products(query=query, in_stock=False, page_size=30)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(str(exc))
            return
        self._found = list(payload.get("items") or [])
        self.results.clear()
        for product in self._found:
            item = QListWidgetItem(
                f"{to_persian_digits(product.get('code'))} — {product.get('name') or ''}")
            item.setData(Qt.ItemDataRole.UserRole, int(product.get("code")))
            self.results.addItem(item)
        if not self._found:
            self.error_label.setText("کالایی پیدا نشد؛ کد کالا را مستقیم وارد کنید.")

    def _picked(self, item, _previous=None) -> None:
        if item is not None:
            self.code_input.setValue(int(item.data(Qt.ItemDataRole.UserRole)))

    def _accept(self) -> None:
        code = int(self.code_input.value())
        if code <= 0:
            self.error_label.setText("کالای فروشگاه را انتخاب کنید یا کد آن را بنویسید.")
            return
        self.kala_code = code
        self.color_label = self.color_input.text().strip()
        self.accept()


class AddProxyDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.link = ""
        self.main = False
        self.setWindowTitle("افزودن پراکسی تلگرام")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(widgets.label("لینک پراکسی MTProto (tg://proxy… یا https://t.me/proxy…):",
                                     wrap=True))
        self.input = QLineEdit()
        self.input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        root.addWidget(self.input)
        self.main_check = QCheckBox("مستقیم در فهرست اصلی (پراکسی مطمئن؛ بدون دورهٔ آزمایشی)")
        root.addWidget(self.main_check)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        buttons.addWidget(widgets.button("افزودن", icon_name="plus", variant="primary",
                                         on_click=self._accept))
        root.addLayout(buttons)

    def _accept(self) -> None:
        text = self.input.text().strip()
        if "proxy?" not in text or "server=" not in text or "secret=" not in text:
            self.error_label.setText("لینک باید server، port و secret داشته باشد.")
            return
        self.link = text
        self.main = self.main_check.isChecked()
        self.accept()
