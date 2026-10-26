"""v2.6.0 in ShopAdmin: real version, order dialog (receipt text, person name +
code), no Approve/Reject for decided customers, setup warnings (payment card,
product groups), ACCOUNTING_STATUS_CODE setting, «گروه‌های کالا» and
«درخواست کالا» pages, item request notifications."""
from __future__ import annotations

import re
from pathlib import Path

from app.paths import APP_VERSION
from app.statuses import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_VIEWER

from .test_ui import _pump, make_context_with_role, ui_context  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


# ---- 1: the real version ----------------------------------------------------------------------
def test_app_version_matches_the_installer_and_the_server():
    iss = (ROOT / "installer" / "ShopAdmin.iss").read_text(encoding="utf-8")
    installer = re.search(r'#define MyAppVersion "([^"]+)"', iss).group(1)
    server = re.search(r'^VERSION = "([^"]+)"',
                       (ROOT.parent / "shopapi" / "app" / "control.py").read_text(encoding="utf-8"),
                       re.M).group(1)
    assert APP_VERSION == installer == server == "2.9.4"


def test_sidebar_shows_the_real_version(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(ui_context)
    from app.persian import to_persian_digits

    assert window.version_label.text() == f"نسخهٔ {to_persian_digits('2.9.4')}"


# ---- 2 + 3: order dialog ------------------------------------------------------------------------
def test_receipt_text():
    from app.ui.pages.orders import receipt_ref_text

    assert receipt_ref_text({"has_receipt": True}, "") == "شمارهٔ پیگیری وارد نشده"
    assert receipt_ref_text({"has_receipt": False}, "") == "رسیدی نیامده است"
    assert receipt_ref_text({"has_receipt": True}, "123") == "۱۲۳"


def test_customer_label_uses_the_accounting_name_and_code():
    from app.ui.pages.orders import customer_label

    assert customer_label({"user_id": 4, "user_name": "Ali", "user_person_code": 7001,
                           "person_name": "علی آزمایشی"}) == "علی آزمایشی (کد شخص ۷۰۰۱)"
    assert customer_label({"user_id": 4, "user_name": "Ali", "user_person_code": 7001}) == \
        "Ali (کد شخص ۷۰۰۱)"
    assert customer_label({"user_id": 4, "user_name": "Ali"}) == "Ali"
    assert customer_label({"user_id": 4}) == "مشتری #۴"


def test_order_dialog_shows_receipt_and_customer(ui_context, admin_qapp):
    from app.ui.pages.orders import OrderDetailDialog
    from PySide6.QtWidgets import QLabel

    order = {"id": 9, "status": "receipt_uploaded", "total": 1000, "price_level": 1,
             "created_at": "2026-10-14T10:00:00+00:00", "items": [], "has_receipt": True,
             "user_id": 4, "user_name": "Ali", "user_person_code": 7001,
             "person_name": "علی آزمایشی"}
    dialog = OrderDetailDialog(ui_context, order)
    assert dialog.receipt_ref_label.text() == "شمارهٔ پیگیری وارد نشده"
    texts = [w.text() for w in dialog.findChildren(QLabel)]
    assert "علی آزمایشی (کد شخص ۷۰۰۱)" in texts
    assert not any("مشتری #" in t for t in texts)
    assert dialog.receipt_button.isEnabled()


# ---- 4: decided customers have no Approve/Reject ---------------------------------------------
def test_decided_customers_have_no_decision_buttons(ui_context, admin_qapp):
    from app.ui.pages.customers import CustomersPage

    context = make_context_with_role(ui_context, ROLE_ADMIN)
    page = CustomersPage(context)
    for status in ("approved", "rejected"):
        holder = page._actions_for({"id": 1, "name": "x", "phone": "09121234567",
                                    "status": status, "person_code": 7001})
        buttons = holder.findChildren(type(page.refresh_button))
        assert buttons == [], status
    holder = page._actions_for({"id": 2, "name": "y", "phone": "09121234567", "status": "pending"})
    assert len([b for b in holder.findChildren(type(page.refresh_button)) if b.isEnabled()]) == 2


def test_approve_is_ignored_for_a_decided_customer(ui_context, admin_qapp, monkeypatch):
    from app.ui.pages import customers

    page = customers.CustomersPage(make_context_with_role(ui_context, ROLE_ADMIN))
    opened = []
    monkeypatch.setattr(customers, "ApproveCustomerDialog",
                        lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError))
    page._approve({"id": 1, "status": "approved"})
    page._reject({"id": 1, "status": "approved"})
    assert opened == []


# ---- 8: payment card / groups warning on the dashboard -----------------------------------------
def test_setup_problems():
    from app.ui.pages.dashboard import setup_problems

    assert setup_problems({"payment_ready": True, "catalog_ready": True}) == []
    assert setup_problems(None) == []
    problems = setup_problems({"payment_ready": False, "catalog_ready": False})
    assert len(problems) == 2 and "کارت" in problems[0] and "گروه" in problems[1]


def test_dashboard_warns_when_the_card_is_missing(ui_context, admin_qapp, fake_api):
    from app.ui.pages.dashboard import DashboardPage

    fake_api.payment_ready = False
    page = DashboardPage(ui_context)
    page.show()
    page.load()
    _pump(admin_qapp)
    assert page.setup_warning.isVisible() and "کارت" in page.setup_warning.text()
    fake_api.payment_ready = True
    page.load()
    _pump(admin_qapp)
    assert not page.setup_warning.isVisible()


# ---- 9: ACCOUNTING_STATUS_CODE on the server settings page ------------------------------------
def test_status_code_setting_and_validation():
    from app.server_settings import SETTINGS_FA, local_problem, translate_problem

    assert "ACCOUNTING_STATUS_CODE" in SETTINGS_FA
    assert local_problem("ACCOUNTING_STATUS_CODE", "0") is None
    assert local_problem("ACCOUNTING_STATUS_CODE", "12") is None
    for bad in ("", "6808", "-1", "x"):
        assert local_problem("ACCOUNTING_STATUS_CODE", bad), bad
    assert translate_problem("6808 is not a valid status code") == "کد وضعیت ۶۸۰۸ معتبر نیست"
    assert translate_problem("ACCOUNTING_STATUS_CODE is required") == "کد وضعیت الزامی است"
    assert local_problem("BANK_ACCOUNT_TEXT", "") is None


def test_server_page_refuses_6808_before_sending(ui_context, admin_qapp, fake_api):
    from app.ui.pages.server import ServerPage

    fake_api.server_settings["ACCOUNTING_STATUS_CODE"] = "0"
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = ServerPage(context)
    page.load()
    _pump(admin_qapp)
    field = page._inputs["ACCOUNTING_STATUS_CODE"]
    field.setText("6808")
    page._save_settings()
    _pump(admin_qapp)
    assert fake_api.settings_puts == []


# ---- 10: «گروه‌های کالا» ------------------------------------------------------------------------
def test_product_groups_page(ui_context, admin_qapp, fake_api):
    from app.ui.pages.product_groups import ProductGroupsPage

    fake_api.product_groups = [
        {"code": 1, "name": "لوازم جانبی", "show_in_bot": True, "is_phone": False},
        {"code": 3, "name": "گوشی", "show_in_bot": False, "is_phone": False},
    ]
    page = ProductGroupsPage(make_context_with_role(ui_context, ROLE_ADMIN))
    page.load()
    _pump(admin_qapp)
    assert page.tree.topLevelItemCount() == 2 and not page.save_button.isEnabled()
    page._checks[3]["show_in_bot"].setChecked(True)
    page._checks[3]["is_phone"].setChecked(True)
    assert page.save_button.isEnabled()
    page.save()
    _pump(admin_qapp)
    assert fake_api.group_puts[-1]["groups"] == [
        {"code": 1, "show_in_bot": True, "is_phone": False, "price_on_inquiry": False},
        {"code": 3, "show_in_bot": True, "is_phone": True, "price_on_inquiry": False}]
    assert not page.save_button.isEnabled()


def test_product_groups_read_only_for_viewers(ui_context, admin_qapp, fake_api):
    from app.ui.pages.product_groups import ProductGroupsPage

    fake_api.product_groups = [{"code": 1, "name": "x", "show_in_bot": False, "is_phone": False}]
    page = ProductGroupsPage(make_context_with_role(ui_context, ROLE_VIEWER))
    page.load()
    _pump(admin_qapp)
    assert not page._checks[1]["show_in_bot"].isEnabled() and page.save_button.isHidden()
    assert "هیچ گروهی" in page.warning.text()


# ---- 12: «درخواست کالا» -------------------------------------------------------------------------
def test_item_requests_page(ui_context, admin_qapp, fake_api):
    from app.ui.pages.item_requests import ItemRequestsPage

    fake_api.item_requests = [
        {"id": 2, "user_id": 1, "kala_code": None, "product_name": "", "text": "نوکیا ۳۳۱۰",
         "status": "new", "created_at": "2026-10-14T10:00:00+00:00", "customer_name": "علی",
         "person_code": 7001},
        {"id": 1, "user_id": 1, "kala_code": 102, "product_name": "قاب", "text": "",
         "status": "done", "created_at": "2026-10-13T10:00:00+00:00", "customer_name": "علی",
         "person_code": 7001},
    ]
    page = ItemRequestsPage(ui_context)
    page.load()
    _pump(admin_qapp)
    assert page.table.rowCount() == 1                      # open only
    page.set_filter("all")
    assert page.table.rowCount() == 2
    assert ItemRequestsPage.product_text(fake_api.item_requests[1]) == "قاب (کد ۱۰۲)"
    page._set_status(fake_api.item_requests[0], "done")
    _pump(admin_qapp)
    assert fake_api.item_requests[0]["status"] == "done"


def test_item_request_notification_and_navigation(ui_context, admin_qapp):
    from app.notifications import ATTENTION_KINDS, KIND_ITEM_REQUEST, notice_for
    from app.ui.main_window import BADGE_KINDS, MainWindow

    notice = notice_for({"kind": "item_request", "ref_id": 5})
    assert notice is not None and notice.target == ("item_requests", "open")
    assert KIND_ITEM_REQUEST in ATTENTION_KINDS and BADGE_KINDS["item_requests"] == ("item_request",)
    window = MainWindow(ui_context)
    assert "item_requests" in window._nav_buttons and "product_groups" in window._nav_buttons
    assert notice_for({"kind": "product_groups_changed"}) is None
