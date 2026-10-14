"""Phase 2: approve with a new accounting person (edited name), receipt image,
shipping, closed mode."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.permissions import ORDERS_SHIP, SHOP_STATE, has_permission  # noqa: E402
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER  # noqa: E402
from app.ui.pages.customers import (  # noqa: E402
    ApproveCustomerDialog,
    name_problem,
    split_name,
)
from app.ui.pages.dashboard import DashboardPage  # noqa: E402
from app.ui.pages.orders import OrderDetailDialog, tracking_fa  # noqa: E402

from .test_ui import _order, _render_page, make_context_with_role, ui_context  # noqa: E402,F401

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


# ---- API client -------------------------------------------------------------
def test_approve_without_code_sends_the_edited_name(fake_api, api):
    customer = fake_api.add_customer(name="🦄 علی")
    result = api.approve_customer(customer["id"], None, first_name="علی", last_name="رضایی")
    assert fake_api.approve_bodies[-1] == {"first_name": "علی", "last_name": "رضایی"}
    assert result["person_code"] == 9000 + customer["id"]


def test_create_person_in_dry_run_is_explained_in_persian(fake_api, api):
    from app.api_client import ApiError

    fake_api.write_enabled = False
    customer = fake_api.add_customer()
    with pytest.raises(ApiError) as caught:
        api.approve_customer(customer["id"], None, last_name="رضایی")
    assert "حالت آزمایشی" in caught.value.message


def test_receipt_image_ship_and_shop_state(fake_api, api):
    order = fake_api.add_order(status="written")
    assert api.receipt_image(order["id"]) is None
    fake_api.receipts[order["id"]] = PNG
    assert api.receipt_image(order["id"]) == PNG
    assert api.ship_order(order["id"])["shipped_at"]
    assert api.shop_state()["closed"] is False
    assert api.sales_action("holiday")["reason"] == "holiday"
    assert api.sales_action("open")["closed"] is False
    assert api.set_shop_closed(True)["closed"] is True


# ---- permissions ------------------------------------------------------------
def test_ship_and_shop_state_permissions():
    assert has_permission(ROLE_OPERATOR, ORDERS_SHIP)
    assert not has_permission(ROLE_VIEWER, ORDERS_SHIP)
    assert has_permission(ROLE_ADMIN, SHOP_STATE)
    assert not has_permission(ROLE_OPERATOR, SHOP_STATE)


# ---- name editing -----------------------------------------------------------
def test_split_name_drops_symbols():
    assert split_name("علی رضایی") == ("علی", "رضایی")
    assert split_name("🦄 Ali ✨") == ("Ali", "")
    assert split_name("محمد علی حسینی") == ("محمد", "علی حسینی")
    assert split_name("😀") == ("", "")


def test_name_problem_rules():
    assert name_problem("علی", "رضایی") == ""
    assert name_problem("", "رضایی") == ""
    assert name_problem("علی", "") != ""
    assert name_problem("علی", "رضایی😀") != ""
    assert name_problem("علی2", "رضایی") != ""
    assert name_problem("علی", "x" * 51) != ""
    assert name_problem("سید‌علی", "رضایی-نژاد") == ""


def test_approve_dialog_create_mode(ui_context, fake_api, admin_qapp):
    customer = fake_api.add_customer(name="🦄 زهرا محمدی")
    dialog = ApproveCustomerDialog(ui_context, customer, None)
    _render_page(admin_qapp, dialog, load=False)          # runs the mobile match (none)
    assert dialog.creating                                  # no match -> create mode
    assert dialog.first_name_input.text() == "زهرا"
    assert dialog.last_name_input.text() == "محمدی"
    dialog.last_name_input.setText("محمدی😀")
    dialog._submit()
    assert dialog.error_label.isVisibleTo(dialog) and dialog.result() == 0
    dialog.last_name_input.setText("  محمدی  ")
    dialog._submit()
    assert dialog.person_code is None
    assert (dialog.first_name, dialog.last_name) == ("زهرا", "محمدی")
    dialog.close()


def test_approve_dialog_link_mode_with_suggestion(ui_context, fake_api, admin_qapp):
    customer = fake_api.add_customer(phone="09121234567")
    fake_api.persons["09121234567"] = {"code": 7001, "masked_name": None}
    dialog = ApproveCustomerDialog(ui_context, customer, None)
    _render_page(admin_qapp, dialog, load=False)
    assert not dialog.creating and dialog.code_input.value() == 7001
    dialog._submit()
    assert dialog.person_code == 7001
    dialog.close()


# ---- orders -------------------------------------------------------------------
def test_tracking_label():
    assert tracking_fa({}) == "—"
    assert tracking_fa({"invoice_state": "partial"}) == "بخشی فاکتور شده"
    assert tracking_fa({"invoice_state": "full"}) == "فاکتور شده"
    assert tracking_fa({"invoice_state": "full", "shipped_at": "2025-01-01T10:00:00+00:00"}) \
        .startswith("ارسال شده")


def test_order_dialog_ship_and_receipt_buttons(ui_context, admin_qapp):
    operator = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = OrderDetailDialog(operator, {**_order(status="written"), "has_receipt": True}, None)
    assert dialog.ship_button.isEnabled() and dialog.receipt_button.isEnabled()
    dialog.close()
    unpaid = OrderDetailDialog(operator, _order(status="awaiting_payment"), None)
    assert not unpaid.ship_button.isEnabled() and not unpaid.receipt_button.isEnabled()
    unpaid.close()
    viewer = make_context_with_role(ui_context, ROLE_VIEWER)
    shipped = OrderDetailDialog(viewer, _order(status="written"), None)
    assert not shipped.ship_button.isEnabled()
    shipped.close()


def test_order_dialog_shows_the_receipt_image(ui_context, fake_api, admin_qapp, monkeypatch):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    order = fake_api.add_order(status="receipt_uploaded", has_receipt=True)
    fake_api.receipts[order["id"]] = bytes(data)

    shown = []
    monkeypatch.setattr("app.ui.pages.orders.ReceiptImageDialog.exec",
                        lambda self: shown.append(self) or 0)
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    dialog = OrderDetailDialog(context, order, None)
    dialog._show_receipt()
    _render_page(admin_qapp, dialog, load=False)
    assert len(shown) == 1
    dialog.close()


# ---- closed mode ------------------------------------------------------------
def test_dashboard_shop_toggle(ui_context, fake_api, admin_qapp, monkeypatch):
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = DashboardPage(context)
    _render_page(admin_qapp, page)
    assert page.shop_toggle.isVisibleTo(page) and page._shop_closed is False
    page._toggle_shop()
    _render_page(admin_qapp, page, load=False)
    assert fake_api.shop_closed is True and page._shop_closed is True
    assert "بسته" in page.shop_state_label.text()
    page.close()


def test_dashboard_hides_toggle_without_permission(ui_context, fake_api, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    page = DashboardPage(context)
    _render_page(admin_qapp, page)
    assert not any(b.isVisibleTo(page) for b in page.sales_buttons.values())
    page.close()


def test_dashboard_sales_buttons(ui_context, fake_api, admin_qapp, monkeypatch):
    """v2.5.0: «تعطیلی امروز» / «بستن فروش» / «باز کردن فروش» go to the server."""
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = DashboardPage(context)
    _render_page(admin_qapp, page)
    assert not page.sales_buttons["open"].isVisibleTo(page)        # already open
    assert page.sales_buttons["holiday"].isVisibleTo(page)
    page._sales_action("holiday")
    _render_page(admin_qapp, page, load=False)
    assert fake_api.sales_actions == ["holiday"] and page._shop_closed is True
    assert "تعطیلی امروز" in page.shop_state_detail.text()
    # only phones are closed: the label says accessories stay orderable
    assert "گوشی" in page.shop_state_label.text() and "لوازم جانبی" in page.shop_state_label.text()
    assert page.sales_buttons["open"].isVisibleTo(page)
    page._sales_action("open")
    _render_page(admin_qapp, page, load=False)
    assert fake_api.sales_actions == ["holiday", "open"] and page._shop_closed is False
    page.close()
