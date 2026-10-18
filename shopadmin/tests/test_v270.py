"""v2.7.0 in ShopAdmin: two roles + per-user ticks from the server, hidden menu items,
sales users land on the orders, «ارسال شد» with an optional courier, staff cancel with
confirmation, the Phone Bridge look (light / dark, Vazirmatn), no cut labels, page help
lines and plain-Persian errors."""
from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402

from app import permissions as perms  # noqa: E402
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN, role_fa  # noqa: E402
from app.ui.pages.orders import OrderDetailDialog, ShipDialog  # noqa: E402

from .test_ui import _order, _pump, make_context_with_role, ui_context  # noqa: E402,F401


# ---- the permission model --------------------------------------------------------------------
def test_two_roles_with_persian_names():
    assert perms.ALL_ROLES == (ROLE_SUPER_ADMIN, ROLE_OPERATOR)
    assert perms.DEFAULT_ROLE == ROLE_OPERATOR
    assert role_fa(ROLE_SUPER_ADMIN) == "مدیر" and role_fa(ROLE_OPERATOR) == "کاربر فروش"
    sales = perms.role_permissions(ROLE_OPERATOR)
    for allowed in (perms.ORDERS_VIEW, perms.ORDERS_APPROVE_PAYMENT, perms.ORDERS_SHIP,
                    perms.ORDERS_CANCEL, perms.ITEM_REQUESTS, perms.CUSTOMERS_VIEW):
        assert allowed in sales
    for admin_only in (perms.DASHBOARD_VIEW, perms.PRICELIST_VIEW, perms.CATALOG_VIEW,
                       perms.SHOP_STATE, perms.SETTINGS_VIEW, perms.USERS_VIEW,
                       perms.SERVER_MANAGE, perms.REPORTS_VIEW, perms.PROXIES_MANAGE,
                       perms.CUSTOMERS_APPROVE, perms.PRODUCTS_VIEW):
        assert admin_only not in sales
    assert perms.role_permissions(ROLE_SUPER_ADMIN) >= sales


def test_server_permissions_drive_the_screens():
    granted = perms.client_permissions(["orders.view", "shop.state"])
    assert perms.ORDERS_VIEW in granted and perms.SHOP_STATE in granted
    assert perms.ORDERS_SHIP not in granted
    assert perms.SETTINGS_CHANGE_OWN_PASSWORD in granted            # always
    assert set(perms.SERVER_PERMISSION_FA) >= perms.SALES_SERVER_PERMISSIONS


def test_principal_from_the_server_list():
    from app.auth import principal_from_staff

    row = {"id": 3, "username": "mina", "full_name": "مینا", "role": "operator",
           "permissions": ["orders.view", "requests.handle"]}
    principal = principal_from_staff(row)
    assert principal.can(perms.ITEM_REQUESTS) and not principal.can(perms.ORDERS_SHIP)
    older = principal_from_staff({**row, "permissions": None})
    assert older.permissions is None and older.can(perms.ORDERS_SHIP)      # role table


# ---- menu ----------------------------------------------------------------------------------------
def test_sales_menu_and_landing(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert set(window._nav_buttons) == {"orders", "item_requests", "customers"}
    assert set(window._pages) == {"orders", "item_requests", "customers"}
    assert window._current_key == "orders" and window.home_key() == "orders"
    assert window.password_button.text() == "گذرواژهٔ من"
    window.close()


def test_a_tick_shows_one_more_page(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    context.principal = replace(context.principal, permissions=perms.client_permissions(
        list(perms.SALES_SERVER_PERMISSIONS - {"customers.view"}) + ["pricelist.manage"]))
    window = MainWindow(context)
    assert "pricelist" in window._nav_buttons and "customers" not in window._nav_buttons
    window.close()


def test_manager_sees_everything_and_lands_on_the_dashboard(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert {"dashboard", "pricelist", "settings", "users", "server"} <= set(window._nav_buttons)
    assert window._current_key == "dashboard"
    window.close()


# ---- shipping ------------------------------------------------------------------------------------
def test_ship_dialog_courier_is_optional(admin_qapp):
    dialog = ShipDialog(None, "۱۲")
    dialog._accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert (dialog.courier_name, dialog.courier_phone) == ("", "")
    dialog = ShipDialog(None, "۱۲")
    dialog.name_input.setText("  علی   پیک ")
    dialog.phone_input.setText("۰۹۱۲ ۳۴۵ ۶۷۸۹")
    dialog._accept()
    assert (dialog.courier_name, dialog.courier_phone) == ("علی پیک", "09123456789")
    bad = ShipDialog(None, "۱۲")
    bad.phone_input.setText("۱۲")
    bad._accept()
    assert bad.result() != bad.DialogCode.Accepted and "رقم" in bad.error_label.text()


def test_ship_sends_the_courier(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import orders

    order = fake_api.add_order(id=7, status="approved")

    class Filled:
        DialogCode = ShipDialog.DialogCode

        def __init__(self, *_a):
            self.courier_name, self.courier_phone = "علی پیک", "09123456789"

        def exec(self):
            return ShipDialog.DialogCode.Accepted

    monkeypatch.setattr(orders, "ShipDialog", Filled)
    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_OPERATOR), order, None)
    dialog._ship()
    _pump(admin_qapp)
    assert fake_api.ship_bodies[-1] == {"courier_name": "علی پیک", "courier_phone": "09123456789"}
    assert dialog.changed


def test_cancel_asks_first(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets

    order = fake_api.add_order(id=8, status="awaiting_payment")
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    answers = [False, True]
    asked = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: asked.append(a[2]) or answers.pop(0))
    dialog = OrderDetailDialog(context, order, None)
    assert dialog.cancel_button.isEnabled()
    dialog._cancel_order()                                   # «خیر»
    _pump(admin_qapp)
    assert order["status"] == "awaiting_payment"
    dialog._cancel_order()                                   # «بله»
    _pump(admin_qapp)
    assert order["status"] == "cancelled" and "برگشت ندارد" in asked[0]
    paid = OrderDetailDialog(context, {**_order(), "status": "approved"}, None)
    assert not paid.cancel_button.isEnabled()


def test_approve_asks_first(ui_context, admin_qapp, monkeypatch):
    from app.ui import widgets

    called = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    monkeypatch.setattr(context.api, "approve_payment", lambda *_a: called.append(1))
    dialog = OrderDetailDialog(context, _order(), None)
    dialog._approve()
    _pump(admin_qapp)
    assert called == [] and dialog.approve_button.text() == "تأیید رسید"


def test_sales_user_sees_no_technical_rows(ui_context, admin_qapp):
    from PySide6.QtWidgets import QLabel

    sales = OrderDetailDialog(make_context_with_role(ui_context, ROLE_OPERATOR), _order(), None)
    texts = " ".join(w.text() for w in sales.findChildren(QLabel))
    assert "پایگاه‌دادهٔ حسابداری" not in texts and "سطح قیمت" not in texts
    manager = OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), _order(),
                                None)
    assert "پایگاه‌دادهٔ حسابداری" in " ".join(w.text() for w in manager.findChildren(QLabel))


# ---- look -----------------------------------------------------------------------------------------
def test_phone_bridge_palette_light_and_dark():
    from app.ui import theme

    assert theme.ACCENT == "#2F7CF6" and theme.SIDEBAR_BG == "#16325C"
    light = theme.stylesheet("X")
    try:
        assert theme.set_mode("dark") == "dark" and theme.SURFACE == "#1B212B"
        dark = theme.stylesheet("X")
        assert dark != light and "#11151C" in dark
    finally:
        theme.set_mode("light")
    assert "qlineargradient" in theme.sidebar_gradient()


def test_vazirmatn_is_bundled_and_found():
    from app.paths import fonts_dir

    names = {p.name for p in fonts_dir().glob("*.ttf")}
    assert {"Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"} <= names


def test_labels_are_never_cut(ui_context, admin_qapp):
    """Bold-in-one-state labels were measured with the normal font and clipped:
    the menu, the order tabs and buttons keep one weight in every state."""
    from app.ui import theme
    from app.ui.main_window import MainWindow

    sheet = theme.stylesheet("X")
    for rule in ("QPushButton#NavButton:checked", "QPushButton#Tab:checked",
                 'QPushButton#NavButton[hasBadge="true"]'):
        body = sheet.split(rule, 1)[1].split("}", 1)[0]
        assert "font-weight" not in body, rule
    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    window.resize(1366, 800)
    window.show()
    window.navigate("orders")
    _pump(admin_qapp)
    page = window.current_page()
    for key, tab in page._tab_buttons.items():
        tab.setChecked(True)
        bold = QFont(tab.font())
        bold.setBold(True)
        needed = QFontMetrics(bold).horizontalAdvance(tab.text())
        assert tab.sizeHint().width() >= needed, key
    table = page.table
    header = table.horizontalHeader()
    bold = QFont(header.font())
    bold.setBold(True)
    for column in range(table.columnCount() - 1):
        text = table.horizontalHeaderItem(column).text()
        assert table.columnWidth(column) >= QFontMetrics(bold).horizontalAdvance(text), text
    window.close()


def test_every_page_has_a_help_line(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    for key, page in window._pages.items():
        assert page.help_text and page.help_label is not None, key
    window.close()


def test_errors_are_plain_and_say_what_to_do():
    from app.api_client import (
        MSG_CONNECTION_FAILED,
        MSG_FORBIDDEN,
        MSG_SERVER_ERROR,
        translate_detail,
    )

    assert "مدیر" in MSG_FORBIDDEN and "سرور" not in MSG_CONNECTION_FAILED
    assert "دوباره" in MSG_SERVER_ERROR
    assert "رقم" in translate_detail("Invalid courier phone", 422)
    assert "لغو نیست" in translate_detail("Order in status approved; cannot be cancelled", 409)


def test_users_form_ticks_follow_the_role(ui_context, admin_qapp, fake_api):
    from app.ui.pages.users import UserFormDialog

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    form = UserFormDialog(context, None)
    assert form.role_combo.currentData() == ROLE_OPERATOR                # default role
    assert form.permission_checks["orders.view"].isChecked()
    assert not form.permission_checks["pricelist.manage"].isChecked()
    form.permission_checks["shop.state"].setChecked(True)
    form.permission_checks["orders.cancel"].setChecked(False)
    assert form.permission_changes() == (["shop.state"], ["orders.cancel"])
    form.username_input.setText("mina")
    form.full_name_input.setText("مینا")
    form.password_input.setText("Secret1234")
    form.confirm_input.setText("Secret1234")
    form._submit()
    _pump(admin_qapp)
    row = fake_api.find_staff("mina")
    assert row["extra_permissions"] == ["shop.state"]
    assert row["removed_permissions"] == ["orders.cancel"]
    form.role_combo.setCurrentIndex(form.role_combo.findData(ROLE_SUPER_ADMIN))
    assert all(c.isChecked() for c in form.permission_checks.values())
