"""v2.17.0: per-user ticks on every screen, «قواعد فروشگاه», write later, closing a
request with a message, staff notifications on the dashboard."""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app import permissions as perms
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN, sazeh_stage_fa

from .test_ui import make_context_with_role, ui_context  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _pump(app, until=None, rounds=200):
    import time

    for _ in range(rounds):
        app.processEvents()
        if until is not None and until():
            break
        time.sleep(0.01)
    app.processEvents()


def _server_staff():
    """shopapi's own table, read straight from its file."""
    spec = importlib.util.spec_from_file_location(
        "shopapi_staff_for_test", ROOT.parent / "shopapi" / "app" / "staff.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _with_ticks(context, ticks):
    context.principal = replace(context.principal,
                                permissions=perms.client_permissions(sorted(perms.with_implied(ticks))))
    return context


# ---- #15 ------------------------------------------------------------------------------------------
def test_the_table_is_the_servers_table():
    server = _server_staff()
    assert list(perms.ALL_SECTIONS) == list(server.ALL_SECTIONS)
    assert perms.SALES_SERVER_PERMISSIONS == server.PERMISSIONS[server.ROLE_SALES]
    assert perms.REQUIRES == server.REQUIRES


def test_every_tick_opens_something_on_the_screens():
    for name in perms.SECTION_PERMISSIONS:
        assert perms.SERVER_TO_CLIENT.get(name), name


def test_every_page_has_its_own_tick():
    from app.ui.main_window import NAV_ITEMS

    keys = [item[3] for item in NAV_ITEMS]
    assert len(keys) == len(set(keys)), "two pages on one tick"
    for key, _text, _icon, permission in NAV_ITEMS:
        assert any(permission in unlocked for unlocked in perms.SERVER_TO_CLIENT.values()), key


def test_only_the_own_password_needs_no_tick():
    assert perms.client_permissions([]) == frozenset({perms.SETTINGS_CHANGE_OWN_PASSWORD})


def test_a_new_user_has_no_admin_or_settings_screen(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert set(window._nav_buttons) == {"dashboard", "orders", "item_requests", "customers",
                                        "archive", "reports"}
    window.close()


def test_no_ticks_no_pages_but_the_password_stays(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR), [])
    window = MainWindow(context)
    assert not window._nav_buttons
    assert not window.notify_button.isVisibleTo(window)
    assert context.can(perms.SETTINGS_CHANGE_OWN_PASSWORD)
    window.close()


def test_the_manager_sees_every_page(ui_context, admin_qapp):
    from app.ui.main_window import NAV_ITEMS, MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert set(window._nav_buttons) == {item[0] for item in NAV_ITEMS}
    window.close()


@pytest.mark.parametrize("tick,page", [("site.view", "site"), ("health.view", "health"),
                                       ("status_codes.view", "shop_rules"),
                                       ("work_hours.view", "shop_rules"),
                                       ("auto_invoice.view", "shop_rules"),
                                       ("app_settings.view", "settings")])
def test_one_tick_opens_its_page(ui_context, admin_qapp, tick, page):
    from app.ui.main_window import MainWindow

    context = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR), [tick])
    window = MainWindow(context)
    assert set(window._nav_buttons) == {page}
    window.close()


def test_user_form_has_a_tick_for_everything(ui_context, admin_qapp):
    from app.ui.pages.users import UserFormDialog

    form = UserFormDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), None)
    assert set(form.permission_checks) == set(perms.SECTION_PERMISSIONS)
    # a new sales user: the daily work ticked, nothing administrative
    assert form.permission_checks["orders.view"].isChecked()
    assert not form.permission_checks["app_settings.view"].isChecked()
    assert not form.permission_checks["server.view"].isChecked()
    assert not form.permission_checks["acctwrite.edit"].isChecked()
    assert form.permission_changes() == ([], [])
    # an action brings its page; taking the page takes the actions
    form.permission_checks["orders.view"].setChecked(False)
    for name in ("receipts.edit", "payinfo.edit", "ship.edit", "cancel.edit"):
        assert not form.permission_checks[name].isChecked(), name
    form.permission_checks["acctwrite.edit"].setChecked(True)
    assert form.permission_checks["orders.view"].isChecked()
    # «مدیر» always has everything: nothing to untick
    form.role_combo.setCurrentIndex(form.role_combo.findData(ROLE_SUPER_ADMIN))
    assert all(c.isChecked() and not c.isEnabled() for c in form.permission_checks.values())


def test_buttons_follow_their_own_tick(ui_context, admin_qapp):
    from app.ui.pages.orders import OrderDetailDialog

    order = {"id": 7, "status": "receipt_uploaded", "total": 10, "items": [],
             "created_at": "2026-11-01T10:00:00+00:00"}
    context = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR),
                          ["orders.view", "ship.edit"])
    dialog = OrderDetailDialog(context, order)
    assert not dialog.approve_button.isVisibleTo(dialog)
    assert not dialog.reject_button.isVisibleTo(dialog)
    assert not dialog.cancel_button.isVisibleTo(dialog)
    assert dialog.ship_button.isVisibleTo(dialog)
    dialog.close()


def test_group_names_arriving_after_the_products_are_shown(ui_context, admin_qapp, fake_api):
    """The two answers race (a build failed on it): the slower one must not leave «گروه ۱»."""
    from app.ui.pages.products import ProductsPage

    fake_api.groups = [{"code": 1, "name": "لوازم خانگی"}]
    page = ProductsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._on_loaded({"total": 1, "page": 1, "page_size": 20, "items": [
        {"code": 101, "name": "یخچال", "group": 1, "unit_price": 1.0, "available_qty": 1.0,
         "image": None}]})
    assert "لوازم خانگی" not in page.table.item(0, 2).text()
    page._load_groups()
    _pump(admin_qapp, until=lambda: "لوازم خانگی" in page.table.item(0, 2).text())
    assert "لوازم خانگی" in page.table.item(0, 2).text()


# ---- #1 and #2 ---------------------------------------------------------------------------------
def test_6808_is_accepted_and_zero_refused():
    from app.server_settings import local_problem

    assert local_problem("ACCOUNTING_STATUS_CODE", "6808") is None
    assert local_problem("ACCOUNTING_STATUS_CODE", "0")
    assert local_problem("ACCOUNTING_HANDOVER_STATUS_CODE", "") is None
    assert local_problem("ACCOUNTING_HANDOVER_STATUS_CODE", "6914") is None
    assert local_problem("ACCOUNTING_HANDOVER_STATUS_CODE", "x")


def _approve_dialog(context, order, monkeypatch, confirm=True):
    from app.ui import widgets
    from app.ui.pages.orders import OrderDetailDialog

    asked = {}

    def fake_confirm(parent, title, message, **kw):
        asked.update(kw, message=message)
        return confirm

    monkeypatch.setattr(widgets, "confirm", fake_confirm)
    shown = []
    monkeypatch.setattr(widgets, "info",
                        lambda parent, title, message, **kw: shown.append((title, message, kw)))
    return OrderDetailDialog(context, order), asked, shown


def test_receipt_without_a_code_warns_before_and_after(ui_context, admin_qapp, fake_api,
                                                       monkeypatch):
    fake_api.status_codes["configured"] = False
    fake_api.orders.append({"id": 77, "status": "receipt_uploaded", "total": 10, "items": [],
                            "created_at": "2026-11-01T10:00:00+00:00"})
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.system_info = replace(context.system_info, accounting_write_enabled=True,
                                  status_code_configured=False, reachable=True)
    order = fake_api.orders[-1]
    dialog, asked, shown = _approve_dialog(context, dict(order), monkeypatch)
    dialog._approve()
    _pump(admin_qapp, until=lambda: shown)
    assert asked["kind"] == "warning" and "ثبت در حسابداری" in asked["detail"]
    assert shown and "ثبت نشد" in shown[0][0] and shown[0][2]["kind"] == "warning"
    assert fake_api.orders[-1]["status"] == "approved"


def test_waiting_order_shows_the_write_button(ui_context, admin_qapp, fake_api):
    from app.ui.pages.orders import OrderDetailDialog

    order = {"id": 78, "status": "approved", "total": 10, "items": [], "accounting_pending": True,
             "created_at": "2026-11-01T10:00:00+00:00", "owned": True, "owned_by_me": True}
    fake_api.orders.append(order)
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    dialog = OrderDetailDialog(context, dict(order))
    assert dialog.write_button.isVisibleTo(dialog)
    dialog._write_accounting()
    _pump(admin_qapp, until=lambda: dialog.changed)
    assert fake_api.orders[-1]["status"] == "written"
    # needs its own tick
    sales = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR), ["orders.view"])
    dialog = OrderDetailDialog(sales, dict(order))
    assert not dialog.write_button.isVisibleTo(dialog)


def test_a_normal_order_has_no_write_button(ui_context, admin_qapp):
    from app.ui.pages.orders import OrderDetailDialog

    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN),
                               {"id": 79, "status": "written", "total": 10, "items": [],
                                "created_at": "2026-11-01T10:00:00+00:00"})
    assert not dialog.write_button.isVisibleTo(dialog)


# ---- #7 --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("order,text", [
    ({"sazeh_stage": "approved"}, "تأیید"),
    ({"sazeh_stage": "handover"}, "تحویل به فروش"),
    ({"sazeh_stage": "invoiced"}, "فاکتور شد"),
    ({"sazeh_stage": "partial"}, "بخشی فاکتور شد"),
    ({"accounting_pending": True}, "منتظر «ثبت در حسابداری»"),
    ({}, "—"),
])
def test_stage_text(order, text):
    assert sazeh_stage_fa(order) == text


def test_orders_table_shows_the_stage(ui_context, admin_qapp, fake_api):
    from app.ui.pages.orders import HEADERS, OrdersPage

    assert HEADERS[-1] == "مرحله در «سازه حساب»"
    fake_api.orders.append({"id": 80, "status": "written", "total": 10, "items": [],
                            "sazeh_stage": "handover", "created_at": "2026-11-01T10:00:00+00:00"})
    page = OrdersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._on_loaded([fake_api.orders[-1]])
    assert page.table.item(0, len(HEADERS) - 1).text() == "تحویل به فروش"


def _rules(ui_context, ticks=None):
    from app.ui.pages.shop_rules import ShopRulesPage

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    if ticks is not None:
        context = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR), ticks)
    page = ShopRulesPage(context)
    return page


def test_rules_page_saves_both_codes(ui_context, admin_qapp, fake_api):
    fake_api.status_codes.update(order_status=None, handover_status=None, configured=False)
    page = _rules(ui_context)
    page.load()
    _pump(admin_qapp, until=lambda: page.status_message.isVisibleTo(page))
    assert "تنظیم نشده" in page.status_message.text()
    page.order_input.setText("۶۸۰۸")
    page.handover_input.setText("6914")
    page._save_codes()
    _pump(admin_qapp, until=lambda: fake_api.status_codes["configured"])
    assert fake_api.status_codes["order_status"] == 6808
    assert fake_api.status_codes["handover_status"] == 6914


@pytest.mark.parametrize("order,handover", [("0", ""), ("", ""), ("abc", ""), ("6808", "6808")])
def test_rules_page_refuses_before_sending(ui_context, admin_qapp, fake_api, order, handover):
    before = dict(fake_api.status_codes)
    page = _rules(ui_context)
    page.order_input.setText(order)
    page.handover_input.setText(handover)
    page._save_codes()
    _pump(admin_qapp, rounds=20)
    assert fake_api.status_codes == before and page.status_message.isVisibleTo(page)


def test_rules_page_shows_only_what_is_ticked(ui_context, admin_qapp):
    page = _rules(ui_context, ["status_codes.view"])
    assert page.status_panel is not None and page.hours_panel is None
    assert page.invoice_panel is None
    assert not page.order_input.isEnabled()
    assert not page.status_save_button.isVisibleTo(page)
    page = _rules(ui_context, ["work_hours.edit"])
    assert page.status_panel is None and page.hours_panel is not None
    assert page.start_input.isEnabled()


def test_server_form_no_longer_holds_the_codes(ui_context, admin_qapp, fake_api):
    from app.ui.pages.server import ServerPage

    fake_api.server_settings["ACCOUNTING_STATUS_CODE"] = "6808"
    page = ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._show_settings({"ACCOUNTING_STATUS_CODE": {"secret": False, "value": "6808"},
                         "RECEIPT_DEADLINE_MINUTES": {"secret": False, "value": "30"}})
    assert "ACCOUNTING_STATUS_CODE" not in page._inputs
    assert "RECEIPT_DEADLINE_MINUTES" in page._inputs


def test_banner_opens_the_rules_page(ui_context, admin_qapp, fake_api):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    window._banner_action("status_code")
    assert window._current_key == "shop_rules"
    window.close()


# ---- #8 --------------------------------------------------------------------------------------------
def test_auto_invoice_is_off_and_disabled(ui_context, admin_qapp):
    page = _rules(ui_context)
    assert not page.auto_invoice_check.isChecked() and not page.auto_invoice_check.isEnabled()
    assert page.auto_invoice_check.toolTip() == "در نسخه‌های بعد"


# ---- #3 --------------------------------------------------------------------------------------------
def test_close_dialog_offers_ready_texts_and_no_skip(admin_qapp):
    from app.ui.pages.item_requests import READY_MESSAGES, CloseRequestDialog

    assert [m[0] for m in READY_MESSAGES] == ["موجود شد", "فعلاً تأمین نمی‌شود", "مدل مشابه داریم",
                                              "متن دلخواه"]
    dialog = CloseRequestDialog(None, {"product_name": "آیفون ۱۷"})
    assert "آیفون ۱۷" in dialog.editor.toPlainText() and "موجود شد" in dialog.editor.toPlainText()
    dialog.choices[1].setChecked(True)
    assert "تأمین نمی‌شود" in dialog.editor.toPlainText()
    dialog.choices[3].setChecked(True)
    assert dialog.editor.toPlainText() == ""
    dialog._send()
    assert dialog.text == "" and dialog.error_label.isVisibleTo(dialog)    # nothing to send
    dialog.editor.setPlainText("متن خودم")
    dialog._send()
    assert dialog.text == "متن خودم"


REQUEST = {"id": 501, "user_id": 1, "product_name": "آیفون ۱۷", "text": "", "status": "new",
           "kind": "unavailable", "created_at": "2026-11-01T10:00:00+00:00"}


def _request_dialog(ui_context, fake_api):
    from app.ui.pages.item_requests import ItemRequestDialog

    return ItemRequestDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN),
                             dict(fake_api.item_requests[0]))


def test_done_without_a_message_asks_first(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests as mod

    fake_api.item_requests.append(REQUEST)
    dialog = _request_dialog(ui_context, fake_api)
    _pump(admin_qapp, rounds=30)
    dialog.messages = []
    opened = []

    class Refuse:
        def __init__(self, *a):
            opened.append(a)

        def exec(self):
            return mod.QDialog.DialogCode.Rejected

    monkeypatch.setattr(mod, "CloseRequestDialog", Refuse)
    sent = []
    monkeypatch.setattr(dialog.context.api, "set_item_request_status",
                        lambda *a, **k: sent.append(a) or {})
    dialog.set_status("done")
    _pump(admin_qapp, rounds=10)
    assert opened and sent == []          # asked; going back changes nothing


def test_chosen_text_is_sent_and_the_request_closed(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests as mod

    fake_api.item_requests.append(dict(REQUEST))
    dialog = _request_dialog(ui_context, fake_api)
    _pump(admin_qapp, rounds=30)
    dialog.messages = []

    def choose(self):
        self.text = "موجود شد"
        return mod.QDialog.DialogCode.Accepted

    monkeypatch.setattr(mod.CloseRequestDialog, "exec", choose)
    calls = []
    api = dialog.context.api
    send, close = api.send_item_request_message, api.set_item_request_status
    monkeypatch.setattr(api, "send_item_request_message",
                        lambda *a: (calls.append(("send", a[1])), send(*a))[1])
    monkeypatch.setattr(api, "set_item_request_status",
                        lambda *a: (calls.append(("close", a[1])), close(*a))[1])
    dialog.set_status("done")
    _pump(admin_qapp, until=lambda: len(calls) == 2)
    assert calls == [("send", "موجود شد"), ("close", "done")]     # message first
    dialog._poll.stop()


def test_done_after_a_message_does_not_ask(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests as mod

    fake_api.item_requests.append(REQUEST)
    dialog = _request_dialog(ui_context, fake_api)
    _pump(admin_qapp, rounds=30)
    dialog.messages = [{"status": "sent", "text": "x"}]
    monkeypatch.setattr(mod, "CloseRequestDialog",
                        lambda *a: pytest.fail("must not ask"))
    sent = []
    monkeypatch.setattr(dialog.context.api, "set_item_request_status",
                        lambda *a, **k: sent.append(a) or {})
    dialog.set_status("done")
    _pump(admin_qapp, until=lambda: sent)
    assert sent


def test_a_failed_message_does_not_count():
    from app.ui.pages.item_requests import has_sent_message

    assert not has_sent_message([])
    assert not has_sent_message([{"status": "failed"}])
    assert has_sent_message([{"status": "failed"}, {"status": "pending"}])


# ---- #12 and #12b --------------------------------------------------------------------------------
def test_dashboard_alert_panel_follows_the_ticks(ui_context, admin_qapp):
    from app.ui.pages.dashboard import DashboardPage

    none = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR), ["dashboard.view"])
    page = DashboardPage(none)
    assert not page.alert_panel.isVisibleTo(page)
    view = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR),
                       ["dashboard.view", "staff_alerts.view"])
    page = DashboardPage(view)
    assert page.alert_panel.isVisibleTo(page)
    assert not any(b.isVisibleTo(page) for b in page.alert_buttons.values())
    edit = _with_ticks(make_context_with_role(ui_context, ROLE_OPERATOR),
                       ["dashboard.view", "staff_alerts.edit"])
    page = DashboardPage(edit)
    texts = [b.text() for b in page.alert_buttons.values()]
    assert texts == ["روشن کردن اعلان‌ها", "خاموش کردن اعلان‌ها", "تعطیلی امروز"]
    assert all(b.isVisibleTo(page) for b in page.alert_buttons.values())


def test_dashboard_buttons_call_the_server(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets
    from app.ui.pages.dashboard import DashboardPage

    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    page = DashboardPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._alert_action("holiday")
    _pump(admin_qapp, until=lambda: fake_api.alert_actions)
    assert fake_api.alert_actions == ["holiday"]
    _pump(admin_qapp, until=lambda: "تعطیلی" in page.alert_state_label.text())
    assert "تعطیلی امروز" in page.alert_state_label.text()


@pytest.mark.parametrize("state,text", [
    ({"active": True}, "روشن طبق ساعت کار"),
    ({"active": False}, "بیرون از ساعت کار"),
    ({"active": True, "override": "on"}, "دستی روشن"),
    ({"active": False, "override": "off"}, "دستی خاموش"),
    ({"active": False, "override": "holiday"}, "تعطیلی امروز"),
])
def test_alert_state_text(state, text):
    from app.ui.pages.dashboard import alert_state_text

    assert text in alert_state_text(state)


def test_hours_text():
    from app.ui.pages.shop_rules import hours_text

    text = hours_text({"start": "09:00", "end": "21:00", "days": [5, 4]})
    assert "۰۹:۰۰ تا ۲۱:۰۰" in text and "شنبه" in text and "جمعه" in text and "یکشنبه" not in text


def test_work_hours_page_saves(ui_context, admin_qapp, fake_api):
    page = _rules(ui_context)
    page.load()
    _pump(admin_qapp, until=lambda: page.start_input.text())
    assert page.start_input.text() == "09:00" and page.day_checks[5].isChecked()
    assert not page.day_checks[4].isChecked()          # Friday off by default
    page.end_input.setText("۱۸:۳۰")
    page.day_checks[4].setChecked(True)
    page._save_hours()
    _pump(admin_qapp, until=lambda: fake_api.work_hours["end"] == "18:30")
    assert fake_api.work_hours["end"] == "18:30" and 4 in fake_api.work_hours["days"]


def test_claim_button_on_a_free_order_only(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets
    from app.ui.pages.orders import OrderDetailDialog

    errors = []
    monkeypatch.setattr(widgets, "error", lambda *a, **k: errors.append(a))

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    free = {"id": 90, "status": "awaiting_payment", "total": 1, "items": [],
            "created_at": "2026-11-01T10:00:00+00:00"}
    fake_api.orders.append(free)
    dialog = OrderDetailDialog(context, free)
    assert dialog.claim_button.isVisibleTo(dialog)
    dialog._claim()
    _pump(admin_qapp, until=lambda: fake_api.claims or errors)
    assert errors == []
    assert fake_api.claims == [("order", 90)]
    taken = OrderDetailDialog(context, {**free, "owned": True})
    assert not taken.claim_button.isVisibleTo(taken)


def test_user_form_saves_the_mobile(ui_context, admin_qapp, fake_api):
    from app.ui.pages.users import UserFormDialog, link_text

    assert link_text({}) == "موبایل ندارد"
    assert "هنوز وصل نشده" in link_text({"mobile": "09120000001"})
    assert "بله، تلگرام" in link_text({"mobile": "09120000001",
                                       "linked_platforms": ["bale", "telegram"]})
    form = UserFormDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), None)
    form.username_input.setText("mina2")
    form.full_name_input.setText("مینا")
    form.password_input.setText("Secret1234")
    form.confirm_input.setText("Secret1234")
    form.mobile_input.setText("۰۹۱۲۰۰۰۰۰۰۱")
    seen = {}
    real = form.context.api.create_staff
    form.context.api.create_staff = lambda *a, **k: (seen.update(k), real(*a, **k))[1]
    form._submit()
    _pump(admin_qapp, until=lambda: seen)
    assert seen["mobile"] == "09120000001"
