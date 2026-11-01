"""v2.14.0 «سایت» › «کالاها»: the tree, PDF import preview, delete, pill toggle,
counters, and the list behaviour (one click selects, a reload keeps the row)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from app.site import catalog as cat  # noqa: E402
from app.site import pdf_import as imp  # noqa: E402
from app.ui import site_import as si  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.pages import site as site_page  # noqa: E402
from app.ui.pages.site import SitePage  # noqa: E402

from .test_catalog_models import _select  # noqa: E402
from .test_ui import _render_page, ui_context  # noqa: E402,F401
from .test_v2110_site import image_bytes, site_folder  # noqa: E402,F401
from .test_v2140_site import SAMPLE  # noqa: E402


@pytest.fixture
def page(admin_qapp, ui_context, site_folder, monkeypatch):
    monkeypatch.setattr(widgets, "success", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "info", lambda *a, **k: None)
    page = SitePage(ui_context)
    page.store.seed_from_folder(site_folder)
    _render_page(admin_qapp, page)
    return page


def _node(page, kind, key=""):
    for item in page._tree_items():
        if list(item.data(0, Qt.ItemDataRole.UserRole)) == [kind, key]:
            page.tree.setCurrentItem(item)
            return item
    raise AssertionError((kind, key))


def test_tree_has_phones_by_brand_and_accessory_groups(page):
    tops = [page.tree.topLevelItem(n).text(0) for n in range(page.tree.topLevelItemCount())]
    assert tops[0].startswith("گوشی‌ها") and tops[1].startswith("لوازم جانبی")
    _node(page, site_page.NODE_BRAND, "apple")
    assert all(p["brand"] == "apple" for p in page._phones)
    assert not page.pdf_button.isEnabled()          # PDF only into an accessory category
    _node(page, site_page.NODE_GROUP, "powerbank")
    assert page.stack.currentIndex() == 1 and page.pdf_button.isEnabled()
    assert "پاوربانک" in page.branch_hint.text()


def test_counter_text(page):
    phones = page.store.items(cat.KIND_PHONE)
    page.store.set_hidden(phones[0]["code"], True)
    page.render()
    assert page.phones_summary.text() == site_page.count_text(
        page.store.counts(cat.KIND_PHONE), "گوشی")
    assert "پنهان)" in page.phones_summary.text() and "در سایت" in page.phones_summary.text()


def test_new_branch_rename_and_manual_add(page, monkeypatch):
    _node(page, site_page.NODE_ACCESSORIES)
    monkeypatch.setattr(page, "_ask_name", lambda *a, **k: "ساعت هوشمند")
    page._new_branch()
    kind, key = page._node
    assert kind == site_page.NODE_GROUP and page.store.group_name(key) == "ساعت هوشمند"
    monkeypatch.setattr(page, "_ask_name", lambda *a, **k: "ساعت و مچ‌بند")
    page._rename_branch()
    assert page.store.group_name(key) == "ساعت و مچ‌بند"
    seen = {}

    def fake_exec(dialog):
        seen["group"] = dialog.group.currentData()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(site_page.AccessoryDialog, "exec", fake_exec)
    page._add_manual()
    assert seen["group"] == key


def test_pill_toggles_and_delete_with_undo(page, monkeypatch):
    _node(page, site_page.NODE_PHONES)
    code = page._phones[0]["code"]
    page._toggle_code(code)
    assert page.store.get(code)["hidden"]
    pill = page.phones_table.cellWidget(0, 5).findChild(widgets.TogglePill)
    assert pill.text() == "پنهان"
    pill.clicked.emit()
    assert not page.store.get(code)["hidden"]
    monkeypatch.setattr(site_page.widgets, "confirm", lambda *a, **k: True)
    _select(page.phones_table, 0)
    page._delete(cat.KIND_PHONE)
    assert page.store.get(code) is None and page.undelete_button.isEnabled()
    monkeypatch.setattr(site_page.QInputDialog, "getItem",
                        lambda _p, _t, _l, names, *_a: (names[0], True))
    page._undelete()
    assert page.store.get(code) is not None


def test_one_click_selects_and_reload_keeps_row_and_scroll(page, admin_qapp, monkeypatch):
    monkeypatch.setattr(site_page.PhoneDialog, "exec", lambda _d: QDialog.DialogCode.Rejected)
    table = page.phones_table
    opened = []
    table.row_activated.connect(opened.append)
    table.cellClicked.emit(1, 1)
    assert opened == []                              # one click: select only
    table.select_row(1)
    key = table.row_key(1)
    page.render()
    rows = sorted({i.row() for i in table.selectionModel().selectedRows()})
    assert rows and table.row_key(rows[0]) == key
    assert table.activate_selected() and opened == [rows[0]]


def test_preview_button_gone_and_change_list_updates_itself(page):
    assert not hasattr(page, "preview_button")
    code = page.store.items(cat.KIND_PHONE)[0]["code"]
    page._toggle_code(code)
    assert "از سایت برداشته می‌شود" in page.preview_box.toPlainText()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample PDF not on this computer")
def test_pdf_import_dialog_preview_and_save(page, admin_qapp, monkeypatch):
    dialog = si.PdfImportDialog(page.store, "powerbank", SAMPLE.read_bytes(), parent=page)
    assert dialog.table.rowCount() == 35
    assert "تازه: ۳۵" in dialog.summary.text()
    dialog.table.item(0, 1).setText("پاوربانک ADATA T10000")       # per-row edit
    dialog._remove(1)                                               # per-row remove
    assert "کنار گذاشته: ۱" in dialog.summary.text()
    dialog._save()
    assert dialog.result_counts["new"] == 34
    names = [i["name"] for i in page.store.items(cat.KIND_ACCESSORY)]
    assert "پاوربانک ADATA T10000" in names
    again = si.PdfImportDialog(page.store, "powerbank", SAMPLE.read_bytes(), parent=page)
    counts = imp.summary(again.rows)
    assert counts["duplicate"] + counts["updated"] == 34 and counts["new"] == 1
