"""v2.8.2: no reload under the user's hands, payment details per order, «تنظیمات
برنامه» apart from «تنظیمات سرور فروشگاه», a working ✕, faster events, text that
fits, no «برمی‌دارم», and the per-section permission table."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from app import permissions as perms  # noqa: E402
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import widgets  # noqa: E402

from .test_ui import _pump, make_context_with_role, ui_context  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]


# ---- 1: automatic reloads wait while something is being edited ---------------------------------
def test_form_pages_never_reload_by_themselves(ui_context, admin_qapp):
    from app.ui.pages.server import ServerPage
    from app.ui.pages.settings import SettingsPage

    for cls in (ServerPage, SettingsPage):
        page = cls(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
        page.ensure_loaded()
        assert not cls.auto_refreshable and not cls.refresh_on_server_events
        assert not page._auto.is_running
        page.close()


def test_auto_refresh_waits_while_editing(ui_context, admin_qapp, monkeypatch):
    from app.ui.pages.orders import OrdersPage

    page = OrdersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    loads = []
    monkeypatch.setattr(page, "load", lambda: loads.append(1))
    monkeypatch.setattr(page, "has_unsaved_changes", lambda: True)
    assert page.soft_refresh() is False and loads == [] and page._refresh_pending
    monkeypatch.setattr(page, "has_unsaved_changes", lambda: False)
    assert page.soft_refresh() is True and loads == [1]


def test_typing_in_a_field_pauses_the_reload(ui_context, admin_qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from app.ui.pages.orders import OrdersPage

    page = OrdersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    field = page.findChild(QLineEdit)
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: field))
    assert page.is_editing()


def test_server_page_counts_unsaved_settings(ui_context, admin_qapp):
    from app.ui.pages.server import ServerPage

    page = ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._show_settings({"RECEIPT_DEADLINE_MINUTES": {"secret": False, "value": "30"}})
    assert not page.has_unsaved_changes()
    page._inputs["RECEIPT_DEADLINE_MINUTES"].setText("45")
    assert page.has_unsaved_changes() and page.is_editing()


# ---- 2: payment details typed for each order ------------------------------------------------------
def test_no_fixed_payment_details_in_server_settings():
    from app.server_settings import SETTINGS_FA

    for key in ("PAYMENT_CARD_NUMBER", "PAYMENT_SHEBA", "PAYMENT_OWNER", "BANK_ACCOUNT_TEXT"):
        assert key not in SETTINGS_FA
    wizard = (ROOT / "app" / "ui" / "server_setup_wizard.py").read_text(encoding="utf-8")
    assert "self.bank_text" not in wizard


def test_payment_form_checks_and_previews():
    from app.ui.pages.orders import payment_info_preview, payment_info_problem

    assert "دست‌کم یکی" in payment_info_problem({"holder": "علی"})
    assert payment_info_problem({"card_number": "1234"}) == "شمارهٔ کارت باید دقیقاً ۱۶ رقم باشد."
    assert payment_info_problem({"card_number": "۶۰۳۷-۹۹۱۱-۲۲۳۳-۴۴۵۵"}) == ""
    assert "شبا" in payment_info_problem({"sheba": "IR12"})
    assert payment_info_problem({"sheba": "IR" + "1" * 24}) == ""
    text = payment_info_preview({"card_number": "6037-9911-2233-4455", "holder": "علی",
                                 "bank": "", "note": ""})
    assert text == "شمارهٔ کارت: 6037-9911-2233-4455\nبه نام: علی"     # empty ones left out


def test_payment_button_sends_after_confirmation(ui_context, fake_api, admin_qapp, monkeypatch):
    from app.ui.pages import orders as page_mod

    order = fake_api.add_order(id=21, status="awaiting_payment", owned=False)
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = page_mod.OrderDetailDialog(context, order)
    assert dialog.payment_button.isVisibleTo(dialog)
    assert "هنوز فرستاده نشده" in " ".join(lbl.text() for lbl in dialog.findChildren(
        type(widgets.label(""))))

    answers = [False, True]
    monkeypatch.setattr(page_mod.widgets, "confirm", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(page_mod.widgets, "success", lambda *a, **k: None)

    form = page_mod.PaymentInfoDialog(dialog, context, order)
    form.inputs["card_number"].setText("6037 9911 2233 4455")
    form.inputs["holder"].setText("فروشگاه")
    form._accept()                                    # «بازگشت»: nothing sent
    assert not form.info
    form._accept()
    # v2.8.3: the masked field keeps the four groups
    assert form.info == {"card_number": "6037-9911-2233-4455", "holder": "فروشگاه"}

    class Accepting(page_mod.PaymentInfoDialog):
        def exec(self):
            self.info = {"card_number": "6037991122334455", "bank": "ملت"}
            return page_mod.QDialog.DialogCode.Accepted

    monkeypatch.setattr(page_mod, "PaymentInfoDialog", Accepting)
    assert page_mod.send_payment_info(dialog, context, order)
    assert fake_api.payment_bodies[-1]["card_number"] == "6037991122334455"
    assert fake_api.payment_bodies[-1]["sheba"] == ""             # empty = left out
    # the last details are offered next time («مثل دفعهٔ قبل»)
    again = page_mod.PaymentInfoDialog(dialog, context, order)
    assert again.last_button.isEnabled()
    again.fill_last()
    assert again.inputs["holder"].text() == "فروشگاه"


# ---- 3: two settings pages ----------------------------------------------------------------------
def test_program_settings_and_server_settings_by_permission(ui_context, admin_qapp):
    from app.ui.main_window import NAV_ITEMS, MainWindow

    labels = {key: text for key, text, _i, _p in NAV_ITEMS}
    assert labels["settings"] == "تنظیمات برنامه"
    assert labels["server"] == "تنظیمات سرور فروشگاه"
    window = MainWindow(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert "settings" not in window._nav_buttons and "server" not in window._nav_buttons
    window.close()
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    context.principal = replace(context.principal, permissions=perms.client_permissions(
        sorted(perms.SALES_SERVER_PERMISSIONS | {"server.view"})))
    window = MainWindow(context)
    assert "server" in window._nav_buttons
    page = window._pages["server"]
    assert not page.save_settings_button.isEnabled()        # «دیدن» only
    window.close()


# ---- 4: the ✕ of every dialog works ------------------------------------------------------------------
def test_dialog_close_button_is_enabled():
    flags = widgets.DIALOG_FLAGS
    for flag in (Qt.WindowType.WindowCloseButtonHint, Qt.WindowType.CustomizeWindowHint,
                 Qt.WindowType.WindowMaximizeButtonHint, Qt.WindowType.WindowSystemMenuHint):
        assert flags & flag


def test_responsive_dialog_uses_the_flags(admin_qapp):
    from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QLabel("x"))
    widgets.make_responsive(dialog)
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    assert dialog.windowFlags() & Qt.WindowType.CustomizeWindowHint


# ---- 5: ShopAdmin hears about new work within seconds ----------------------------------------------
def test_event_poll_is_3_seconds_and_old_default_is_moved(tmp_path):
    store = Store(tmp_path / "s.db")
    assert store.get_setting("event_poll_seconds") == 3
    store.set_setting("event_poll_seconds", 15)
    store.close()
    import sqlite3

    conn = sqlite3.connect(tmp_path / "s.db")
    conn.execute("DELETE FROM settings WHERE key='event_poll_v282'")
    conn.commit()
    conn.close()
    again = Store(tmp_path / "s.db")
    assert again.get_setting("event_poll_seconds") == 3           # the old default moved
    again.set_setting("event_poll_seconds", 15)                    # chosen again: kept
    again.close()
    assert Store(tmp_path / "s.db").get_setting("event_poll_seconds") == 15


# ---- 6: text fits ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["کاربر فروش", "گذرواژهٔ موقت", "ثبت‌شده در حسابداری"])
def test_badges_are_as_wide_as_their_text(admin_qapp, text):
    pill = widgets.StatusPill(text, "pending")
    bold = QFont(pill.font())
    bold.setBold(True)
    need = QFontMetrics(bold).horizontalAdvance(text) + 2 * widgets.StatusPill.PADDING
    assert pill.sizeHint().width() >= need and pill.minimumSizeHint().width() >= need


def test_user_row_actions_are_in_a_menu(ui_context, fake_api, admin_qapp):
    from PySide6.QtWidgets import QPushButton

    from app.ui.pages.users import UsersPage

    page = UsersPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    holder = page._actions_for({"id": 99, "username": "x", "active": True, "locked": True})
    texts = [b.text() for b in holder.findChildren(QPushButton)]
    assert texts == ["ویرایش", "بیشتر"]
    more = [b for b in holder.findChildren(QPushButton) if b.text() == "بیشتر"][0]
    assert [a.text() for a in more.menu_actions if a.text()] == [
        "تغییر گذرواژه", "بازنشانی گذرواژه به ۱۲۳۴۵", "رفع قفل",
        "انتقال همهٔ کارهای باز به همکار دیگر", "غیرفعال کردن", "حذف کاربر"]


def test_text_fit_audit_script_exists():
    source = (ROOT / "scripts" / "text_fit_audit.py").read_text(encoding="utf-8")
    assert "def problems_in" in source


# ---- 8: no «برمی‌دارم» -----------------------------------------------------------------------------
def test_the_old_take_button_text_is_gone():
    """v2.17.0: the button is called «برداشت» now."""
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "برمی‌دارم" not in text, path.name


def test_taken_by_a_colleague_is_explained():
    from app.api_client import translate_detail

    text = translate_detail("Another colleague is working on this", 403)
    assert "همکار دیگری زودتر" in text


# ---- 10: per-section permissions -------------------------------------------------------------------
def test_sections_match_the_server():
    server = (ROOT.parent / "shopapi" / "app" / "staff.py").read_text(encoding="utf-8")
    for key, label, view, edit in perms.SECTIONS:
        assert re.search(rf'\("{key}", "{re.escape(label)}",\s*{view}, {edit}\)', server), key


def test_section_names_unlock_the_screens():
    granted = perms.client_permissions(["requests.view"])
    assert perms.ITEM_REQUESTS_VIEW in granted and perms.ITEM_REQUESTS not in granted
    granted = perms.client_permissions(["orders.view", "payinfo.edit", "ship.edit", "cancel.edit"])
    assert {perms.ORDERS_PAYMENT_INFO, perms.ORDERS_SHIP, perms.ORDERS_CANCEL} <= granted
    assert perms.ORDERS_APPROVE_PAYMENT not in granted          # v2.17.0: its own tick
    assert perms.with_implied({"groups.edit"}) == {"groups.edit", "groups.view"}
    # a not-yet-updated server's names still work
    assert perms.SHOP_STATE in perms.client_permissions(["shop.state"])


def test_permission_table_rows(ui_context, admin_qapp):
    from app.ui.pages.users import UserFormDialog

    form = UserFormDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), None)
    assert "assign.view" not in form.permission_checks           # «ارجاع»: «تغییر» only
    assert "dashboard.edit" not in form.permission_checks
    form.permission_checks["server.edit"].setChecked(True)
    assert form.permission_checks["server.view"].isChecked()
    form.reset_permissions()                                       # «برگرداندن به دسترسی‌های نقش»
    assert not form.permission_checks["server.view"].isChecked()
    assert form.permission_changes() == ([], [])
