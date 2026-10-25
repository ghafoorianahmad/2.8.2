"""v2.9.3: right-to-left everywhere (and the audit that checks it), one button
look, tidy dialog footers, the order dialog, cancel with a reason, the price
message with staff's own words, the look applied on a click, the proxy table,
the server setup's «دادن دسترسی به این دیتابیس» and the site models."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPlainTextEdit, QWidget  # noqa: E402

from app import activity, notifications  # noqa: E402
from app.statuses import ROLE_SUPER_ADMIN  # noqa: E402
from app.ui import rtl, widgets  # noqa: E402

from .test_ui import make_context_with_role, ui_context  # noqa: E402,F401

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _pump(rounds: int = 60, until=None) -> None:
    for _ in range(rounds):
        QApplication.processEvents()
        if until is not None and until():
            return


@pytest.fixture
def audits(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import button_audit
    import rtl_audit

    return rtl_audit, button_audit


# ---- right to left ---------------------------------------------------------------
def test_mixed_text_gets_a_right_to_left_mark():
    text = "ahmad سفارش را لغو کرد"
    assert rtl.needs_rlm(text)
    fixed = rtl.fix_mixed(text)
    assert fixed == rtl.RLM + text and not rtl.needs_rlm(fixed)
    assert rtl.fix_mixed("سفارش ahmad لغو شد") == "سفارش ahmad لغو شد"     # starts Persian
    assert rtl.fix_mixed("C:\\Data") == "C:\\Data"                         # Latin only
    assert rtl.bidi("ZAA-256").startswith(rtl.LRE)
    two = rtl.fix_mixed("سلام\nok باشد")
    assert two.split("\n")[1].startswith(rtl.RLM)


def test_labels_and_timeline_never_scramble_a_latin_first_sentence(admin_qapp):
    label = widgets.label("ahmad قیمت را فرستاد")
    assert label.text().startswith(rtl.RLM)
    label.setText("Sara Karimi یادداشت گذاشت")
    assert label.text().startswith(rtl.RLM)


def test_every_multi_line_box_is_right_to_left(admin_qapp):
    box = QPlainTextEdit()
    box.show()
    _pump(5)
    assert rtl.document_is_rtl(box)          # the program-wide filter (theme.apply_theme)
    log = rtl.mark_ltr(QPlainTextEdit())
    log.show()
    _pump(5)
    assert not rtl.document_is_rtl(log) and rtl.is_marked_ltr(log)
    box.close()
    log.close()


def test_rtl_audit_finds_the_mistakes(admin_qapp, audits):
    rtl_audit, _ = audits
    root = QWidget()
    root.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    unmarked = QLineEdit(root)
    unmarked.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    code = QLineEdit(root)
    code.setPlaceholderText("https://192.168.1.10:8443")
    box = QPlainTextEdit(root)
    mixed = widgets.label("", wrap=True)
    mixed.setParent(root)
    super(widgets.BidiLabel, mixed).setText("ahmad سفارش را لغو کرد")   # no mark
    root.show()
    _pump(5)
    option = box.document().defaultTextOption()
    option.setTextDirection(Qt.LayoutDirection.LeftToRight)
    box.document().setDefaultTextOption(option)
    found = "\n".join(rtl_audit.problems_in(root, "t"))
    assert "not marked as a code field" in found
    assert "must be left-to-right" in found
    assert "without a right-to-left document" in found
    assert "mixed text without a right-to-left mark" in found
    rtl.mark_ltr(code)
    unmarked.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    rtl.rtl_text(box)
    mixed.setText(mixed.text())
    assert rtl_audit.problems_in(root, "t") == []
    root.close()


# ---- buttons and footers --------------------------------------------------------------
def test_footer_puts_prominent_first_and_close_last(admin_qapp):
    other = widgets.button("ارجاع")
    main = widgets.button("ثبت", variant="primary")
    close = widgets.button("بستن")
    row = widgets.footer(other, main, close=close)
    order = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]
    assert order == [main, other, close]


def test_button_audit_finds_plain_text_buttons_and_a_wrong_footer(admin_qapp, audits):
    _, button_audit = audits
    dialog = QDialog()
    dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dialog.resize(600, 300)
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    root = QVBoxLayout(dialog)
    root.addStretch(1)
    row = QHBoxLayout()
    ghost = widgets.button("بستن", variant="ghost")
    row.addWidget(ghost)
    row.addWidget(widgets.button("ثبت", variant="primary"))
    root.addLayout(row)
    dialog.show()
    _pump(5)
    found = "\n".join(button_audit.problems_in(dialog, "d", button_audit.standard_height()))
    assert "looks like plain text" in found
    dialog.close()


def test_every_button_variant_is_equally_tall_and_disabled_looks_disabled(admin_qapp, audits):
    _, button_audit = audits
    heights = set()
    for variant in ("default", "primary", "success", "danger"):
        button = widgets.button("ارسال", variant=variant)
        button.ensurePolished()
        heights.add(button.sizeHint().height())
    assert len(heights) == 1
    assert button_audit.theme_problems("t") == []


# ---- order dialog, cancel ------------------------------------------------------------------
def test_timeline_is_one_line_per_action_with_its_time(admin_qapp):
    lines = activity.timeline_lines([
        {"action": "price_offer", "actor_name": "ahmad", "ts": "2026-10-25T10:00:00+00:00"},
        {"action": "ship", "is_me": True, "ts": "2026-10-25T11:30:00+00:00"}])
    assert len(lines) == 2 and lines[1][1] == "شما ارسال کرد"
    view = widgets.TimelineView()
    view.set_lines(lines)
    assert view.lines == lines
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_order_dialog_wraps_the_full_product_name(ui_context, admin_qapp, fake_api):
    from app.ui.pages.orders import OrderDetailDialog

    name = "SAMSUNG Galaxy S26 Ultra 512GB 12GB RAM — Titanium Silverblue (ZAA)"
    order = fake_api.add_order(status="awaiting_payment",
                               items=[{"kala_code": 5, "name": name, "qty": 1.0,
                                       "unit_price": 10.0}])
    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), order)
    table = dialog.items_table
    assert table.item(0, 1).text() == name
    assert table.wordWrap() and table.textElideMode() == Qt.TextElideMode.ElideNone
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    dialog.close()


def test_cancel_sends_the_reason(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import orders

    order = fake_api.add_order(status="awaiting_payment")

    def fake_exec(dialog):
        dialog.reason_input.setText("  این رنگ   تمام شد ")
        dialog._accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(orders.CancelOrderDialog, "exec", fake_exec)
    dialog = orders.OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), order)
    dialog._cancel_order()
    _pump(until=lambda: order["status"] == "cancelled")
    assert order["status"] == "cancelled" and order["cancel_note"] == "این رنگ تمام شد"
    assert "لغو توسط فروشگاه — دلیل: این رنگ تمام شد" == orders.tracking_fa(order)


# ---- purchase request -----------------------------------------------------------------------
def _purchase(fake_api) -> dict:
    row = {"id": 31, "kind": "purchase", "status": "seen", "text": "", "platform": "bale",
           "customer_name": "x", "created_at": "2026-10-25T10:00:00+00:00",
           "product_name": "iPhone 17 Pro", "kala_code": 12, "price_rial": 500_000_000,
           "qty": 1}
    fake_api.item_requests.append(row)
    return row


def test_typed_message_goes_with_the_price(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests

    row = _purchase(fake_api)
    dialog = item_requests.ItemRequestDialog(
        make_context_with_role(ui_context, ROLE_SUPER_ADMIN), row)
    dialog.message_edit.setPlainText("گارانتی ۱۸ ماهه دارد")
    seen = {}

    def fake_exec(confirm):
        seen["note"] = confirm.note_label.text()
        confirm._accept_list()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(item_requests.StockConfirmDialog, "exec", fake_exec)
    monkeypatch.setattr(widgets, "info", lambda *a, **k: None)
    dialog.confirm_stock()
    _pump(until=lambda: fake_api.stock_confirms)
    _pump(30)
    assert seen["note"] == "گارانتی ۱۸ ماهه دارد"
    assert fake_api.stock_confirms[-1]["note"] == "گارانتی ۱۸ ماهه دارد"
    assert dialog.message_edit.toPlainText() == ""
    dialog._closing_checked = True
    dialog.close()


def test_closing_with_unsent_text_asks_first(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests

    row = _purchase(fake_api)
    dialog = item_requests.ItemRequestDialog(
        make_context_with_role(ui_context, ROLE_SUPER_ADMIN), row)
    dialog.show()
    dialog.message_edit.setPlainText("سلام")
    asked = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: asked.append(a[2]) or False)
    dialog.accept()
    assert asked and "پیام به مشتری" in asked[0]
    assert dialog.result() != QDialog.DialogCode.Accepted
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_message_history_wraps_without_a_side_scroll_bar(ui_context, admin_qapp, fake_api):
    from app.ui.pages import item_requests

    row = _purchase(fake_api)
    dialog = item_requests.ItemRequestDialog(
        make_context_with_role(ui_context, ROLE_SUPER_ADMIN), row)
    assert dialog.history.wordWrap()
    assert dialog.history.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    dialog._closing_checked = True
    dialog.close()


# ---- look on a click ---------------------------------------------------------------------
def test_a_click_applies_and_saves_the_look(ui_context, admin_qapp, monkeypatch):
    from app.ui import appearance

    applied = []
    ui_context.apply_look = lambda: applied.append(appearance.saved_look(ui_context.store))
    monkeypatch.setattr(appearance.QTimer, "singleShot", lambda _ms, fn: fn())
    picker = appearance.AppearancePicker(ui_context.store, context=ui_context)
    picker.cards["mode"]["dark"].click()
    picker.apply_now()                          # the short delay, now
    assert appearance.saved_look(ui_context.store)[1] == "dark"
    assert applied and applied[-1][1] == "dark"
    picker.cards["mode"]["light"].click()
    picker.apply_now()
    assert appearance.saved_look(ui_context.store)[1] == "light"


def test_notifications_dialog_has_no_save_button(ui_context, admin_qapp):
    from app.ui.main_window import NotificationDialog

    dialog = NotificationDialog(ui_context)
    texts = [b.text() for b in dialog.findChildren(type(widgets.button("x")))]
    assert "ذخیره" not in texts and "بستن" in texts
    dialog.close()


# ---- proxies, setup, notices -----------------------------------------------------------------
def test_proxy_states_and_full_address(ui_context, admin_qapp, fake_api):
    from app.ui.pages import server

    assert server.proxy_now_fa(False, True, slow=True).startswith("سالم ولی کند")
    host = "proxy-serving.mozitop-network.example.com"
    fake_api.proxies = [{"id": 1, "host": host, "port": 443, "kind": "ee", "state": "main",
                         "source": "manual", "last_ok_at": "2026-10-25T08:00:00+00:00",
                         "failing_now": False}]
    page = server.ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page.load()
    _pump(until=lambda: page.proxy_table.rowCount())
    table = page.proxy_table
    assert table.item(0, 0).text().endswith(f"{host}:443") or host in table.item(0, 0).text()
    assert "هرگز خودکار حذف نمی‌شود" in table.item(0, 5).text()
    assert table.textElideMode() == Qt.TextElideMode.ElideNone


def test_grant_result_and_access_error_kind():
    from app import server_setup as setup

    error = setup.DatabaseAccessError("x", "", "4060")
    assert error.kind == "db_access" and error.code == "4060"
    text = setup.grant_result_text({"login": "shopbot", "database": "hesab5",
                                    "steps": ["user_ready", "role_granted"], "check_ok": True})
    assert "«shopbot» به «hesab5»" in text and "اتصال فروشگاه" in text
    assert "db_owner" in setup.grant_result_text({"login": "a", "database": "b", "steps": [],
                                                 "note": "db_owner"})


def test_wizard_offers_access_after_a_permission_error(admin_qapp, monkeypatch):
    from app import server_setup as setup

    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "existing_config_port", lambda: None)
    monkeypatch.setattr(setup, "harden_data_dir", lambda *a, **k: None)
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: {"ok": True})

    def denied():
        raise setup.DatabaseAccessError("دسترسی ندارد", "", "4060")

    monkeypatch.setattr(setup, "check_database", denied)
    granted = []
    monkeypatch.setattr(setup, "grant_database_access",
                        lambda: granted.append(1) or {"login": "shopbot", "database": "hesab5",
                                                      "steps": ["role_granted"],
                                                      "check_ok": True})
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    from app.ui.server_setup_wizard import ServerSetupWizard

    wizard = ServerSetupWizard()
    try:
        wizard.db_name.setText("hesab5")
        wizard.db_user.setText("shopbot")
        wizard.db_password.setText("x")
        wizard._test_database()
        _pump(200, until=lambda: not wizard.grant_button.isHidden())
        assert not wizard.grant_button.isHidden()
        wizard._grant_access()
        _pump(200, until=lambda: granted and wizard._db_ok)
        assert granted and wizard._db_ok
        assert wizard.grant_button.isHidden()
    finally:
        wizard.close()
        wizard.deleteLater()


def test_new_site_models_are_announced():
    notice = notifications.notice_for({"kind": "site_models_new", "ref_id": 3})
    assert notice is not None and notice.target == ("catalog", "all")
    assert "۳ مدل تازه" in notice.body


def test_site_model_suggestion_can_be_accepted(ui_context, admin_qapp, fake_api):
    from app.ui.pages.catalog_models import CatalogModelsPage, has_suggestion

    model = fake_api.add_catalog_model("galaxy-a56", "Galaxy A56", "Samsung")
    model["suggestions"] = [{"kala_code": 77, "name": "گلکسی A56 256", "label": "256 گیگ"}]
    page = CatalogModelsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page.load()
    _pump(until=lambda: page._models)
    assert has_suggestion(page._models[0])
    page.set_filter("suggested")
    assert page.models_table.rowCount() == 1
    page._detail = page._models[0]
    page._accept_suggestion()
    _pump(until=lambda: fake_api.catalog_items)
    assert [i["kala_code"] for i in fake_api.catalog_items] == [77]
    page.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows fonts")
@pytest.mark.parametrize("script", ["text_fit_audit.py", "rtl_audit.py", "button_audit.py"])
def test_nothing_on_the_screens_is_cut_wrong_or_out_of_line(script):
    """The audits, default look, each in a fresh process (the release runs them in
    every look: ``python scripts/<audit>.py``)."""
    import os
    import subprocess

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, str(SCRIPTS / script), "--quick"], cwd=SCRIPTS,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900, env=env)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
