"""v2.8.0 in ShopAdmin: right-aligned Persian (real right edge, LTR codes), «کارهای من»,
owner column, waiting highlight, timeline / handover / copy in the order dialog,
«درخواست خرید» (تأیید موجودی / ناموجود), «گزارش فعالیت», «بایگانی», auto refresh,
per-user notifications and the mapping suggestions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QStyle  # noqa: E402

from app import activity, permissions as perms  # noqa: E402
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN  # noqa: E402
from app.ui import rtl, widgets  # noqa: E402

from .test_ui import _pump, _render_page, make_context_with_role, ui_context  # noqa: E402,F401


# ---- 1: RTL -----------------------------------------------------------------------------------
def test_right_means_the_real_right_edge(admin_qapp):
    # plain AlignRight is mirrored to the LEFT in a right-to-left widget
    mirrored = QStyle.visualAlignment(Qt.LayoutDirection.RightToLeft, Qt.AlignmentFlag.AlignRight)
    assert mirrored & Qt.AlignmentFlag.AlignLeft
    fixed = QStyle.visualAlignment(Qt.LayoutDirection.RightToLeft, rtl.RIGHT)
    assert fixed & Qt.AlignmentFlag.AlignRight


def test_tables_and_labels_sit_on_the_right(admin_qapp):
    table = widgets.DataTable(("نام", "کد"))
    table.insertRow(0)
    item = table.set_cell(0, 0, "علی")
    assert item.textAlignment() & Qt.AlignmentFlag.AlignAbsolute
    assert item.textAlignment() & Qt.AlignmentFlag.AlignRight
    assert widgets.label("مشتری").alignment() & Qt.AlignmentFlag.AlignAbsolute
    assert isinstance(table.itemDelegate(), widgets.BidiDelegate)


def test_latin_only_text_is_ltr():
    assert rtl.is_ltr_text("17 Pro 256 ZAA") and rtl.is_ltr_text(r"C:\Data\x.db")
    assert not rtl.is_ltr_text("آیفون 17") and not rtl.is_ltr_text("۱۲۳")
    assert rtl.bidi("ZAA").startswith(rtl.LRE) and rtl.bidi("علی") == "علی"


def test_delegate_lays_out_codes_left_to_right(admin_qapp):
    from PySide6.QtWidgets import QStyleOptionViewItem

    table = widgets.DataTable(("کد",))
    table.insertRow(0)
    table.set_cell(0, 0, "ZAA-256")
    option = QStyleOptionViewItem()
    table.itemDelegate().initStyleOption(option, table.model().index(0, 0))
    assert option.direction == Qt.LayoutDirection.LeftToRight


# ---- 5: activity sentences ------------------------------------------------------------------------
def test_timeline_text_names_for_the_manager_only():
    steps = [{"action": "receipt_approve", "actor_name": "احمد"},
             {"action": "assign", "actor_name": "احمد", "to_name": "علی"},
             {"action": "ship", "actor_name": "علی"}]
    assert activity.timeline_text(steps) == "احمد رسید را تأیید کرد ← به علی ارجاع داد ← علی ارسال کرد"
    hidden = [{"action": "claim", "is_me": False}, {"action": "handover", "to_me": True},
              {"action": "ship", "is_me": True}]
    text = activity.timeline_text(hidden)
    assert "همکار" in text and "شما" in text and "احمد" not in text
    assert activity.timeline_text([]) == "هنوز کاری روی آن انجام نشده است."


# ---- 6/8: orders page ----------------------------------------------------------------------------
def _late(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_sales_user_starts_on_my_work_and_sees_the_owner(ui_context, fake_api, admin_qapp):
    from app.ui.pages.orders import OrdersPage

    fake_api.add_order(id=1, owned=True, owned_by_me=True, updated_at=_late(1))
    fake_api.add_order(id=2, owned=False, updated_at=_late(15))
    page = OrdersPage(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert page._mine and page.auto_refreshable
    _render_page(admin_qapp, page)
    assert page.table.rowCount() == 1 and page.table.item(0, 5).text() == "من"
    assert ("GET", "/admin/orders") in fake_api.requests
    page.set_scope(False)
    _pump(admin_qapp)
    assert page.table.rowCount() == 2
    owners = {page.table.item(r, 0).text(): page.table.item(r, 5).text() for r in range(2)}
    assert owners == {"۱": "من", "۲": "آزاد"}
    # a receipt waiting 15 minutes is highlighted and counted
    late_row = next(r for r in range(2) if page.table.item(r, 0).text() == "۲")
    assert page.table.item(late_row, 0).data(Qt.ItemDataRole.UserRole) == "late"
    assert page.waiting_label.isVisibleTo(page) and "۱" in page.waiting_label.text()


def test_manager_starts_on_everything(ui_context, admin_qapp):
    from app.ui.pages.orders import OrdersPage

    page = OrdersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert not page._mine


def test_order_dialog_timeline_copy_and_handover(ui_context, fake_api, admin_qapp):
    from PySide6.QtWidgets import QApplication

    from app.ui.pages.orders import OrderDetailDialog

    order = fake_api.add_order(id=5, user_phone="09121234567", owned=True, owned_by_me=True)
    fake_api.timelines[("order", 5)] = [{"action": "claim", "is_me": True}]
    fake_api.add_staff("sara", full_name="سارا")
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = OrderDetailDialog(context, order)
    _pump(admin_qapp)
    assert [text for _when, text in dialog.timeline_view.lines] == ["شما کار را برداشت"]
    dialog.copy_phone_button.click()
    assert QApplication.clipboard().text() == "09121234567"
    # the owner may hand it over; the colleague list holds names only
    assert dialog.assign_button.isVisibleTo(dialog)
    dialog.close()


def test_free_order_has_the_take_button(ui_context, fake_api, admin_qapp):
    """v2.17.0: «برداشت» stops the repeats to staff; any first action still takes it."""
    from app.ui.pages.orders import OrderDetailDialog

    order = fake_api.add_order(id=6, owned=False)
    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_OPERATOR), order)
    assert dialog.claim_button.isVisibleTo(dialog)
    # v2.8.3: «ارجاع» is always on (the server lets anyone hand over a free order)
    assert dialog.assign_button.isVisibleTo(dialog)


def test_finished_order_is_read_only(ui_context, fake_api, admin_qapp):
    from app.ui.pages.orders import OrderDetailDialog

    order = fake_api.add_order(id=8, status="written", shipped_at="2026-10-18T10:00:00+00:00",
                               finished=True)
    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), order)
    for button in (dialog.approve_button, dialog.reject_button, dialog.ship_button,
                   dialog.cancel_button, dialog.payment_button, dialog.assign_button):
        assert not button.isVisibleTo(dialog)


def test_assign_dialog_lists_colleagues(ui_context, fake_api, admin_qapp):
    from app.ui.pages.orders import AssignDialog

    fake_api.add_staff("sara", full_name="سارا")
    dialog = AssignDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), None, "سفارش ۵")
    _pump(admin_qapp)
    assert [dialog.combo.itemText(i) for i in range(dialog.combo.count())] == ["سارا"]
    dialog._accept()
    assert dialog.staff_id == fake_api.find_staff("sara")["id"]


# ---- 4: purchase requests ----------------------------------------------------------------------
def _purchase(fake_api, **kw) -> dict:
    row = {"id": 31, "user_id": 1, "kind": "purchase", "status": "new", "created_at": _late(2),
           "product_name": "iPHONE 17 Pro 256 CHA", "color": "Silver", "part": "CHA",
           "price_rial": 1_150_000_000, "kala_code": None, "customer_name": "مشتری", "text": "",
           "platform": "bale", "owned": False}
    row.update(kw)
    fake_api.item_requests.append(row)
    return row


def test_purchase_request_row_and_stock_confirm(ui_context, fake_api, admin_qapp, monkeypatch):
    from app.ui.pages import item_requests as page_mod

    row = _purchase(fake_api)
    page = page_mod.ItemRequestsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    _render_page(admin_qapp, page)
    assert page.table.item(0, 2).text() == "درخواست خرید - استعلام قیمت"
    product = page.table.item(0, page_mod.COL_PRODUCT).text()
    assert "Silver" in product and "CHA" in product
    dialog = page_mod.ItemRequestDialog(page.context, row)
    assert dialog.stock_button.isVisibleTo(dialog) and dialog.unavailable_button.isVisibleTo(dialog)
    assert not dialog.done_button.isVisibleTo(dialog)

    class Confirm:
        DialogCode = page_mod.QDialog.DialogCode

        def __init__(self, *_a, **_k):
            self.kala_code, self.price = 600, 1_100_000_000

        def exec(self):
            return page_mod.QDialog.DialogCode.Accepted

    monkeypatch.setattr(page_mod, "StockConfirmDialog", Confirm)
    monkeypatch.setattr(page_mod.widgets, "success", lambda *a, **k: None)
    monkeypatch.setattr(page_mod.widgets, "info", lambda *a, **k: None)
    dialog.confirm_stock()
    _pump(admin_qapp)
    assert fake_api.stock_confirms == [{"id": 31, "kala_code": 600, "price_rial": 1_100_000_000,
                                        "note": ""}]
    # v2.9.2: the price is with the customer; it may be sent again until they answer
    assert dialog.item["outcome"] == "offered" and dialog.stock_button.isVisibleTo(dialog)
    assert dialog.stock_button.text() == "ارسال قیمت دوباره"
    assert "منتظر «تأیید و خرید»" in dialog.outcome_label.text()


def test_stock_confirm_dialog_needs_a_product_when_unmapped(admin_qapp):
    from app.ui.pages.item_requests import StockConfirmDialog

    dialog = StockConfirmDialog(None, {"kind": "purchase", "kala_code": None,
                                       "price_rial": 5, "product_name": "x"})
    dialog._accept()
    assert dialog.error_label.isVisibleTo(dialog) and dialog.kala_code is None
    dialog.code_input.setText("۶۰۰")
    dialog.price_input.setText("")
    dialog._accept()
    assert dialog.kala_code == 600 and dialog.price is None


def test_stock_confirm_dialog_needs_a_price_without_a_list_price(admin_qapp):
    """v2.9.2: no list price (or a price waiting for the manager): type one."""
    from app.ui.pages.item_requests import StockConfirmDialog

    dialog = StockConfirmDialog(None, {"kind": "purchase", "kala_code": 600,
                                       "price_rial": None, "product_name": "x"})
    assert not dialog.list_button.isVisibleTo(dialog)
    dialog._accept()
    assert dialog.error_label.isVisibleTo(dialog) and dialog.price is None
    dialog.price_input.setText("۵۲۵٬۰۰۰٬۰۰۰")
    dialog._accept()
    assert dialog.price == 525_000_000


def test_unavailable_closes_the_request(ui_context, fake_api, admin_qapp, monkeypatch):
    from app.ui.pages import item_requests as page_mod

    row = _purchase(fake_api)
    monkeypatch.setattr(page_mod.widgets, "confirm", lambda *a, **k: True)
    dialog = page_mod.ItemRequestDialog(make_context_with_role(ui_context, ROLE_OPERATOR), row)
    dialog.mark_unavailable()
    _pump(admin_qapp)
    assert dialog.item["outcome"] == "unavailable"
    assert not dialog.send_button.isEnabled() and not dialog.note_button.isEnabled()


# ---- 5/7: activity and archive pages ----------------------------------------------------------------
def test_activity_page_is_for_the_manager(ui_context, fake_api, admin_qapp):
    from app.ui.main_window import MainWindow
    from app.ui.pages.activity import ActivityPage, day_bounds

    fake_api.activity_rows = [{"id": 1, "ts": "2026-10-18T08:00:00+00:00",
                               "action": "receipt_approve", "actor_name": "احمد",
                               "target_type": "order", "target_id": 5,
                               "customer_name": "رضا"}]
    page = ActivityPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    _render_page(admin_qapp, page)
    assert page.table.rowCount() == 1
    assert [page.table.item(0, c).text() for c in (1, 2, 3, 4)] == [
        "احمد", "رسید را تأیید کرد", "سفارش ۵", "رضا"]
    assert fake_api.activity_params[-1]["date_from"].endswith("+00:00")
    start, end = day_bounds(datetime(2026, 10, 18).date(), datetime(2026, 10, 18).date())
    assert start == "2026-10-17T20:30:00+00:00" and end == "2026-10-18T20:30:00+00:00"
    sales = MainWindow(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert "activity" not in sales._pages and "archive" in sales._pages
    sales.close()


def test_archive_page_is_read_only(ui_context, fake_api, admin_qapp):
    from app.ui.pages.archive import ArchivePage

    fake_api.archived_orders = [{**fake_api.add_order(id=70, status="cancelled"),
                                 "archived": True, "finished": True, "accounting_db": "hesab5"}]
    fake_api.archived_requests = [_purchase(fake_api, id=71, status="done",
                                            outcome="unavailable", archived=True)]
    page = ArchivePage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    _render_page(admin_qapp, page)
    assert page.orders_table.rowCount() == 1
    assert page.orders_table.item(0, 6).text() == "hesab5"
    assert page.db_input.isVisibleTo(page)
    page.set_tab("requests")
    _pump(admin_qapp)
    assert page.requests_table.item(0, 3).text() == "ناموجود اعلام شد"
    sales = ArchivePage(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert not sales.db_input.isVisibleTo(sales)


# ---- 8: notifications, permissions, suggestions ----------------------------------------------------
def test_notifications_are_per_user(ui_context):
    from app.notifications import set_user_setting, user_setting

    store = ui_context.store
    assert user_setting(store, "notify_sound", "mina") is True
    set_user_setting(store, "notify_sound", "mina", False)
    assert user_setting(store, "notify_sound", "mina") is False
    assert user_setting(store, "notify_sound", "sara") is True


def test_notification_dialog_saves_for_this_user(ui_context, admin_qapp):
    from app.notifications import user_setting
    from app.ui.main_window import NotificationDialog

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = NotificationDialog(context)
    dialog.sound_check.setChecked(False)
    dialog.save()
    assert user_setting(context.store, "notify_sound", context.principal.username) is False


def test_assign_tick_and_new_pages_in_permissions():
    assert perms.ORDERS_ASSIGN in perms.client_permissions(["orders.assign"])
    assert perms.ARCHIVE_VIEW in perms.role_permissions(ROLE_OPERATOR)
    assert perms.ACTIVITY_VIEW not in perms.role_permissions(ROLE_OPERATOR)
    assert perms.ACTIVITY_VIEW in perms.role_permissions(ROLE_SUPER_ADMIN)
    assert perms.ORDERS_ASSIGN in perms.client_permissions(["assign.edit"])
    assert perms.SERVER_PERMISSION_FA["assign.edit"] == "ارجاع کار به همکار — تغییر"


def test_mapping_dialog_shows_three_suggestions(ui_context, fake_api, admin_qapp):
    from app.ui.pages.pricelist import MapRowDialog

    fake_api.suggestions["k1"] = {"items": [
        {"code": 600, "name": "آیفون ۱۷ پرو ۲۵۶ گیگ", "score": 0.96},
        {"code": 601, "name": "آیفون ۱۷ پرو ۵۱۲", "score": 0.7},
        {"code": 602, "name": "آیفون ۱۷", "score": 0.6}], "confident": 600}
    dialog = MapRowDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN),
                          {"row_key": "k1", "section": "iPHONE", "description": "17 Pro 256 ZAA"})
    _pump(admin_qapp)
    assert dialog.results.count() == 3
    assert dialog.code_input.value() == 600
    assert "۹۶" in dialog.results.item(0).text()
