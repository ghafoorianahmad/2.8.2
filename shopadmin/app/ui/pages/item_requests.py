"""صفحهٔ «درخواست کالا» (نسخهٔ ۲٫۶٫۰).

مشتری در ربات با «درخواست کالای ناموجود» کالایی را که ندارد درخواست می‌کند. این درخواست
سفارش نیست: پرداختی ندارد و چیزی در «سازه حساب» نوشته نمی‌شود. همکاران اینجا فهرست را
می‌بینند و پس از تماس با مشتری آن را «رسیدگی شد» می‌زنند.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget

from ...persian import format_datetime_shamsi, to_persian_digits
from .. import theme, widgets
from ..base_page import BasePage

HEADERS = ("شماره", "زمان", "مشتری", "کد شخص", "کالای درخواستی", "وضعیت", "عملیات")
STATUS_FA = {"new": "جدید", "seen": "دیده شد", "done": "رسیدگی شد"}
TABS = (("open", "باز"), ("done", "رسیدگی‌شده"), ("all", "همه"))


class ItemRequestsPage(BasePage):
    title = "درخواست کالا"
    subtitle = "کالاهای ناموجودی که مشتریان در ربات درخواست کرده‌اند"
    auto_refreshable = True

    def build_body(self) -> None:
        self._tab = "open"
        self._items: list[dict] = []
        tabs = QHBoxLayout()
        self._tab_buttons = {}
        for key, text in TABS:
            button = widgets.button(text, variant="ghost", on_click=lambda k=key: self.set_filter(k))
            button.setCheckable(True)
            self._tab_buttons[key] = button
            tabs.addWidget(button)
        tabs.addStretch(1)
        self.body.addLayout(tabs)
        panel = widgets.Panel("درخواست‌ها")
        panel.body.addWidget(widgets.label(
            "درخواست کالا سفارش نیست؛ پرداختی ندارد و در «سازه حساب» چیزی ثبت نمی‌شود. "
            "پس از تماس با مشتری «رسیدگی شد» را بزنید.", name="Muted", wrap=True))
        self.table = widgets.DataTable(HEADERS, key="item_requests")
        self.table.set_empty_state("درخواستی نیست", "", "inbox")
        self.table.setMinimumHeight(300)
        panel.body.addWidget(self.table, 1)
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)
        self._select_tab()

    def set_filter(self, key: str) -> None:
        self._tab = key if key in dict(TABS) else "open"
        self._select_tab()
        self._render()

    def _select_tab(self) -> None:
        for key, button in self._tab_buttons.items():
            button.setChecked(key == self._tab)

    def load(self) -> None:
        self.run(self.context.api.list_item_requests, on_success=self._loaded,
                 on_error=lambda m, _k: self.show_table_error(m))

    def _loaded(self, items: list) -> None:
        self._items = [i for i in (items or []) if isinstance(i, dict)]
        self._render()

    def visible_items(self) -> list[dict]:
        if self._tab == "open":
            return [i for i in self._items if i.get("status") != "done"]
        if self._tab == "done":
            return [i for i in self._items if i.get("status") == "done"]
        return list(self._items)

    @staticmethod
    def product_text(item: dict) -> str:
        name = str(item.get("product_name") or "").strip()
        text = str(item.get("text") or "").strip()
        if name and item.get("kala_code"):
            name = f"{name} (کد {to_persian_digits(item['kala_code'])})"
        if name and text and text != name:
            return f"{name} — «{text}»"
        return name or (f"«{text}»" if text else "—")

    def _render(self) -> None:
        rows = self.visible_items()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for item in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                status = str(item.get("status") or "new")
                self.table.set_cell(row, 0, to_persian_digits(item.get("id", "")))
                self.table.set_cell(row, 1, format_datetime_shamsi(item.get("created_at")))
                self.table.set_cell(row, 2, str(item.get("customer_name") or "—"), bold=True)
                code = item.get("person_code")
                self.table.set_cell(row, 3, to_persian_digits(code) if code is not None else "—")
                product = self.product_text(item)
                self.table.set_cell(row, 4, product, tooltip=product)
                self.table.set_cell(row, 5, STATUS_FA.get(status, status),
                                    color=theme.WARNING_TEXT if status == "new" else None,
                                    bold=status == "new")
                self.table.set_widget(row, 6, self._actions(item))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        open_count = sum(1 for i in self._items if i.get("status") != "done")
        self.summary.setText(f"{to_persian_digits(open_count)} درخواست باز — "
                             f"{to_persian_digits(len(self._items))} درخواست در کل")

    def _actions(self, item: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        status = item.get("status")
        if status != "done":
            layout.addWidget(widgets.button(
                "رسیدگی شد", variant="success",
                on_click=lambda i=item: self._set_status(i, "done")))
        if status == "new":
            layout.addWidget(widgets.button(
                "دیده شد", on_click=lambda i=item: self._set_status(i, "seen")))
        if status == "done":
            layout.addWidget(widgets.button(
                "باز کردن دوباره", on_click=lambda i=item: self._set_status(i, "new")))
        layout.addStretch(1)
        return holder

    def _set_status(self, item: dict, status: str) -> None:
        request_id = int(item["id"])
        self.run(lambda: self.context.api.set_item_request_status(request_id, status),
                 on_success=lambda _r: self.load(),
                 on_error=lambda m, _k: widgets.error(self, "انجام نشد", m))
