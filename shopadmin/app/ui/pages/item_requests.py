"""صفحهٔ «درخواست کالا» (نسخهٔ ۲٫۶٫۰؛ جزئیات و پیام به مشتری از نسخهٔ ۲٫۶٫۱).

مشتری در ربات با «درخواست کالای ناموجود» کالایی را که ندارد درخواست می‌کند، یا برای
کالای «قیمت با استعلام» دکمهٔ «استعلام قیمت» را می‌زند. این درخواست سفارش نیست:
پرداختی ندارد و هرگز چیزی در «سازه حساب» نوشته نمی‌شود. همکاران اینجا فهرست را
می‌بینند، با کلیک روی هر ردیف جزئیات را باز می‌کنند، یادداشت می‌گذارند، از همان‌جا
به مشتری (با همان رباتی که درخواست داده) پیام می‌فرستند و «رسیدگی شد» را می‌زنند.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...activity import timeline_text
from ...permissions import ORDERS_ASSIGN
from ...persian import coerce_datetime, format_datetime_shamsi, format_money, \
    gregorian_to_jalali, to_english_digits, to_persian_digits
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..rtl import RIGHT

HEADERS = ("شماره", "زمان ثبت", "نوع", "مشتری", "کد شخص", "وضعیت", "مسئول", "کالای درخواستی")
COL_TIME = 1
COL_PRODUCT = 7
STATUS_FA = {"new": "جدید", "seen": "دیده شد", "done": "رسیدگی شد"}
KIND_FA = {"unavailable": "ناموجود", "inquiry": "استعلام قیمت", "purchase": "درخواست خرید"}
OUTCOME_FA = {"confirmed": "موجودی تأیید شد (سفارش ساخته شد)", "unavailable": "ناموجود اعلام شد"}
PLATFORM_FA = {"bale": "بله", "telegram": "تلگرام"}
MESSAGE_STATUS_FA = {"pending": "در صف ارسال (ربات)", "sent": "ارسال شد", "failed": "ارسال نشد"}
#: v2.8.1: each filter says what it covers (two buttons both read «همه» before)
TABS = (("open", "باز"), ("done", "رسیدگی‌شده"), ("all", "همهٔ وضعیت‌ها"))
SCOPES = (("mine", "کارهای من"), ("all", "همهٔ درخواست‌ها"))
KIND_FILTERS = (("", "همهٔ انواع"), ("purchase", "درخواست خرید"), ("unavailable", "ناموجود"),
                ("inquiry", "استعلام قیمت"))
#: After sending, the dialog re-reads the delivery state this often, this many times.
POLL_MS = 3000
POLL_TRIES = 20


def full_datetime(value: object) -> str:
    """Shamsi date and the time to the second (the table shows minutes)."""
    moment = coerce_datetime(value)
    if moment is None:
        return "—"
    jy, jm, jd = gregorian_to_jalali(moment.year, moment.month, moment.day)
    return to_persian_digits(f"{jy}/{jm:02d}/{jd:02d} "
                             f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}")


def product_text(item: dict) -> str:
    name = str(item.get("product_name") or "").strip()
    if item.get("kind") == "purchase":
        # v2.8.0: «درخواست خرید» of a price-list row: model — color — part — price
        parts = [name, str(item.get("color") or "").strip(), str(item.get("part") or "").strip()]
        text = " — ".join(p for p in parts if p) or "—"
        if item.get("price_rial"):
            text += f" ({format_money(item['price_rial'])})"
        return text
    text = str(item.get("text") or "").strip()
    if name and item.get("kala_code"):
        name = f"{name} (کد {to_persian_digits(item['kala_code'])})"
    if name and text and text != name:
        return f"{name} — «{text}»"
    return name or (f"«{text}»" if text else "—")


def _filter_caption(text: str) -> QWidget:
    """A filter group's caption, centred on the height of its buttons."""
    caption = widgets.label(text, name="Muted", bold=True)
    caption.setAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
    caption.setMinimumHeight(widgets.button("x").sizeHint().height())
    caption.setContentsMargins(10, 0, 0, 0)
    return caption


class ItemRequestsPage(BasePage):
    title = "درخواست کالا"
    subtitle = "کالاهای ناموجود و استعلام‌های قیمتی که مشتریان در ربات فرستاده‌اند"
    help_text = "کالاهایی که مشتریان خواسته‌اند یا قیمتشان را پرسیده‌اند. روی هر ردیف کلیک کنید تا به مشتری پیام بدهید."
    auto_refreshable = True

    def build_body(self) -> None:
        self._tab = "open"
        self._kind = ""
        self._items: list[dict] = []
        self._visible: list[dict] = []
        principal = self.context.principal
        # v2.8.0: «کارهای من» is the default view of a sales user
        self._mine = principal is not None and not principal.is_manager
        # v2.8.1: three labelled groups in a row that wraps on a narrow window
        filters_holder = QWidget()
        tabs = widgets.FlowLayout(filters_holder, spacing=8)
        tabs.addWidget(_filter_caption("نمایش:"))
        self._scope_buttons = {}
        for key, text in SCOPES:
            button = widgets.button(text, variant="ghost",
                                    on_click=lambda k=key: self.set_scope(k == "mine"))
            button.setObjectName("Tab")   # the chosen filter is highlighted
            button.setCheckable(True)
            button.setChecked((key == "mine") == self._mine)
            self._scope_buttons[key] = button
            tabs.addWidget(button)
        tabs.addWidget(_filter_caption("وضعیت:"))
        self._tab_buttons = {}
        for key, text in TABS:
            button = widgets.button(text, variant="ghost", on_click=lambda k=key: self.set_filter(k))
            button.setObjectName("Tab")
            button.setCheckable(True)
            self._tab_buttons[key] = button
            tabs.addWidget(button)
        tabs.addWidget(_filter_caption("نوع:"))
        self.kind_combo = QComboBox()
        for key, text in KIND_FILTERS:
            self.kind_combo.addItem(text, key)
        self.kind_combo.currentIndexChanged.connect(
            lambda _i: self.set_kind(self.kind_combo.currentData() or ""))
        tabs.addWidget(self.kind_combo)
        self.body.addWidget(filters_holder)
        panel = widgets.Panel("درخواست‌ها")
        panel.body.addWidget(widgets.label(
            "درخواست کالا سفارش نیست؛ پرداختی ندارد و در «سازه حساب» چیزی ثبت نمی‌شود. "
            "روی هر ردیف کلیک کنید تا جزئیات، یادداشت و ارسال پیام به مشتری باز شود.",
            name="Muted", wrap=True))
        # New width key: widths saved by v2.6.0 cut the date and the product header.
        self.table = widgets.DataTable(HEADERS, selectable_rows=True, key="item_requests_v261",
                                       keep_columns=(COL_TIME,))
        self.table.set_empty_state("درخواستی نیست", "", "inbox")
        self.table.setMinimumHeight(300)
        self.table.row_activated.connect(self._open_row)
        panel.body.addWidget(self.table, 1)
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)
        self._select_tab()

    # ------------------------------------------------------------------ filters
    def set_filter(self, key: str) -> None:
        self._tab = key if key in dict(TABS) else "open"
        self._select_tab()
        self._render()

    def set_kind(self, kind: str) -> None:
        self._kind = kind if kind in dict(KIND_FILTERS) else ""
        index = self.kind_combo.findData(self._kind)
        if index >= 0 and index != self.kind_combo.currentIndex():
            self.kind_combo.setCurrentIndex(index)
        self._render()

    def set_scope(self, mine: bool) -> None:
        self._mine = bool(mine)
        for key, button in self._scope_buttons.items():
            button.setChecked((key == "mine") == self._mine)
        self.load()

    def _select_tab(self) -> None:
        for key, button in self._tab_buttons.items():
            button.setChecked(key == self._tab)

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        mine = self._mine
        self.run(lambda: self.context.api.list_item_requests(mine=mine), on_success=self._loaded,
                 on_error=lambda m, _k: self.show_table_error(m))

    def _loaded(self, items: list) -> None:
        self._items = [i for i in (items or []) if isinstance(i, dict)]
        self._render()

    def visible_items(self) -> list[dict]:
        rows = self._items
        if self._kind:
            rows = [i for i in rows if (i.get("kind") or "unavailable") == self._kind]
        if self._tab == "open":
            return [i for i in rows if i.get("status") != "done"]
        if self._tab == "done":
            return [i for i in rows if i.get("status") == "done"]
        return list(rows)

    product_text = staticmethod(product_text)

    def _render(self) -> None:
        rows = self.visible_items()
        self._visible = rows
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for item in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                status = str(item.get("status") or "new")
                kind = str(item.get("kind") or "unavailable")
                self.table.set_cell(row, 0, to_persian_digits(item.get("id", "")))
                self.table.set_cell(row, COL_TIME, format_datetime_shamsi(item.get("created_at")),
                                    tooltip=full_datetime(item.get("created_at")))
                self.table.set_cell(row, 2, KIND_FA.get(kind, kind),
                                    color=theme.PRIMARY if kind in ("inquiry", "purchase")
                                    else None, bold=kind == "purchase")
                self.table.set_cell(row, 3, str(item.get("customer_name") or "—"), bold=True)
                code = item.get("person_code")
                self.table.set_cell(row, 4, to_persian_digits(code) if code is not None else "—")
                self.table.set_cell(row, 5, STATUS_FA.get(status, status),
                                    color=theme.WARNING_TEXT if status == "new" else None,
                                    bold=status == "new")
                from .orders import owner_label, waiting_too_long

                self.table.set_cell(row, 6, owner_label(item), bold=bool(item.get("owned_by_me")))
                product = product_text(item)
                self.table.set_cell(row, COL_PRODUCT, product, tooltip=product)
                if waiting_too_long(item, statuses=("new",)):
                    self.table.set_cell(row, 0, to_persian_digits(item.get("id", "")),
                                        bold=True, color=theme.WARNING_TEXT,
                                        tooltip="بیش از ۱۰ دقیقه بی‌پاسخ مانده است")
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        open_count = sum(1 for i in self._items if i.get("status") != "done")
        self.summary.setText(f"{to_persian_digits(open_count)} درخواست باز — "
                             f"{to_persian_digits(len(self._items))} درخواست در کل")

    def _open_row(self, row: int) -> None:
        if 0 <= row < len(self._visible):
            self.open_request(self._visible[row])

    def open_request(self, item: dict) -> None:
        dialog = ItemRequestDialog(self.context, item, self)
        dialog.exec()
        if dialog.changed:
            self.load()

    def _set_status(self, item: dict, status: str) -> None:
        request_id = int(item["id"])
        self.run(lambda: self.context.api.set_item_request_status(request_id, status),
                 on_success=lambda _r: self.load(),
                 on_error=lambda m, _k: widgets.error(self, "انجام نشد", m))


def _kv(key: str, value: str, *, selectable: bool = True) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(widgets.label(f"{key}:", name="Muted"))
    value_label = widgets.label(value, bold=True, wrap=True)
    if selectable:
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(value_label, 1)
    return holder


class ItemRequestDialog(widgets.ResponsiveDialog):
    """جزئیات یک درخواست: متن کامل، مشتری، وضعیت، یادداشت و پیام به مشتری."""

    def __init__(self, context, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.item = dict(item)
        self.changed = False
        self.messages: list[dict] = []
        self._poll_left = 0
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_tick)

        request_id = int(item.get("id") or 0)
        self.setWindowTitle(f"درخواست شمارهٔ {to_persian_digits(request_id)}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(700, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        kind = str(item.get("kind") or "unavailable")
        header.addWidget(widgets.label(
            f"درخواست شمارهٔ {to_persian_digits(request_id)} — {KIND_FA.get(kind, kind)}",
            size=14, bold=True), 1)
        self.status_pill = widgets.StatusPill("", "")
        header.addWidget(self.status_pill)
        root.addLayout(header)

        meta = widgets.Panel()
        code = item.get("person_code")
        phone = str(item.get("customer_phone") or "").strip()
        platform = str(item.get("platform") or "")
        meta.body.addWidget(_kv("زمان ثبت", full_datetime(item.get("created_at"))))
        meta.body.addWidget(_kv("مشتری", str(item.get("customer_name") or "—")))
        meta.body.addWidget(_kv("کد شخص", to_persian_digits(code) if code is not None
                                else "هنوز وصل نشده"))
        phone_row = QHBoxLayout()
        phone_row.addWidget(_kv("موبایل", to_persian_digits(phone) if phone else "—"), 1)
        if phone:
            from .orders import copy_to_clipboard

            self.copy_phone_button = widgets.button(
                "کپی", icon_name="copy", tooltip="کپی شمارهٔ موبایل مشتری",
                on_click=lambda: (copy_to_clipboard(phone),
                                  self._set_send_info("شمارهٔ موبایل کپی شد.", ok=True)))
            phone_row.addWidget(self.copy_phone_button)
        meta.body.addLayout(phone_row)
        from .orders import owner_label

        meta.body.addWidget(_kv("مسئول", owner_label(item)))
        if kind == "purchase":
            meta.body.addWidget(_kv("رنگ / پارت", " — ".join(
                p for p in (str(item.get("color") or ""), str(item.get("part") or "")) if p)
                or "—"))
            meta.body.addWidget(_kv("قیمت لیست", format_money(item.get("price_rial") or 0)
                                    if item.get("price_rial") else "—"))
            if item.get("outcome"):
                meta.body.addWidget(_kv("نتیجه", OUTCOME_FA.get(item["outcome"], item["outcome"])
                                        + (f" — سفارش {to_persian_digits(item['order_id'])}"
                                           if item.get("order_id") else "")))
        meta.body.addWidget(_kv("پیام‌رسان", PLATFORM_FA.get(platform, platform or "—")))
        name = str(item.get("product_name") or "").strip()
        if name:
            meta.body.addWidget(_kv("کالا", f"{name} (کد {to_persian_digits(item.get('kala_code'))})"
                                    if item.get("kala_code") else name))
        self.handled_label = widgets.label("", name="Muted", wrap=True)
        meta.body.addWidget(self.handled_label)
        root.addWidget(meta)

        text_panel = widgets.Panel("متن کامل درخواست")
        self.request_text = QPlainTextEdit(str(item.get("text") or "").strip()
                                           or "(مشتری متنی ننوشته؛ کالا از فهرست انتخاب شده)")
        self.request_text.setReadOnly(True)
        self.request_text.setMaximumHeight(80)
        text_panel.body.addWidget(self.request_text)
        root.addWidget(text_panel)

        note_panel = widgets.Panel("یادداشت همکاران (به مشتری نشان داده نمی‌شود)")
        self.note_edit = QPlainTextEdit(str(item.get("admin_note") or ""))
        self.note_edit.setMaximumHeight(70)
        note_panel.body.addWidget(self.note_edit)
        note_row = QHBoxLayout()
        self.note_info = widgets.label("", name="Muted")
        note_row.addWidget(self.note_info, 1)
        self.note_button = widgets.button("ذخیرهٔ یادداشت", on_click=self.save_note)
        note_row.addWidget(self.note_button)
        note_panel.body.addLayout(note_row)
        root.addWidget(note_panel)

        msg_panel = widgets.Panel("پیام به مشتری (با همان رباتی که درخواست داده)")
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(("زمان", "فرستنده", "وضعیت", "متن"))
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)
        self.history.setMaximumHeight(140)
        widgets.show_full_headers(self.history)
        msg_panel.body.addWidget(self.history)
        self.message_edit = QPlainTextEdit()
        self.message_edit.setPlaceholderText("متن پیام به مشتری…")
        self.message_edit.setMaximumHeight(70)
        msg_panel.body.addWidget(self.message_edit)
        send_row = QHBoxLayout()
        self.send_info = widgets.label("", wrap=True)
        send_row.addWidget(self.send_info, 1)
        self.send_button = widgets.button("ارسال پیام به مشتری", variant="primary",
                                          on_click=self.send_message)
        send_row.addWidget(self.send_button)
        msg_panel.body.addLayout(send_row)
        root.addWidget(msg_panel, 1)

        # v2.8.0: what was done (names only for the manager)
        self.timeline_label = widgets.label("…", wrap=True)
        timeline_panel = widgets.Panel("کارهای انجام‌شده")
        timeline_panel.body.addWidget(self.timeline_label)
        root.addWidget(timeline_panel)

        buttons = QHBoxLayout()
        self.stock_button = widgets.button("تأیید موجودی", variant="success", icon_name="check",
                                           on_click=self.confirm_stock)
        self.unavailable_button = widgets.button("ناموجود", variant="danger",
                                                 on_click=self.mark_unavailable)
        self.assign_button = widgets.button("ارجاع به همکار", icon_name="users",
                                            on_click=self.assign)
        for b in (self.stock_button, self.unavailable_button):
            b.setProperty("big", True)
            buttons.addWidget(b)
        self.seen_button = widgets.button("دیده شد", on_click=lambda: self.set_status("seen"))
        self.done_button = widgets.button("رسیدگی شد", variant="success",
                                          on_click=lambda: self.set_status("done"))
        self.reopen_button = widgets.button("باز کردن دوباره",
                                            on_click=lambda: self.set_status("new"))
        for b in (self.done_button, self.seen_button, self.reopen_button, self.assign_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("بستن", variant="ghost", on_click=self.accept))
        root.addLayout(buttons)

        self._render_item()
        self.load_messages()
        self.load_timeline()

    # ------------------------------------------------------------------ item
    def _render_item(self) -> None:
        status = str(self.item.get("status") or "new")
        self.status_pill.set_status(
            {"new": "pending", "seen": "receipt_uploaded", "done": "approved"}.get(status, status),
            STATUS_FA.get(status, status))
        purchase = self.item.get("kind") == "purchase"
        finished = status == "done" or bool(self.item.get("archived") or self.item.get("archived_at"))
        self.seen_button.setVisible(status == "new" and not finished)
        # a purchase request ends with «تأیید موجودی» / «ناموجود» (the customer is told)
        self.done_button.setVisible(not finished and not purchase)
        # v2.8.0: a finished request is read-only
        self.reopen_button.setVisible(False)
        self.stock_button.setVisible(purchase and not finished)
        self.unavailable_button.setVisible(purchase and not finished)
        may_assign = self.context.can(ORDERS_ASSIGN) or bool(self.item.get("owned_by_me"))
        self.assign_button.setVisible(not finished and may_assign)
        for widget in (self.note_button, self.send_button, self.note_edit, self.message_edit):
            widget.setEnabled(not finished)
        handled = []
        if self.item.get("handled_at"):
            handled.append(f"آخرین تغییر وضعیت: {full_datetime(self.item.get('handled_at'))}"
                           f" — {self.item.get('handled_by') or '—'}")
        self.handled_label.setText("\n".join(handled))
        self.handled_label.setVisible(bool(handled))
        if self.item.get("note_at"):
            self.note_info.setText(f"آخرین ویرایش: {full_datetime(self.item.get('note_at'))} — "
                                   f"{self.item.get('note_by') or '—'}")

    # ---- v2.8.0: purchase requests, handover, timeline ----------------------
    def load_timeline(self) -> None:
        request_id = int(self.item["id"])
        api = self.context.api
        if not hasattr(api, "item_request_timeline"):
            self.timeline_label.setText("—")
            return
        run_async(lambda: api.item_request_timeline(request_id),
                  on_success=lambda rows: self.timeline_label.setText(
                      timeline_text(list(rows or []))),
                  on_error=lambda _m, _k: self.timeline_label.setText("—"))

    def confirm_stock(self) -> None:
        dialog = StockConfirmDialog(self, self.item)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request_id = int(self.item["id"])
        code, price = dialog.kala_code, dialog.price
        self.stock_button.setEnabled(False)
        run_async(lambda: self.context.api.confirm_purchase_stock(request_id, code, price),
                  on_success=self._stock_confirmed,
                  on_error=lambda m, _k: (self.stock_button.setEnabled(True),
                                          widgets.error(self, "سفارش ساخته نشد", m)))

    def _stock_confirmed(self, order: object) -> None:
        order_id = (order or {}).get("id") if isinstance(order, dict) else None
        self.item.update(status="done", outcome="confirmed", order_id=order_id)
        self.changed = True
        self._render_item()
        self.load_timeline()
        widgets.success(self, "سفارش ساخته شد",
                        f"سفارش شمارهٔ {to_persian_digits(order_id or '—')} ساخته شد و ربات "
                        "اطلاعات پرداخت را برای مشتری می‌فرستد (مهلت رسید مثل سفارش‌های دیگر).")

    def mark_unavailable(self) -> None:
        if not widgets.confirm(self, "ناموجود",
                               "به مشتری پیام مؤدبانهٔ «ناموجود» فرستاده و درخواست بسته شود؟",
                               confirm_text="بله، بفرست", kind="warning"):
            return
        request_id = int(self.item["id"])
        run_async(lambda: self.context.api.mark_purchase_unavailable(request_id),
                  on_success=lambda row: (self._item_updated(row), self.load_messages(),
                                          self.load_timeline()),
                  on_error=lambda m, _k: widgets.error(self, "انجام نشد", m))

    def assign(self) -> None:
        from .orders import AssignDialog

        dialog = AssignDialog(self.context, self,
                              f"درخواست {to_persian_digits(self.item.get('id', ''))}")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.staff_id is None:
            return
        request_id, staff_id = int(self.item["id"]), dialog.staff_id
        run_async(lambda: self.context.api.assign_item_request(request_id, staff_id),
                  on_success=lambda _r: (setattr(self, "changed", True), self.accept()),
                  on_error=lambda m, _k: widgets.error(self, "ارجاع انجام نشد", m))

    def set_status(self, status: str) -> None:
        request_id = int(self.item["id"])
        run_async(lambda: self.context.api.set_item_request_status(request_id, status),
                  on_success=self._item_updated,
                  on_error=lambda m, _k: widgets.error(self, "انجام نشد", m))

    def save_note(self) -> None:
        request_id = int(self.item["id"])
        note = self.note_edit.toPlainText().strip()
        run_async(lambda: self.context.api.set_item_request_note(request_id, note),
                  on_success=self._item_updated,
                  on_error=lambda m, _k: widgets.error(self, "یادداشت ذخیره نشد", m))

    def _item_updated(self, row: object) -> None:
        if isinstance(row, dict) and row:
            self.item.update(row)
        self.changed = True
        self._render_item()

    # ------------------------------------------------------------------ messages
    def load_messages(self) -> None:
        request_id = int(self.item["id"])
        run_async(lambda: self.context.api.item_request_messages(request_id),
                  on_success=self._messages_loaded,
                  on_error=lambda m, _k: self._set_send_info(f"تاریخچهٔ پیام‌ها خوانده نشد: {m}",
                                                             error=True))

    def _messages_loaded(self, rows: object) -> None:
        self.messages = [r for r in (rows or []) if isinstance(r, dict)]
        self.history.setRowCount(0)
        for msg in self.messages:
            row = self.history.rowCount()
            self.history.insertRow(row)
            status = str(msg.get("status") or "pending")
            label = MESSAGE_STATUS_FA.get(status, status)
            if status == "failed" and msg.get("error"):
                label = f"{label}: {msg['error']}"
            cells = (full_datetime(msg.get("created_at")), str(msg.get("created_by") or "—"),
                     label, str(msg.get("text") or ""))
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                if column == 2:
                    cell.setForeground(theme_brush(
                        theme.DANGER if status == "failed" else
                        theme.SUCCESS if status == "sent" else theme.WARNING_TEXT))
                self.history.setItem(row, column, cell)
        self.history.resizeColumnsToContents()
        self._report_delivery()

    def _report_delivery(self) -> None:
        if not self.messages:
            if not self.send_info.text():
                self._set_send_info("هنوز پیامی برای این مشتری فرستاده نشده است.")
            return
        last = self.messages[-1]
        status = str(last.get("status") or "")
        if status == "failed":
            self._poll.stop()
            self._set_send_info("❌ آخرین پیام ارسال نشد: " + str(last.get("error") or
                                "علت نامشخص") + " — می‌توانید دوباره بفرستید.", error=True)
        elif status == "sent":
            self._poll.stop()
            self._set_send_info("✅ آخرین پیام به مشتری ارسال شد.", ok=True)
        elif not self._poll.isActive():
            self._set_send_info("⏳ پیام در صف ارسال است؛ ربات سرور چند ثانیه بعد آن را "
                                "می‌فرستد. اگر مدتی در صف ماند، روشن بودن ربات را بررسی کنید.")

    def _set_send_info(self, text: str, *, error: bool = False, ok: bool = False) -> None:
        color = theme.DANGER if error else theme.SUCCESS if ok else theme.TEXT_MUTED
        self.send_info.setText(text)
        self.send_info.setStyleSheet(f"color: {color};" + (" font-weight: 600;" if error else ""))

    def send_message(self) -> None:
        text = self.message_edit.toPlainText().strip()
        if not text:
            self._set_send_info("متن پیام خالی است.", error=True)
            return
        request_id = int(self.item["id"])
        self.send_button.setEnabled(False)
        run_async(lambda: self.context.api.send_item_request_message(request_id, text),
                  on_success=self._sent, on_error=self._send_failed,
                  on_done=lambda: self.send_button.setEnabled(True))

    def _sent(self, _row: object) -> None:
        self.message_edit.clear()
        self.changed = True
        self._set_send_info("⏳ پیام ثبت شد و در صف ارسال ربات است…")
        self._poll_left = POLL_TRIES
        self._poll.start()
        self.load_messages()

    def _send_failed(self, message: str, _kind: str = "") -> None:
        self._set_send_info("❌ پیام ارسال نشد: " + (message or "خطای نامشخص"), error=True)
        widgets.error(self, "پیام ارسال نشد", message)

    def _poll_tick(self) -> None:
        self._poll_left -= 1
        if self._poll_left <= 0:
            self._poll.stop()
        self.load_messages()

    def done(self, result: int) -> None:  # noqa: D401 - QDialog override
        self._poll.stop()
        super().done(result)


class StockConfirmDialog(widgets.ResponsiveDialog):
    """«تأیید موجودی»: the «سازه حساب» product (needed when the row is not mapped
    yet) and, optionally, another price. A normal order awaiting payment follows."""

    def __init__(self, parent: QWidget | None, item: dict) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit

        self.kala_code: int | None = None
        self.price: int | None = None
        self._item = item
        self.setWindowTitle("تأیید موجودی")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label("تأیید موجودی", size=14, bold=True))
        root.addWidget(widgets.label(product_text(item), bold=True, wrap=True))
        root.addWidget(widgets.label(
            "با تأیید، یک سفارش عادی برای مشتری ساخته می‌شود و ربات اطلاعات پرداخت را "
            "می‌فرستد؛ رسید باید در مهلت معمول برسد. اگر فروش گوشی بسته باشد، سفارش ساخته "
            "نمی‌شود.", name="Muted", wrap=True))
        mapped = bool(item.get("kala_code"))
        root.addWidget(widgets.label("کد کالا در «سازه حساب»" +
                                     (" (اختیاری؛ ردیف قبلاً وصل شده)" if mapped else "")))
        self.code_input = QLineEdit(to_persian_digits(item["kala_code"]) if mapped else "")
        self.code_input.setPlaceholderText("مثلاً ۱۲۳۴")
        self.code_input.setMinimumHeight(40)
        root.addWidget(self.code_input)
        root.addWidget(widgets.label("قیمت (ریال) — خالی = قیمت لیست"))
        self.price_input = QLineEdit(to_persian_digits(item["price_rial"])
                                     if item.get("price_rial") else "")
        self.price_input.setMinimumHeight(40)
        root.addWidget(self.price_input)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = widgets.button("ساخت سفارش", variant="success", icon_name="check",
                            on_click=self._accept)
        ok.setProperty("big", True)
        row.addWidget(ok)
        row.addWidget(widgets.button("انصراف", on_click=self.reject))
        root.addLayout(row)

    @staticmethod
    def _number(text: str) -> int | None:
        digits = "".join(ch for ch in to_english_digits(text) if ch.isdigit())
        return int(digits) if digits else None

    def _accept(self) -> None:
        code = self._number(self.code_input.text())
        price = self._number(self.price_input.text())
        if code is None and not self._item.get("kala_code"):
            self.error_label.setText("این ردیف هنوز به کالایی وصل نیست؛ کد کالا را بنویسید.")
            self.error_label.setVisible(True)
            return
        if self.price_input.text().strip() and not price:
            self.error_label.setText("قیمت درست نیست؛ فقط رقم بنویسید یا خالی بگذارید.")
            self.error_label.setVisible(True)
            return
        self.kala_code = code
        self.price = price
        self.accept()


def theme_brush(value: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(value))
