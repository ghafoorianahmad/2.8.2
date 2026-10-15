"""v2.6.2 in ShopAdmin: PDF drag & drop on «لیست قیمت» (same path as the button), the
«خودکار» mapping state with confirm / undo / run, the customer-cancel notifications,
and who cancelled an order."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402

from app.statuses import ROLE_VIEWER  # noqa: E402
from app.ui.pages import pricelist as pl  # noqa: E402

from .test_pricelist import PDF, _lists_tab, _page, _pump, _select  # noqa: E402
from .test_ui import ui_context  # noqa: E402,F401


def _mime(*paths) -> QMimeData:
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return data


def _drop(page, mime):
    enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dragEnterEvent(enter)
    if not enter.isAccepted():
        return False
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dropEvent(drop)
    return drop.isAccepted()


def test_dropped_pdf_helper(tmp_path):
    assert pl.dropped_pdf([QUrl.fromLocalFile(str(tmp_path / "a.txt")),
                           QUrl.fromLocalFile(str(tmp_path / "List.PDF"))]).endswith("List.PDF")
    assert pl.dropped_pdf([QUrl.fromLocalFile(str(tmp_path / "a.png"))]) is None
    assert pl.dropped_pdf([]) is None


def test_drag_and_drop_uploads_like_the_button(ui_context, fake_api, admin_qapp, tmp_path,
                                               monkeypatch):
    infos = []
    monkeypatch.setattr("app.ui.widgets.info", lambda *a, **k: infos.append((a, k)))
    pdf = tmp_path / "drop list.pdf"
    pdf.write_bytes(PDF)
    page = _page(ui_context, admin_qapp)
    assert page.acceptDrops()
    _lists_tab(page, admin_qapp)
    assert _drop(page, _mime(pdf))
    _pump(admin_qapp, page)
    assert len(fake_api.price_uploads) == 1
    assert fake_api.price_uploads[0]["source_ref"] == "drop list.pdf"
    # not a PDF: refused before anything is sent
    other = tmp_path / "photo.png"
    other.write_bytes(b"\x89PNG")
    assert not _drop(page, _mime(other))
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"MZ not a pdf")
    _drop(page, _mime(fake_pdf))
    _pump(admin_qapp, page)
    assert len(fake_api.price_uploads) == 1
    page.close()


def test_viewer_cannot_drop(ui_context, fake_api, admin_qapp, tmp_path):
    pdf = tmp_path / "l.pdf"
    pdf.write_bytes(PDF)
    page = _page(ui_context, admin_qapp, role=ROLE_VIEWER)
    assert not page.acceptDrops() and not _drop(page, _mime(pdf))
    assert fake_api.price_uploads == []
    page.close()


def test_upload_reports_automatic_mappings(ui_context, fake_api, admin_qapp, tmp_path,
                                           monkeypatch):
    infos = []
    monkeypatch.setattr("app.ui.widgets.info", lambda *a, **k: infos.append((a, k)))
    fake_api.upload_outcome, fake_api.upload_auto = "held", 4
    pdf = tmp_path / "l.pdf"
    pdf.write_bytes(PDF)
    page = _page(ui_context, admin_qapp)
    page.upload_pdf_file(str(pdf))
    _pump(admin_qapp, page)
    assert "۴ ردیف خودکار" in infos[0][0][2]
    page.close()


# ---- automatic mappings ----------------------------------------------------------------------
def test_row_states_include_automatic():
    assert pl.row_state({"action": "map", "auto": 1}) == "auto_mapped"
    assert pl.row_state({"action": "ignore", "auto": 1}) == "auto_ignored"
    assert pl.row_state({"action": "map", "auto": 0}) == "mapped"
    assert pl.row_state_fa({"action": "map", "auto": 1}) == "نگاشت خودکار"
    assert ("auto", "خودکار (بازبینی)") in pl.FILTERS


def test_confirm_undo_and_run_automatic(ui_context, fake_api, admin_qapp, monkeypatch):
    fake_api.add_pricelist()
    fake_api.add_price_row("17 Pro 256 ZAA", "Silver", action="map", kala_code=900)
    fake_api.add_price_row("17 Pro 256 ZAA", "Orange", action="map", kala_code=900, auto=True)
    fake_api.add_price_row("17 Pro 256 CHA", "Silver", action="map", kala_code=900, auto=True)
    page = _page(ui_context, admin_qapp, filter_key="auto")
    assert page.rows_table.rowCount() == 2
    assert page.rows_table.item(0, 7).text() == "نگاشت خودکار"
    assert "رنگ یا پارت" in page.rows_table.item(0, 7).toolTip()
    assert "(۲)" in page.filter_combo.itemText(page.filter_combo.findData("auto"))
    _select(page.rows_table, 0)
    page._confirm_selected()
    _pump(admin_qapp, page)
    assert fake_api.price_rows[1]["auto"] == 0
    page._load_rows()
    _pump(admin_qapp, page)
    assert page.rows_table.rowCount() == 1
    _select(page.rows_table, 0)
    page._undo_selected()
    _pump(admin_qapp, page)
    assert fake_api.price_rows[2]["action"] is None                 # back to «نگاشت‌نشده»
    page._run_auto()
    _pump(admin_qapp, page)
    assert getattr(fake_api, "auto_runs", 0) == 1
    page.close()


# ---- customer cancel ---------------------------------------------------------------------------
def test_customer_cancel_notifications():
    from app.notifications import ATTENTION_KINDS, KIND_CUSTOMER_CANCEL, notice_for

    notice = notice_for({"kind": "order_cancelled_by_customer", "ref_id": 7})
    assert notice is not None and "۷" in notice.body and notice.target == ("orders", "cancelled")
    assert KIND_CUSTOMER_CANCEL in ATTENTION_KINDS
    written = notice_for({"kind": "order_cancel_written", "ref_id": 7})
    assert written is not None and written.warning and "سازه حساب" in written.body


def test_orders_show_who_cancelled():
    from app.ui.pages.orders import tracking_fa

    assert "مشتری" in tracking_fa({"status": "cancelled", "cancel_reason": "customer"})
    assert "خودکار" in tracking_fa({"status": "cancelled", "cancel_reason": "receipt_timeout"})
    assert tracking_fa({"status": "approved"}) == "—"


# ---- build: pytest never depends on a shared %TEMP% ---------------------------------------------
def test_build_all_gives_pytest_a_fresh_temp_root():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "build_all.bat").read_text(encoding="utf-8")
    setup = text.index('set "TEMP=%SHOP_TEST_TMP%"')
    assert setup < text.index(r'call "%ROOT%shopsystem\build_exe.bat"')  # before every pytest
    assert 'set "TMP=%SHOP_TEST_TMP%"' in text and "%RANDOM%" in text
    assert 'set "PYTEST_ADDOPTS=-p no:cacheprovider"' in text
    assert b"\r\n" in (Path(__file__).resolve().parents[2] / "build_all.bat").read_bytes()
