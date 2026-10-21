"""v2.8.3: own activity only, the dashboard (own chart, no horizontal scroll bar),
the payment-info reminder and highlighted rows, the masked card / Sheba fields,
the smaller permission table and «انتقال همهٔ کارهای باز»."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QHeaderView  # noqa: E402

from app import notifications  # noqa: E402
from app import permissions as perms  # noqa: E402
from app.activity import sentence  # noqa: E402
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN  # noqa: E402
from app.ui import theme  # noqa: E402

from .test_ui import make_context_with_role, ui_context  # noqa: E402,F401


# ---- 1: «گزارش فعالیت» -----------------------------------------------------------------------------
def test_activity_has_no_user_filter_for_a_sales_user(ui_context, admin_qapp):
    from app.ui.pages.activity import ActivityPage

    page = ActivityPage(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert page.own_only and not page.user_combo.isVisibleTo(page)
    assert page.query()["staff_id"] is None
    manager = ActivityPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert not manager.own_only and manager.user_combo.isVisibleTo(manager)


def test_moved_work_names_the_previous_owner_for_the_manager():
    entry = {"action": "assign", "actor_name": "مدیر", "to_name": "علی", "from_name": "مینا"}
    assert sentence(entry) == "مدیر کار مینا را به علی ارجاع داد"
    assert sentence({"action": "assign", "is_me": True}) == "شما به همکار ارجاع داد"


# ---- 2 / 4: dashboard ------------------------------------------------------------------------------
def _dashboard_data(orders):
    return {"pending_customers": [], "receipts": orders, "approved": [], "written": [],
            "products": {"total": 0}, "info": None, "shop": None}


def test_dashboard_chart_counts_only_own_work(ui_context, admin_qapp, monkeypatch):
    from datetime import datetime, timezone

    from app.ui.pages import dashboard

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    orders = [{"id": 1, "status": "receipt_uploaded", "created_at": now, "owned_by_me": True},
              {"id": 2, "status": "receipt_uploaded", "created_at": now, "owned_by_me": False}]
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    monkeypatch.setattr(context, "apply_system_info", lambda _info: None)
    page = dashboard.DashboardPage(context)
    seen = []
    monkeypatch.setattr(page.chart, "set_data", lambda data: seen.append(data))
    page._render(_dashboard_data(orders))
    assert sum(count for _label, count in seen[-1]) == 1
    assert not page.card_products.isVisibleTo(page) or context.can(perms.PRODUCTS_VIEW)
    header = page.table.horizontalHeader()
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(4) == QHeaderView.ResizeMode.ResizeToContents
    page.resize(1300, 900)
    page.show()
    for _ in range(5):
        admin_qapp.processEvents()
    assert page.table.viewport().width() > 700
    assert not page.table.horizontalScrollBar().isVisible()
    page.close()


def test_sales_detail_shows_no_colleague_name():
    from app.ui.pages.dashboard import sales_detail_text

    assert "Ahmad" not in sales_detail_text({"reason": "manual_open", "override_by": ""})
    assert "به‌دست شما" in sales_detail_text({"reason": "manual_open", "override_by": "شما"})


# ---- 5: payment-info reminders ---------------------------------------------------------------------
def test_reminder_notice_texts():
    assert notifications.payment_reminder_notice([]) is None
    one = notifications.payment_reminder_notice([7])
    assert "۷" in one.body and one.target == ("orders", "awaiting_payment")
    many = notifications.payment_reminder_notice([1, 2, 3])
    assert "۳ سفارش" in many.body
    assert notifications.PAYMENT_REMINDER_SECONDS == 30


def test_reminder_ignores_the_users_switches(admin_qapp, tmp_path, monkeypatch):
    from app.store import Store

    store = Store(tmp_path / "n.db")
    store.set_setting("notify_sound", False)
    store.set_setting("notify_desktop", False)
    tray = notifications.TrayNotifier(store)
    sounds = []
    monkeypatch.setattr(notifications, "play_notification_sound", lambda: sounds.append(1))
    shown = []
    if tray.tray is not None:
        monkeypatch.setattr(tray.tray, "showMessage", lambda *a: shown.append(a))
    assert tray.remind_payment_info([5]) is not None
    assert sounds == [1]
    if tray.tray is not None:
        assert shown and shown[0][3] <= 6000        # a small, closable balloon
    tray.hide()
    store.close()


def test_reminder_emits_only_for_listed_orders(admin_qapp):
    reminder = notifications.PaymentInfoReminder("http://x.test", "t")
    reminded, changed = [], []
    reminder.remind.connect(reminded.append)
    reminder.due_changed.connect(changed.append)
    reminder._on_result([{"id": 9}, {"id": 4}])
    reminder._on_result([{"id": 4}, {"id": 9}])
    reminder._on_result([])
    assert reminded == [[4, 9], [4, 9]] and changed == [[4, 9], []]
    reminder.client.close()


def test_rows_waiting_for_payment_details_are_highlighted(ui_context, admin_qapp):
    from app.ui.pages.orders import OrdersPage, needs_payment_info

    page = OrdersPage(make_context_with_role(ui_context, ROLE_OPERATOR))
    page._orders = [
        {"id": 1, "status": "awaiting_payment", "owned": False, "items": []},
        {"id": 2, "status": "awaiting_payment", "payment_info_at": "2026-10-21T08:00:00+00:00",
         "owned": False, "items": []},
    ]
    page._render()
    assert needs_payment_info(page._orders[0]) and not needs_payment_info(page._orders[1])
    assert page.table.item(0, 0).background().color() == QColor(theme.WARNING_BG)
    assert page.table.item(1, 0).background().color() != QColor(theme.WARNING_BG)
    assert "اطلاعات پرداخت" in page.waiting_label.text()


# ---- 8: masked card / Sheba ------------------------------------------------------------------------
def test_card_and_sheba_masks(ui_context, admin_qapp):
    from app.ui.pages import orders as page_mod

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    form = page_mod.PaymentInfoDialog(None, context, {"id": 3, "total": 10})
    card, sheba = form.inputs["card_number"], form.inputs["sheba"]
    assert card.inputMask().startswith("9999-9999-9999-9999")
    assert sheba.inputMask().startswith("IR")
    assert form.values()["card_number"] == "" and form.values()["sheba"] == ""
    card.setText("6037123456781234")
    sheba.setText("IR" + "1" * 24)
    assert form.values()["card_number"] == "6037-1234-5678-1234"
    assert form.values()["sheba"] == "IR" + "1" * 24
    card.setText("6037abc1")                          # only digits are kept
    assert page_mod.card_digits(card.text()) == "60371"
    assert page_mod.payment_info_problem(form.values()) == "شمارهٔ کارت باید دقیقاً ۱۶ رقم باشد."
    assert page_mod.sheba_text("۱" * 24) == "IR" + "1" * 24


# ---- 9: the permission table -----------------------------------------------------------------------
def test_daily_work_is_not_in_the_table():
    keys = {key for key, *_ in perms.SECTIONS}
    assert not keys & perms.ALWAYS_SECTIONS
    assert {"products", "groups", "pricelist", "models", "sales", "activity", "passwords",
            "staff", "server"} == keys
    sales = perms.role_permissions(ROLE_OPERATOR)
    for name in (perms.DASHBOARD_VIEW, perms.ORDERS_VIEW, perms.ITEM_REQUESTS,
                 perms.ARCHIVE_VIEW, perms.REPORTS_VIEW, perms.CUSTOMERS_APPROVE,
                 perms.ORDERS_ASSIGN):
        assert name in sales


# ---- 10: «انتقال همهٔ کارهای باز» -------------------------------------------------------------------
def test_transfer_open_work_from_the_users_page(ui_context, admin_qapp, monkeypatch):
    from app.ui.pages import users as users_mod

    page = users_mod.UsersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._users = [{"id": 2, "username": "mina", "full_name": "مینا", "active": True},
                   {"id": 3, "username": "reza", "full_name": "رضا", "active": True}]
    calls = []
    monkeypatch.setattr(page.context.api, "transfer_open_work",
                        lambda a, b: calls.append((a, b)) or {"orders": 2, "requests": 1})

    class Picking(users_mod.TransferDialog):
        def exec(self):
            self._accept()
            return 1

    monkeypatch.setattr(users_mod, "TransferDialog", Picking)
    monkeypatch.setattr(users_mod.widgets, "success", lambda *a, **k: None)
    monkeypatch.setattr(page, "run", lambda fn, on_success, on_error=None: on_success(fn()))
    page._transfer_open(page._users[0])
    assert calls == [(2, 3)]
