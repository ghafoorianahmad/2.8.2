"""Phase 3: the «لیست قیمت» page (rows + mapping, received lists, Telegram proxies)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from app.permissions import (  # noqa: E402
    PRICELIST_MANAGE,
    PRICELIST_VIEW,
    PROXIES_MANAGE,
    has_permission,
)
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER  # noqa: E402
from app.ui.pages import pricelist as pl  # noqa: E402
from app.ui.pages.pricelist import AddProxyDialog, MapRowDialog, PriceListPage  # noqa: E402

from .test_ui import PERSIAN_RE, _render_page, make_context_with_role, ui_context  # noqa: E402,F401

PDF = b"%PDF-1.4 test list"


# ---- pure helpers -------------------------------------------------------------------
def test_row_state_and_labels():
    assert pl.row_state({"action": "map"}) == "mapped"
    assert pl.row_state({"action": "ignore"}) == "ignored"
    assert pl.row_state({"action": None}) == "unmapped"
    assert pl.row_state_fa({}) == "نگاشت‌نشده"
    assert pl.pdf_price(52500) == "۵۲,۵۰۰" or pl.pdf_price(52500).replace("٬", ",") == "۵۲,۵۰۰"
    assert pl.pdf_price(None) == "—" and pl.pdf_price(0) == "—"
    assert pl.filter_label("unmapped", {"unmapped": 3}) == "نگاشت‌نشده (۳)"
    assert pl.filter_label("all", {}) == "همهٔ ردیف‌ها"


def test_search_matches_model_color_and_arabic_letters():
    row = {"section": "iPHONE", "description": "17 Promax 256 ZAA", "kind": "شرکتی",
           "color": "Silver", "color_label": "نقره‌ای"}
    assert pl.matches(row, "")
    assert pl.matches(row, "promax silver")
    assert pl.matches(row, "شركتي")              # Arabic kaf/yeh typed
    assert not pl.matches(row, "promax blue")


def test_permissions_per_role():
    # v2.7.0: «مدیر» only; «کاربر فروش» (operator / old viewer) never sees the list
    for role in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        assert has_permission(role, PRICELIST_VIEW) and has_permission(role, PRICELIST_MANAGE)
    for role in (ROLE_VIEWER, ROLE_OPERATOR):
        assert not has_permission(role, PRICELIST_VIEW)
    assert not has_permission(ROLE_OPERATOR, PROXIES_MANAGE)
    assert has_permission(ROLE_SUPER_ADMIN, PROXIES_MANAGE)


# ---- page ---------------------------------------------------------------------------------
def _seed(fake_api):
    fake_api.add_price_row("17 Promax 256 ZAA", "Silver")
    fake_api.add_price_row("17 Promax 256 ZAA", "Blue", action="map", kala_code=289,
                           color_label="آبی")
    fake_api.add_price_row("Redmi 13", "Black", section="XIAOMI", naghd=None, raval=None)
    fake_api.add_price_row("A55", "Gray", section="SAMSUNG", action="ignore")
    fake_api.add_pricelist()


def _page(ui_context, admin_qapp, role=ROLE_SUPER_ADMIN, *, filter_key="all"):
    context = make_context_with_role(ui_context, role)
    page = PriceListPage(context)
    page.filter_combo.blockSignals(True)
    page.filter_combo.setCurrentIndex(page.filter_combo.findData(filter_key))
    page.filter_combo.blockSignals(False)
    _render_page(admin_qapp, page)
    return page


def _select(table, *rows):
    model = table.selectionModel()
    model.clearSelection()
    for r in rows:
        model.select(table.model().index(r, 0),
                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def _pump(admin_qapp, page):
    _render_page(admin_qapp, page, load=False)


def test_page_title_is_persian(ui_context):
    page = PriceListPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert PERSIAN_RE.search(page.title) and PERSIAN_RE.search(page.subtitle)
    page.close()


def test_rows_load_with_counts_sections_and_prices(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)
    table = page.rows_table
    assert table.rowCount() == 4
    assert table.item(0, 1).text() == "17 Promax 256 ZAA"
    assert table.item(0, 7).text() == "نگاشت‌نشده"
    assert "←" in table.item(1, 3).text() and table.item(1, 8).text() == "۲۸۹"
    assert table.item(2, 6).text() == "ناموجود"
    assert [page.section_combo.itemData(i) for i in range(page.section_combo.count())] == \
        [None, "iPHONE", "XIAOMI", "SAMSUNG"]
    assert page.filter_combo.itemText(0) == "نگاشت‌نشده (۲)"
    assert page.banner.isVisible() and "۲ ردیف" in page.banner.text()
    assert "۴ ردیف" in page.rows_summary.text()
    page.close()


def test_default_filter_is_unmapped_and_search_filters_locally(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp, filter_key="unmapped")
    assert page.rows_table.rowCount() == 2
    assert ("GET", "/admin/pricelists/rows") in fake_api.requests
    page.row_search.setText("redmi")
    assert page.rows_table.rowCount() == 1
    assert page.rows_table.item(0, 1).text() == "Redmi 13"
    page.close()


def test_section_filter_is_sent_to_the_server(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)
    page.section_combo.setCurrentIndex(page.section_combo.findData("XIAOMI"))
    _pump(admin_qapp, page)
    assert page.rows_table.rowCount() == 1
    assert page.section_combo.currentData() == "XIAOMI"     # kept after the reload
    page.close()


def test_no_list_yet_shows_the_upload_hint(ui_context, fake_api, admin_qapp):
    page = _page(ui_context, admin_qapp)
    assert page.rows_table.rowCount() == 0
    assert "بارگذاری" in page.banner.text()
    page.close()


def test_held_list_banner_shows_the_reason(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    fake_api.pricelists[-1].update(status="held", reason="تغییر قیمت ۲۰٪")
    page = _page(ui_context, admin_qapp)
    assert "نگه‌داشته" in page.banner.text() and "تغییر قیمت" in page.banner.text()
    page.close()


def test_map_selected_row(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)

    def fake_exec(dialog):
        dialog.code_input.setValue(777)
        dialog.color_input.setText("نقره‌ای")
        dialog._accept()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(MapRowDialog, "exec", fake_exec)
    _select(page.rows_table, 0)
    page._map_selected()
    _pump(admin_qapp, page)
    row = fake_api.price_rows[0]
    assert (row["action"], row["kala_code"], row["color_label"]) == ("map", 777, "نقره‌ای")
    assert page.rows_table.item(0, 7).text() == "نگاشت‌شده"
    page.close()


def test_map_needs_exactly_one_row(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)
    opened = []
    monkeypatch.setattr(MapRowDialog, "exec", lambda d: opened.append(d) or 0)
    _select(page.rows_table, 0, 2)
    page._map_selected()
    assert opened == []
    assert not any(m == "PUT" for m, _ in fake_api.requests)
    page.close()


def test_ignore_and_clear_selected_rows(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _select(page.rows_table, 0, 2)
    page._ignore_selected()
    _pump(admin_qapp, page)
    assert [r["action"] for r in fake_api.price_rows] == ["ignore", "map", "ignore", "ignore"]
    _select(page.rows_table, 1, 2)          # the mapped Blue row + an ignored row
    page._clear_selected()
    _pump(admin_qapp, page)
    assert fake_api.price_rows[1]["action"] is None and fake_api.price_rows[2]["action"] is None
    assert ("DELETE", "/admin/price-mappings/102") in fake_api.requests
    page.close()


def test_ignore_cancelled_sends_nothing(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: False)
    page = _page(ui_context, admin_qapp)
    _select(page.rows_table, 0)
    page._ignore_selected()
    _pump(admin_qapp, page)
    assert ("POST", "/admin/price-mappings/ignore") not in fake_api.requests
    page.close()


def test_operator_sees_rows_but_cannot_change_them(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp, ROLE_OPERATOR)
    assert page.rows_table.rowCount() == 4
    for b in (page.map_button, page.ignore_button, page.clear_button, page.upload_button,
              page.approve_button, page.reject_button):
        assert not b.isEnabled()
    assert page.tabs.count() == 3      # rows, lists, channel posts (no proxies tab)
    opened = []
    monkeypatch.setattr(MapRowDialog, "exec", lambda d: opened.append(d) or 0)
    _select(page.rows_table, 0)
    page._map_selected()                                # double-click path
    assert opened == []
    page.close()


def test_manager_has_every_tab(ui_context, fake_api, admin_qapp):
    page = _page(ui_context, admin_qapp, ROLE_ADMIN)               # old "admin" = «مدیر»
    assert page.tabs.count() == 4 and page.map_button.isEnabled()
    page.close()


# ---- received lists -----------------------------------------------------------------------
def _lists_tab(page, admin_qapp):
    page.tabs.setCurrentIndex(1)
    _pump(admin_qapp, page)


def test_lists_tab_and_approve_held(ui_context, fake_api, admin_qapp, monkeypatch):
    fake_api.add_pricelist(status="superseded", list_date="1405/07/18")
    fake_api.add_pricelist(status="held", list_date="1405/07/19", reason="۳ ردیف بیش از ۱۵٪")
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _lists_tab(page, admin_qapp)
    table = page.lists_table
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "۱۴۰۵/۰۷/۱۹" and table.item(0, 2).text() == "کانال تلگرام"
    _select(table, 1)                                     # not held -> refused locally
    page._approve_list()
    _pump(admin_qapp, page)
    assert not any(p.endswith("/approve") for _, p in fake_api.requests)
    _select(table, 0)
    page._approve_list()
    _pump(admin_qapp, page)
    assert fake_api.pricelists[1]["status"] == "active"
    page.close()


def test_reject_held_list(ui_context, fake_api, admin_qapp, monkeypatch):
    fake_api.add_pricelist(status="held")
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _lists_tab(page, admin_qapp)
    _select(page.lists_table, 0)
    page._reject_list()
    _pump(admin_qapp, page)
    assert fake_api.pricelists[0]["status"] == "rejected"
    page.close()


def test_upload_pdf(ui_context, fake_api, admin_qapp, monkeypatch, tmp_path):
    pdf = tmp_path / "list.pdf"
    pdf.write_bytes(PDF)
    monkeypatch.setattr(pl.QFileDialog, "getOpenFileName", lambda *a, **k: (str(pdf), "PDF"))
    infos = []
    monkeypatch.setattr("app.ui.widgets.info", lambda *a, **k: infos.append((a, k)))
    page = _page(ui_context, admin_qapp)
    _lists_tab(page, admin_qapp)
    page._upload_pdf()
    _pump(admin_qapp, page)
    assert len(fake_api.price_uploads) == 1
    assert fake_api.price_uploads[0]["source_ref"] == "list.pdf"
    assert infos == []                                    # "active" = success toast only
    fake_api.upload_outcome = "held"
    page._upload_pdf()
    _pump(admin_qapp, page)
    assert len(infos) == 1 and "تغییر قیمت" in infos[0][1]["detail"]
    page.close()


def test_upload_refuses_non_pdf(ui_context, fake_api, admin_qapp, monkeypatch, tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"MZ not a pdf")
    monkeypatch.setattr(pl.QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), "PDF"))
    page = _page(ui_context, admin_qapp)
    page._upload_pdf()
    _pump(admin_qapp, page)
    assert fake_api.price_uploads == []
    monkeypatch.setattr(pl.QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    page._upload_pdf()                                    # cancelled dialog
    assert fake_api.price_uploads == []
    page.close()


# ---- proxies ---------------------------------------------------------------------------------
def test_proxies_tab_add_toggle_delete(ui_context, fake_api, admin_qapp, monkeypatch):
    fake_api.proxies = [{"id": 1, "host": "a.example", "port": 443, "kind": "ee", "state": "main",
                         "stability": 0.93, "good_days": 14, "checked_days": 15,
                         "last_ok_at": "2026-10-11T10:00:00", "failing_now": False}]
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    page.tabs.setCurrentIndex(3)          # v2.9.1: «پیام‌های کانال» is the third tab
    _pump(admin_qapp, page)
    table = page.proxy_table
    assert table.rowCount() == 1
    assert table.item(0, 3).text() == "اصلی" and table.item(0, 4).text() == "۹۳٪"
    assert table.item(0, 7).text() == "سالم"

    def add_exec(dialog):
        dialog.input.setText("tg://proxy?server=new.example&port=443&secret=dd" + "ab" * 16)
        dialog.main_check.setChecked(True)
        dialog._accept()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(AddProxyDialog, "exec", add_exec)
    page._add_proxy()
    _pump(admin_qapp, page)
    assert fake_api.proxy_adds[0]["main"] is True and table.rowCount() == 2

    _select(table, 0)
    page._toggle_proxy()
    _pump(admin_qapp, page)
    assert fake_api.proxies[0]["state"] == "disabled"
    _select(table, 0)
    page._toggle_proxy()
    _pump(admin_qapp, page)
    assert fake_api.proxies[0]["state"] == "probation"

    _select(table, 1)
    page._delete_proxy()
    _pump(admin_qapp, page)
    assert [p["id"] for p in fake_api.proxies] == [1]
    page.close()


def test_add_proxy_dialog_validates(admin_qapp):
    dialog = AddProxyDialog()
    dialog.input.setText("https://example.com")
    dialog._accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error_label.text()
    dialog.input.setText("https://t.me/proxy?server=h&port=1&secret=" + "ab" * 16)
    dialog._accept()
    assert dialog.link.startswith("https://t.me/proxy") and dialog.main is False
    dialog.close()


# ---- mapping dialog ------------------------------------------------------------------------
def test_map_dialog_search_pick_and_validation(ui_context, fake_api, admin_qapp):
    fake_api.products = {289: {"code": 289, "name": "17 Promax 256", "group": 1,
                               "unit_price": 1.0, "available_qty": 0.0, "image": None}}
    row = fake_api.add_price_row("17 Promax 256 ZAA", "Silver")
    dialog = MapRowDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), row)
    assert dialog.search.text() == "17"
    dialog._accept()                                       # no product yet
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error_label.text()
    dialog._search()
    assert dialog.results.count() == 1
    dialog.results.setCurrentRow(0)
    assert dialog.code_input.value() == 289
    dialog.color_input.setText("  نقره‌ای ")
    dialog._accept()
    assert (dialog.kala_code, dialog.color_label) == (289, "نقره‌ای")
    dialog.close()


def test_map_dialog_reports_no_match(ui_context, fake_api, admin_qapp):
    row = fake_api.add_price_row("Nothing", "Red")
    dialog = MapRowDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), row)
    dialog._search()
    assert dialog.results.count() == 0 and "پیدا نشد" in dialog.error_label.text()
    dialog.close()


def test_page_loads_without_callback_errors(ui_context, fake_api, admin_qapp, caplog):
    import logging
    _seed(fake_api)
    with caplog.at_level(logging.ERROR, logger="shopadmin.worker"):
        page = _page(ui_context, admin_qapp)
        for index in range(page.tabs.count()):
            page.tabs.setCurrentIndex(index)
            _pump(admin_qapp, page)
    assert not [r.message for r in caplog.records if "callback failed" in r.message]
    page.close()
