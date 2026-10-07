"""Responsive layout, resizable table columns and RTL/bidi-safe numbers."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QWidget

from app.persian import LRI, PDI, format_phone, isolate_ltr
from app.statuses import ROLE_SUPER_ADMIN
from app.ui import widgets
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


def _pump(app, rounds: int = 40) -> None:
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    for _ in range(rounds):
        app.processEvents()


# ---------------------------------------------------------------- bidi
def test_phone_is_isolated_left_to_right_with_persian_digits():
    text = format_phone("0912*****67")
    assert text.startswith(LRI) and text.endswith(PDI)
    assert "۰۹۱۲" in text and "0" not in text
    assert format_phone("") == "—" and format_phone(None) == "—"


def test_isolate_leaves_empty_and_dash_alone():
    assert isolate_ltr("") == "" and isolate_ltr("—") == "—"


# ---------------------------------------------------------------- tables
class MemoryStore:
    def __init__(self):
        self.data = {}

    def get_setting(self, key, default=None):
        return self.data.get(key, default)

    def set_setting(self, key, value):
        self.data[key] = value


@pytest.fixture
def table_store(admin_qapp):
    store = MemoryStore()
    widgets.DataTable.settings_store = store
    yield store
    widgets.DataTable.settings_store = None


def test_table_columns_are_user_resizable(admin_qapp):
    table = widgets.DataTable(("الف", "ب", "ج"))
    header = table.horizontalHeader()
    assert all(header.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive for i in range(2))
    assert header.stretchLastSection()
    assert table.textElideMode() == Qt.TextElideMode.ElideRight


def test_table_default_widths_fit_the_viewport(admin_qapp):
    table = widgets.DataTable(("شمارهٔ سفارش", "مشتری", "مبلغ کل", "تاریخ ثبت"), key="t1")
    table.resize(420, 300)
    table.show()
    table.fill([["۱۰۴۱", "یک نام خیلی خیلی طولانی برای مشتری", "۱٬۲۵۰٬۰۰۰ تومان", "۱۴۰۵/۰۷/۱۵"]])
    _pump(admin_qapp, 5)
    total = sum(table.columnWidth(c) for c in range(table.columnCount()))
    assert total <= table.viewport().width() + 4          # nothing forces a scroll bar
    assert all(table.columnWidth(c) >= widgets.DataTable.MIN_COLUMN for c in range(4))
    table.close()


def test_table_cell_text_has_a_tooltip_when_elided(admin_qapp):
    table = widgets.DataTable(("الف",))
    table.fill([["متن بلند"]])
    assert table.item(0, 0).toolTip() == "متن بلند"


def test_dragged_widths_are_remembered(admin_qapp, table_store):
    table = widgets.DataTable(("الف", "ب", "ج"), key="persist")
    table.fill([["۱", "۲", "۳"]])
    table.horizontalHeader().resizeSection(0, 211)       # a user drag
    table._save_widths()
    assert table_store.data["table_widths.persist"][0] == 211

    again = widgets.DataTable(("الف", "ب", "ج"), key="persist")
    again.fill([["۱", "۲", "۳"]])
    assert again.columnWidth(0) == 211                   # restored, not re-fitted
    again.reset_widths()
    assert table_store.data["table_widths.persist"] is None


def test_wrong_number_of_saved_widths_is_ignored(admin_qapp, table_store):
    table_store.data["table_widths.x"] = [100, 100]
    table = widgets.DataTable(("الف", "ب", "ج"), key="x")
    table.fill([["۱", "۲", "۳"]])
    assert table._user_sized is False


# ---------------------------------------------------------------- layouts
def test_flow_layout_wraps_and_stays_right_to_left(admin_qapp):
    holder = QWidget()
    holder.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    flow = widgets.FlowLayout(holder, spacing=10)
    boxes = []
    for _ in range(3):
        box = QWidget()
        box.setFixedSize(100, 20)
        flow.addWidget(box)
        boxes.append(box)
    holder.resize(250, 100)
    holder.show()
    _pump(admin_qapp, 5)
    assert boxes[0].x() > boxes[1].x()                   # first item on the right
    assert boxes[2].y() > boxes[0].y()                   # the third wrapped to a new row
    assert flow.heightForWidth(250) >= 50
    holder.close()


def test_card_grid_makes_an_even_grid(admin_qapp):
    grid = widgets.CardGrid(min_card_width=250)
    for _ in range(4):
        grid.add_card(widgets.StatCard("عنوان"))
    grid.resize(1100, 200)
    grid.show()
    _pump(admin_qapp, 5)
    assert grid.columns() == 4
    grid.resize(780, 400)
    _pump(admin_qapp, 5)
    assert grid.columns() == 2                           # 2 x 2, not 3 + 1
    grid.close()


# ---------------------------------------------------------------- main window
@pytest.mark.parametrize("width,height,compact", [(1366, 768, False), (900, 600, True)])
def test_main_window_adapts_to_small_screens(ui_context, admin_qapp, width, height, compact):  # noqa: F811
    from app.ui.main_window import SIDEBAR_COMPACT, SIDEBAR_WIDE, MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    window.resize(width, height)
    window.show()
    _pump(admin_qapp, 10)
    try:
        assert window.minimumWidth() <= 900 and window.minimumHeight() <= 600
        assert window._compact is compact
        assert window._sidebar.width() == (SIDEBAR_COMPACT if compact else SIDEBAR_WIDE)
        for key, page in window._pages.items():
            # pages never demand more width than the content area offers
            assert page.minimumSizeHint().width() <= window.width() - SIDEBAR_COMPACT, key
    finally:
        window.close()
