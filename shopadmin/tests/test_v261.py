"""v2.6.1 in ShopAdmin: «گروه‌های کالا» as a tree with inherited ticks and «قیمت با
استعلام», the dashboard warning without a phone group, and «درخواست کالا» with the
type column/filter, untruncated date column, details dialog, staff note and replies."""
from __future__ import annotations

import re

from app.statuses import ROLE_ADMIN

from .test_ui import _pump, make_context_with_role, ui_context  # noqa: F401

TREE = [
    {"code": 1, "name": "لوازم جانبی", "parent": None, "show_in_bot": True, "is_phone": False},
    {"code": 3, "name": "گوشی", "parent": None, "show_in_bot": True, "is_phone": True},
    {"code": 31, "name": "سامسونگ", "parent": 3, "show_in_bot": False, "is_phone": False},
    {"code": 32, "name": "اپل", "parent": 3, "show_in_bot": False, "is_phone": False},
    {"code": 5, "name": "ساعت", "parent": None, "show_in_bot": False, "is_phone": False,
     "price_on_inquiry": False},
]


def _groups_page(ui_context, admin_qapp, fake_api):
    from app.ui.pages.product_groups import ProductGroupsPage

    fake_api.product_groups = [dict(g) for g in TREE]
    page = ProductGroupsPage(make_context_with_role(ui_context, ROLE_ADMIN))
    page.load()
    _pump(admin_qapp)
    return page


def test_groups_are_a_tree_and_children_inherit(ui_context, admin_qapp, fake_api):
    page = _groups_page(ui_context, admin_qapp, fake_api)
    assert page.tree.topLevelItemCount() == 3
    phones = page._items[3]
    assert phones.childCount() == 2 and phones.child(0).text(0) == "سامسونگ"
    brand = page._checks[31]
    # the parent's ticks reach the brands: shown checked and locked
    assert brand["is_phone"].isChecked() and not brand["is_phone"].isEnabled()
    assert brand["show_in_bot"].isChecked() and not brand["show_in_bot"].isEnabled()
    assert brand["price_on_inquiry"].isEnabled() and not brand["price_on_inquiry"].isChecked()
    assert page.effective(31, "is_phone") and not page.inherited(3, "is_phone")
    # unticking the parent frees the children (their own values come back)
    page.set_flag(3, "is_phone", False)
    assert not brand["is_phone"].isChecked() and brand["is_phone"].isEnabled()
    # ticking a parent «قیمت با استعلام» applies to the children
    page.set_flag(3, "price_on_inquiry", True)
    assert brand["price_on_inquiry"].isChecked() and not brand["price_on_inquiry"].isEnabled()
    page.save()
    _pump(admin_qapp)
    sent = {g["code"]: g for g in fake_api.group_puts[-1]["groups"]}
    # only OWN ticks are saved; the server applies inheritance itself
    assert sent[3] == {"code": 3, "show_in_bot": True, "is_phone": False,
                       "price_on_inquiry": True}
    assert sent[31] == {"code": 31, "show_in_bot": False, "is_phone": False,
                        "price_on_inquiry": False}


def test_groups_warn_without_a_phone_group(ui_context, admin_qapp, fake_api):
    page = _groups_page(ui_context, admin_qapp, fake_api)
    assert not page.warning.isVisible() or "گوشی" not in page.warning.text()
    page.set_flag(3, "is_phone", False)
    assert "گروه گوشی" in page.warning.text()
    assert "۱ با استعلام" not in page.summary.text()


def test_dashboard_warns_without_a_phone_group(ui_context, admin_qapp, fake_api):
    from app.ui.pages.dashboard import DashboardPage, setup_problems

    problems = setup_problems({"payment_ready": True, "catalog_ready": True,
                               "phone_groups_ready": False})
    assert len(problems) == 1 and "گروه گوشی" in problems[0]
    fake_api.phone_groups_ready = False
    page = DashboardPage(ui_context)
    page.show()
    page.load()
    _pump(admin_qapp)
    assert page.setup_warning.isVisible() and "گروه گوشی" in page.setup_warning.text()
    fake_api.phone_groups_ready = True
    page.load()
    _pump(admin_qapp)
    assert not page.setup_warning.isVisible()


# ---- «درخواست کالا» ------------------------------------------------------------------------------
REQUESTS = [
    {"id": 3, "user_id": 1, "kala_code": 600, "product_name": "ساعت طلا", "text": "",
     "kind": "inquiry", "status": "new", "created_at": "2026-10-15T07:30:45+00:00",
     "customer_name": "علی", "person_code": 7001, "customer_phone": "09121234567",
     "platform": "bale", "admin_note": ""},
    {"id": 2, "user_id": 1, "kala_code": None, "product_name": "",
     "text": "نوکیا ۳۳۱۰ مشکی با جعبه و فاکتور و گارانتی", "kind": "unavailable",
     "status": "new", "created_at": "2026-10-14T10:00:00+00:00", "customer_name": "علی",
     "person_code": 7001, "customer_phone": "09121234567", "platform": "bale",
     "admin_note": ""},
]


def _requests_page(ui_context, admin_qapp, fake_api):
    from app.ui.pages.item_requests import ItemRequestsPage

    fake_api.item_requests = [dict(r) for r in REQUESTS]
    page = ItemRequestsPage(ui_context)
    page.resize(1100, 700)
    page.show()
    page.load()
    _pump(admin_qapp)
    return page


def test_requests_table_type_column_and_filter(ui_context, admin_qapp, fake_api):
    from app.ui.pages.item_requests import COL_TIME, HEADERS

    page = _requests_page(ui_context, admin_qapp, fake_api)
    assert HEADERS[-1] == "کالای درخواستی" and "نوع" in HEADERS
    assert page.table.rowCount() == 2
    assert [page.table.item(r, 2).text() for r in range(2)] == ["استعلام قیمت", "ناموجود"]
    page.set_kind("inquiry")
    assert page.table.rowCount() == 1 and page.table.item(0, 0).text() == "۳"
    page.set_kind("unavailable")
    assert page.table.rowCount() == 1 and page.table.item(0, 0).text() == "۲"
    page.set_kind("")
    # the date column is never squeezed below its text (it was cut in v2.6.0)
    metrics = page.table.fontMetrics()
    text = page.table.item(0, COL_TIME).text()
    assert page.table.columnWidth(COL_TIME) >= metrics.horizontalAdvance(text) + 20
    # the product header is the stretching last column
    assert page.table.horizontalHeader().stretchLastSection()
    assert page.table._key == "item_requests_v261"


def test_row_click_opens_the_details(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import item_requests

    page = _requests_page(ui_context, admin_qapp, fake_api)
    opened = []
    monkeypatch.setattr(item_requests.ItemRequestsPage, "open_request",
                        lambda self, item: opened.append(item["id"]))
    page.table.row_activated.emit(1)
    assert opened == [2]


def _dialog(ui_context, admin_qapp, fake_api, item=REQUESTS[1]):
    from app.ui.pages.item_requests import ItemRequestDialog

    fake_api.item_requests = [dict(r) for r in REQUESTS]
    dialog = ItemRequestDialog(ui_context, dict(item))
    _pump(admin_qapp)
    return dialog


def test_dialog_shows_everything(ui_context, admin_qapp, fake_api):
    from PySide6.QtWidgets import QLabel

    dialog = _dialog(ui_context, admin_qapp, fake_api)
    texts = " | ".join(w.text() for w in dialog.findChildren(QLabel))
    assert "علی" in texts and "۷۰۰۱" in texts and "۰۹۱۲۱۲۳۴۵۶۷" in texts and "بله" in texts
    assert "ناموجود" in texts
    assert dialog.request_text.toPlainText() == REQUESTS[1]["text"]       # never cut
    assert "۱۴۰۵/۰۷/۲۲" in texts                                            # full time,
    assert re.search("[۰-۹]{2}:[۰-۹]{2}:[۰-۹]{2}", texts)                   # to the second
    assert dialog.seen_button.isVisibleTo(dialog) and dialog.done_button.isVisibleTo(dialog)
    dialog.set_status("seen")
    _pump(admin_qapp)
    assert fake_api.item_requests[1]["status"] == "seen" and dialog.changed
    assert not dialog.seen_button.isVisibleTo(dialog)
    dialog.set_status("done")
    _pump(admin_qapp)
    assert fake_api.item_requests[1]["status"] == "done"
    assert dialog.reopen_button.isVisibleTo(dialog) and not dialog.done_button.isVisibleTo(dialog)


def test_dialog_note(ui_context, admin_qapp, fake_api):
    dialog = _dialog(ui_context, admin_qapp, fake_api)
    dialog.note_edit.setPlainText("  تماس گرفته شد  ")
    dialog.save_note()
    _pump(admin_qapp)
    assert fake_api.item_requests[1]["admin_note"] == "تماس گرفته شد"
    assert "آخرین ویرایش" in dialog.note_info.text()


def test_dialog_sends_a_message_and_shows_history(ui_context, admin_qapp, fake_api):
    dialog = _dialog(ui_context, admin_qapp, fake_api)
    assert dialog.history.rowCount() == 0
    dialog.message_edit.setPlainText("موجود شد")
    dialog.send_message()
    _pump(admin_qapp)
    _pump(admin_qapp)                                   # send, then re-read the history
    sent = fake_api.item_request_messages[2]
    assert [m["text"] for m in sent] == ["موجود شد"]
    assert dialog.message_edit.toPlainText() == "" and dialog.history.rowCount() == 1
    assert dialog.history.item(0, 2).text() == "در صف ارسال (ربات)"
    assert dialog._poll.isActive()
    # the bot reports a failure -> a clear error in the dialog
    sent[0].update(status="failed", error="مشتری ربات را مسدود کرده است")
    dialog._poll_tick()
    _pump(admin_qapp)
    _pump(admin_qapp)
    assert "مسدود" in dialog.history.item(0, 2).text()
    assert "ارسال نشد" in dialog.send_info.text() and not dialog._poll.isActive()
    dialog.done(0)


def test_dialog_send_error_is_clear(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets

    shown = []
    monkeypatch.setattr(widgets, "error", lambda _p, title, message, *a: shown.append(message))
    dialog = _dialog(ui_context, admin_qapp, fake_api)
    dialog.send_message()                                   # empty text: not sent
    assert "خالی" in dialog.send_info.text() and fake_api.item_request_messages.get(2) in (None, [])
    fake_api.message_fail = "Customer has no messenger"
    dialog.message_edit.setPlainText("سلام")
    dialog.send_message()
    _pump(admin_qapp)
    assert shown and "پیام‌رسانی ندارد" in shown[0]
    assert "پیام‌رسانی ندارد" in dialog.send_info.text()
    assert dialog.message_edit.toPlainText() == "سلام"     # kept for another try
