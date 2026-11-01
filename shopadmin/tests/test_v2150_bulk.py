"""v2.15.0 #4: a check box per row + «انتخاب همه» in «سایت» (phones and
accessories) with bulk «حذف» / «پنهان» / «نمایش»; a bulk delete keeps the
48-hour undo (one line brings the whole group back)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.site import catalog as cat  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.pages import site as site_page  # noqa: E402

from .test_ui import ui_context  # noqa: E402,F401
from .test_v2110_site import image_bytes, site_folder  # noqa: E402,F401
from .test_v2140_site_ui import page  # noqa: E402,F401


def test_rows_have_a_check_box_and_select_all(page):  # noqa: F811
    table = page.phones_table
    assert table.rowCount() >= 2
    assert table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert table.checked_rows() == []
    page.phone_select_all.click()
    assert len(table.checked_rows()) == table.rowCount()
    assert page.phone_checked_label.text().endswith("انتخاب‌شده")
    page.phone_select_all.click()
    assert table.checked_rows() == [] and page.phone_checked_label.text() == ""
    table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert table.checked_rows() == [1] and not page.phone_select_all.isChecked()


def test_bulk_hide_and_show(page):  # noqa: F811
    table = page.phones_table
    codes = [table.row_key(0), table.row_key(1)]
    table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    page.hide_phone_button.click()
    assert all(page.store.get(c)["hidden"] for c in codes)
    # the ticks survive the reload after the action
    assert sorted(page.phones_table.checked_keys()) == sorted(codes)
    page.show_phone_button.click()
    assert not any(page.store.get(c)["hidden"] for c in codes)


def test_bulk_delete_keeps_the_48_hour_undo(page, monkeypatch):  # noqa: F811
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    table = page.phones_table
    before = table.rowCount()
    codes = [table.row_key(r) for r in range(before)]
    page.phone_select_all.click()
    page.delete_phone_button.click()
    assert page.phones_table.rowCount() == 0
    assert all(page.store.get(c) is None for c in codes)
    deleted = page.store.recently_deleted()
    assert {e["item"]["code"] for e in deleted} >= set(codes)
    assert len({e.get("batch") for e in deleted if e["item"]["code"] in codes}) == 1
    # «برگرداندن حذف‌شده‌ها…»: the first choice brings the whole group back
    monkeypatch.setattr(site_page.QInputDialog, "getItem",
                        lambda _p, _t, _l, choices, *_a: (choices[0], True))
    page._undelete()
    assert page.phones_table.rowCount() == before
    assert all(page.store.get(c) is not None for c in codes)


def test_without_ticks_the_selected_row_is_used(page, monkeypatch):  # noqa: F811
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    table = page.phones_table
    code = table.row_key(0)
    table.select_row(0)
    page.delete_phone_button.click()
    assert page.store.get(code) is None
    assert page.store.undelete(code)


def test_accessories_have_the_same_tools(page):  # noqa: F811
    assert page.accessories_table.columnCount() == len(site_page.ACCESSORY_HEADERS)
    assert page.accessory_select_all.text() == "انتخاب همه"
    assert page.hide_accessory_button.text() == "پنهان"
    assert page.show_accessory_button.text() == "نمایش"


def test_store_bulk_helpers(page):  # noqa: F811
    store = page.store
    codes = [i["code"] for i in store.items(cat.KIND_PHONE)[:3]]
    assert len(codes) >= 2
    assert store.set_hidden_many(codes, True) == len(codes)
    assert store.set_hidden_many(codes, True) == 0           # already hidden
    removed = store.delete_many(codes + ["no-such-code"])
    assert [i["code"] for i in removed] == codes
    assert store.undelete_many(codes) == len(codes)
    assert all(store.get(c)["hidden"] for c in codes)        # came back as they were
