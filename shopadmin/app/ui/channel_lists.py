"""v2.14.0 «لیست‌های دریافتی» › لیست کانال‌های دیگر.

لیست ابریشمی خودکار پایهٔ قیمت ربات می‌ماند. فایل‌ها و پیام‌های «کانال قیمت دیگر» (PDF، عکس،
Excel، متن) با نام کانال خوانده و نگه داشته می‌شوند. ردیف نامطمئن هرگز به کار نمی‌رود؛ در
«ردیف‌ها…» عکس بریدهٔ هر ردیف کنار مقدار خوانده‌شده دیده می‌شود. مدیر می‌تواند یک لیست (و ستون
قیمت کم / زیاد) را تا یک زمان یا پایان امروز پایه کند؛ بعد خودکار به ابریشمی برمی‌گردد. لیست
عکسی فقط پس از «تأیید لیست عکسی» پایه می‌شود. با لیست ابریشمی مقایسه نمی‌شود.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QLabel,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..persian import format_int, format_shamsi, to_persian_digits
from . import theme, widgets

HEADERS = ("کانال", "نوع", "زمان", "ردیف مطمئن", "وضعیت", "پایه")
KIND_FA = {"pdf": "PDF", "image": "عکس", "excel": "Excel", "text": "متن"}
STATE_FA = {"ok": "مطمئن", "doubtful": "نامطمئن (به کار نمی‌رود)", "call": "تماس بگیرید",
            "unavailable": "ناموجود (***)"}
MAX_CROPS = 80


def basis_text(basis: Optional[dict], lists: list[dict]) -> str:
    if not basis:
        return "پایهٔ قیمت ربات: لیست ابریشمی (خودکار)."
    item = next((i for i in lists if i.get("id") == basis.get("list_id")), {})
    name = item.get("channel_title") or item.get("channel") or "کانال دیگر"
    column = "قیمت زیاد" if basis.get("column") == "max" else "قیمت کم"
    return (f"پایهٔ قیمت ربات اکنون: «{name}» ({column}) تا {format_shamsi(basis.get('until'))}؛ "
            "بعد خودکار به ابریشمی برمی‌گردد. در این مدت مشتری فقط «درخواست خرید» می‌دهد.")


class ChannelListsPanel(widgets.Panel):
    def __init__(self, page) -> None:
        super().__init__("لیست کانال‌های دیگر")
        self.page = page
        self._lists: list[dict] = []
        self._basis: Optional[dict] = None
        self.body.addWidget(widgets.label(
            "کانال‌هایی که در «تنظیمات سرور فروشگاه» نقش «کانال قیمت دیگر» دارند فقط خوانده و "
            "نگه داشته می‌شوند. پایهٔ ربات خودکار ابریشمی است؛ هیچ مقایسه‌ای با ابریشمی انجام نمی‌شود.",
            name="Muted", wrap=True))
        self.basis_label = widgets.label("", bold=True, wrap=True)
        self.body.addWidget(self.basis_label)
        self.table = widgets.DataTable(HEADERS, selectable_rows=True, key="channel_lists")
        self.table.set_empty_state("هنوز لیستی از کانال دیگری نیست",
                                   "نقش «کانال قیمت دیگر» را در تنظیمات سرور به کانالی بدهید.", "file")
        self.table.setMinimumHeight(220)
        self.table.row_activated.connect(lambda _r: self._show_rows())
        self.body.addWidget(self.table, 1)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=10)
        self.rows_button = widgets.button("ردیف‌ها…", icon_name="eye", on_click=self._show_rows)
        self.approve_button = widgets.button("تأیید لیست عکسی", icon_name="check",
                                             on_click=self._approve)
        self.basis_button = widgets.button("پایهٔ قیمت موقت…", icon_name="clock",
                                           variant="primary", on_click=self._make_basis)
        self.back_button = widgets.button("برگشت به ابریشمی", icon_name="refresh",
                                          on_click=self._clear_basis)
        for b in (self.basis_button, self.rows_button, self.approve_button, self.back_button):
            flow.addWidget(b)
        self.body.addWidget(holder)
        self.table.itemSelectionChanged.connect(self._sync)

    # ---- data ----------------------------------------------------------------------
    def load(self) -> None:
        self.page.run(lambda: self.page.context.api.channel_lists(), on_success=self._fill,
                      on_error=lambda *_a: self.table.set_error_state())

    def _fill(self, data: dict) -> None:
        self._lists = list((data or {}).get("lists") or [])
        self._basis = (data or {}).get("basis")
        table = self.table
        table.setRowCount(0)
        for item in self._lists:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, item.get("channel_title") or item.get("channel") or "—", bold=True)
            table.set_cell(i, 1, KIND_FA.get(item.get("kind"), str(item.get("kind") or "")))
            table.set_cell(i, 2, format_shamsi(item.get("posted_at") or item.get("created_at")))
            table.set_cell(i, 3, f"{format_int(item.get('usable') or 0)} از "
                                 f"{format_int(item.get('total') or 0)}")
            state = "خوانده شد" if item.get("status") == "read" else \
                (item.get("reason") or "خوانده نشد")
            if item.get("kind") == "image":
                state += " — تأیید شده" if item.get("approved_at") else " — منتظر تأیید"
            table.set_cell(i, 4, state, tooltip=item.get("reason") or state)
            table.set_cell(i, 5, "پایهٔ فعلی" if item.get("is_basis") else "—",
                           bold=bool(item.get("is_basis")))
            table.set_row_key(i, item.get("id"))
        table._refresh_states()
        self.basis_label.setText(basis_text(self._basis, self._lists))
        self._sync()

    def _selected(self) -> Optional[dict]:
        model = self.table.selectionModel()
        rows = sorted({i.row() for i in model.selectedRows()}) if model is not None else []
        return self._lists[rows[0]] if len(rows) == 1 and rows[0] < len(self._lists) else None

    def _sync(self) -> None:
        item = self._selected()
        manage = bool(getattr(self.page, "can_manage", False))
        self.rows_button.setEnabled(item is not None)
        self.approve_button.setEnabled(manage and item is not None and item.get("kind") == "image"
                                       and not item.get("approved_at") and bool(item.get("usable")))
        ready = item is not None and item.get("status") == "read" and bool(item.get("usable")) \
            and (item.get("kind") != "image" or bool(item.get("approved_at")))
        self.basis_button.setEnabled(manage and ready)
        self.back_button.setEnabled(manage and bool(self._basis))
        hint = ""
        if item is not None and item.get("kind") == "image" and not item.get("approved_at"):
            hint = "لیست عکسی فقط پس از «تأیید لیست عکسی» پایه می‌شود."
        self.basis_button.setToolTip(hint or "این لیست تا زمانی که بگویید پایهٔ قیمت ربات می‌شود.")

    # ---- actions -------------------------------------------------------------------
    def _show_rows(self) -> None:
        item = self._selected()
        if item is None:
            return
        self.page.run(lambda: self.page.context.api.channel_list(item["id"]),
                      on_success=lambda full: ChannelRowsDialog(self.page, full).exec())

    def _approve(self) -> None:
        item = self._selected()
        if item is None or not widgets.confirm(
                self, "تأیید لیست عکسی", "ردیف‌های مطمئن این عکس را دیده‌اید و درست است؟ "
                "(ردیف‌های نامطمئن هیچ‌وقت به کار نمی‌روند)", confirm_text="تأیید"):
            return
        self.page.run(lambda: self.page.context.api.approve_channel_list(item["id"]),
                      on_success=lambda _r: (self.page.notify_success("لیست عکسی تأیید شد."),
                                             self.load()))

    def _make_basis(self) -> None:
        item = self._selected()
        if item is None:
            return
        dialog = BasisDialog(self, item)
        if not dialog.exec():
            return
        column, until = dialog.column(), dialog.until()
        self.page.run(lambda: self.page.context.api.set_price_basis(item["id"], column, until),
                      on_success=lambda _r: (self.page.notify_success("پایهٔ قیمت عوض شد."),
                                             self.load()))

    def _clear_basis(self) -> None:
        self.page.run(lambda: self.page.context.api.clear_price_basis(),
                      on_success=lambda _r: (self.page.notify_success(
                          "پایهٔ قیمت دوباره لیست ابریشمی است."), self.load()))


class BasisDialog(widgets.ResponsiveDialog):
    """ستون قیمت و مدت پایه بودن."""

    def __init__(self, parent: QWidget, item: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("پایهٔ قیمت موقت")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(widgets.label("پایهٔ قیمت موقت", size=14, bold=True))
        root.addWidget(widgets.label(
            f"«{item.get('channel_title') or item.get('channel')}» تا زمانی که انتخاب کنید پایهٔ "
            "قیمت ربات می‌شود؛ بعد خودکار به ابریشمی برمی‌گردد. فقط ردیف‌های مطمئن به کار می‌روند و "
            "مشتری فقط «درخواست خرید» می‌دهد (همکار قیمت را تأیید می‌کند).", wrap=True))
        root.addWidget(widgets.label("ستون قیمت:"))
        self.column_box = QComboBox()
        self.column_box.addItem("قیمت کم (اول بازه)", "min")
        self.column_box.addItem("قیمت زیاد (آخر بازه)", "max")
        root.addWidget(self.column_box)
        root.addWidget(widgets.label("تا کی:"))
        self.until_box = QComboBox()
        self.until_box.addItem("تا پایان امروز", "today")
        self.until_box.addItem("چند ساعت…", "hours")
        root.addWidget(self.until_box)
        self.hours = QSpinBox()
        self.hours.setRange(1, 72)
        self.hours.setValue(3)
        self.hours.setSuffix(" ساعت")
        self.hours.setEnabled(False)
        self.until_box.currentIndexChanged.connect(
            lambda _i: self.hours.setEnabled(self.until_box.currentData() == "hours"))
        root.addWidget(self.hours)
        root.addLayout(widgets.footer(
            widgets.button("پایه کن", icon_name="check", variant="primary", on_click=self.accept),
            close=widgets.button("انصراف", on_click=self.reject)))

    def column(self) -> str:
        return str(self.column_box.currentData() or "min")

    def until(self) -> Optional[str]:
        if self.until_box.currentData() != "hours":
            return None                       # the server: end of today (Tehran)
        when = datetime.now(timezone.utc) + timedelta(hours=self.hours.value())
        return when.isoformat(timespec="seconds")


class ChannelRowsDialog(widgets.ResponsiveDialog):
    """ردیف‌های یک لیست؛ برای لیست عکسی، عکس بریدهٔ هر ردیف کنار مقدار خوانده‌شده."""

    def __init__(self, page, item: dict) -> None:
        super().__init__(page)
        self.page = page
        self.item = item
        self.setWindowTitle("ردیف‌های لیست")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(900)
        self.setMinimumHeight(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        rows = list(item.get("rows") or [])
        ok = sum(1 for r in rows if r.get("state") == "ok")
        root.addWidget(widgets.label(
            f"«{item.get('channel_title') or item.get('channel')}» — {format_int(ok)} ردیف مطمئن از "
            f"{format_int(len(rows))}", size=14, bold=True, wrap=True))
        root.addWidget(widgets.label(
            "ردیف نامطمئن فقط نشان داده می‌شود و هیچ‌وقت به کار نمی‌رود (دلیلش در ستون آخر است).",
            name="Muted", wrap=True))
        picture = item.get("kind") == "image"
        headers = (["عکس ردیف"] if picture else []) + ["برند/بخش", "نام", "رنگ", "قیمت", "وضعیت"]
        self.table = widgets.RoundTable(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        for n, row in enumerate(rows):
            self.table.insertRow(n)
            col = 0
            if picture:
                holder = QLabel("…")
                holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setCellWidget(n, 0, holder)
                col = 1
            low, high = row.get("price_min"), row.get("price_max")
            price = "—" if not low else (to_persian_digits(f"{low:,}") if low == high else
                                         to_persian_digits(f"{low:,} – {high:,}"))
            state = STATE_FA.get(row.get("state"), str(row.get("state")))
            if row.get("reasons"):
                state += ": " + "، ".join(row["reasons"])
            for k, text in enumerate((row.get("brand") or "", row.get("name") or "",
                                      row.get("color") or "", price, state)):
                cell = QTableWidgetItem(text)
                if row.get("state") != "ok":
                    cell.setForeground(theme_brush(theme.TEXT_MUTED))
                cell.setToolTip(text)
                self.table.setItem(n, col + k, cell)
        if picture:
            self.table.setColumnWidth(0, 300)
            self.table.verticalHeader().setDefaultSectionSize(40)
            for n in range(min(len(rows), MAX_CROPS)):
                self._load_crop(n)
        root.addLayout(widgets.footer(close=widgets.button("بستن", on_click=self.accept)))

    def _load_crop(self, index: int) -> None:
        def shown(data: bytes) -> None:
            holder = self.table.cellWidget(index, 0)
            pixmap = QPixmap()
            if holder is not None and data and pixmap.loadFromData(data):
                holder.setPixmap(pixmap.scaledToHeight(34, Qt.TransformationMode.SmoothTransformation))

        self.page.run(lambda: self.page.context.api.channel_row_crop(self.item["id"], index),
                      on_success=shown, on_error=lambda *_a: None)


def theme_brush(value: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(value))
