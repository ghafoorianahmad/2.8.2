"""v2.17.0 in ShopAdmin: the first receipt's name, the address on the order, the new
customer's details, Windows start and the tray."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog  # noqa: E402

from app import autostart  # noqa: E402
from app.statuses import ROLE_SUPER_ADMIN  # noqa: E402

from .test_ui import make_context_with_role, ui_context  # noqa: E402,F401
from .test_v2170 import _pump  # noqa: E402

ORDER = {"id": 91, "status": "receipt_uploaded", "total": 10, "items": [], "first_receipt": True,
         "user_name": "نام پروفایل", "person_name": "علی رضایی",
         "created_at": "2026-11-01T10:00:00+00:00"}


# ---- #9 the first receipt --------------------------------------------------------------------------
def test_first_step_shows_the_name_and_two_answers(admin_qapp):
    from app.ui.pages.orders import FirstReceiptDialog, registered_name

    assert registered_name(ORDER) == "علی رضایی"
    assert registered_name({"user_name": "نام"}) == "نام"
    dialog = FirstReceiptDialog(None, "علی رضایی")
    assert dialog.same_button.isVisibleTo(dialog) and dialog.different_button.isVisibleTo(dialog)
    assert not dialog.question.isVisibleTo(dialog) and not dialog.record_button.isVisibleTo(dialog)
    dialog._same()
    assert dialog.result() == QDialog.DialogCode.Accepted and not dialog.record_payer


def test_not_the_same_asks_record_or_keep(admin_qapp):
    from app.ui.pages.orders import FirstReceiptDialog

    dialog = FirstReceiptDialog(None, "علی رضایی")
    dialog.different_button.click()
    assert dialog.question.text() == "نام واریزکننده ثبت شود یا همان نام بماند؟"
    assert dialog.question.isVisibleTo(dialog)
    assert dialog.record_button.isVisibleTo(dialog) and dialog.keep_button.isVisibleTo(dialog)
    assert not dialog.same_button.isVisibleTo(dialog)
    # «همان نام بماند»: nothing recorded, nothing blocked
    dialog.keep_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted and not dialog.record_payer


def test_recording_needs_the_name(admin_qapp):
    from app.ui.pages.orders import FirstReceiptDialog

    dialog = FirstReceiptDialog(None, "علی رضایی")
    dialog._different()
    dialog._record()
    assert not dialog.record_payer and dialog.error_label.isVisibleTo(dialog)
    dialog.payer_input.setText("  حسین   احمدی ")
    dialog._record()
    assert dialog.record_payer and dialog.payer_name == "حسین احمدی"


def _approve_with(context, fake_api, monkeypatch, on_exec, order=None):
    from app.ui import widgets
    from app.ui.pages import orders

    order = dict(order or ORDER)
    fake_api.orders.append(dict(order))
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(orders.FirstReceiptDialog, "exec", on_exec)
    sent = {}
    real = context.api.approve_payment

    def spy(order_id, **kw):
        sent.update(kw, called=True)
        return real(order_id, **kw)

    monkeypatch.setattr(context.api, "approve_payment", spy)
    dialog = orders.OrderDetailDialog(context, order)
    return dialog, sent


def test_first_receipt_sends_the_answer(ui_context, admin_qapp, fake_api, monkeypatch):
    def fill(self):
        self.record_payer, self.payer_name = True, "حسین احمدی"
        return QDialog.DialogCode.Accepted

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    dialog, sent = _approve_with(context, fake_api, monkeypatch, fill)
    dialog._approve()
    _pump(admin_qapp, until=lambda: sent.get("called"))
    assert sent == {"payer_checked": True, "record_payer": True, "payer_name": "حسین احمدی",
                    "called": True}


def test_cancel_on_the_first_receipt_changes_nothing(ui_context, admin_qapp, fake_api, monkeypatch):
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    dialog, sent = _approve_with(context, fake_api, monkeypatch,
                                 lambda self: QDialog.DialogCode.Rejected)
    dialog._approve()
    _pump(admin_qapp, rounds=20)
    assert sent == {}


def test_later_receipts_are_not_asked(ui_context, admin_qapp, fake_api, monkeypatch):
    def fail(self):
        pytest.fail("must not ask again")

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    dialog, sent = _approve_with(context, fake_api, monkeypatch, fail,
                                 {**ORDER, "first_receipt": False})
    dialog._approve()
    _pump(admin_qapp, until=lambda: sent.get("called"))
    assert sent == {"called": True}


# ---- #10 the address --------------------------------------------------------------------------------
def _texts(widget):
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def test_address_and_payer_are_on_the_order(ui_context, admin_qapp):
    from app.ui.pages.orders import OrderDetailDialog

    dialog = OrderDetailDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN),
                               {**ORDER, "ship_address": "تهران، ولیعصر، پلاک 1",
                                "payer_name": "حسین احمدی"})
    shown = _texts(dialog)
    assert "تهران، ولیعصر، پلاک 1" in shown and "آدرس ارسال" in shown
    assert "حسین احمدی" in shown and "نام واریزکننده" in shown


def test_new_customer_details_fill_the_approve_dialog(ui_context, admin_qapp):
    from app.ui.pages.customers import ApproveCustomerDialog, details_lines

    customer = {"id": 3, "name": "نام پروفایل", "platform": "bale", "phone": "09124445555",
                "status": "pending", "created_at": "2026-11-01T10:00:00+00:00",
                "first_name": "علی", "last_name": "رضایی", "national_code": "0499370899",
                "address": "تهران، ولیعصر"}
    assert "کد ملی" in details_lines(customer) and "تهران، ولیعصر" in details_lines(customer)
    assert details_lines({}) == ""
    dialog = ApproveCustomerDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN), customer)
    assert dialog.first_name_input.text() == "علی" and dialog.last_name_input.text() == "رضایی"
    assert "تهران، ولیعصر" in _texts(dialog)


# ---- #11 Windows start, ✕, exit ---------------------------------------------------------------------
class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class FakeStore:
    def __init__(self):
        self.values = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def test_on_by_default_once():
    reg, store = FakeRegistry(), FakeStore()
    autostart.apply_default(store, reg, frozen=True)
    assert autostart.is_enabled(reg) and store.values["autostart_initialized"] is True


def test_turning_it_off_is_respected_after_that():
    reg, store = FakeRegistry(), FakeStore()
    autostart.apply_default(store, reg, frozen=True)
    autostart.set_enabled(False, reg)
    autostart.apply_default(store, reg, frozen=True)
    assert not autostart.is_enabled(reg)


def test_a_development_run_registers_nothing():
    reg, store = FakeRegistry(), FakeStore()
    autostart.apply_default(store, reg, frozen=False)
    assert not reg.values and "autostart_initialized" not in store.values


def test_autostart_is_a_per_user_key():
    assert autostart.RUN_KEY == r"Software\Microsoft\Windows\CurrentVersion\Run"
    source = autostart.WindowsRunKey.set.__code__.co_names
    assert "HKEY_CURRENT_USER" in source and "HKEY_LOCAL_MACHINE" not in source


def test_settings_page_can_turn_it_off_and_has_no_tray_opt_out(ui_context, admin_qapp):
    from app.ui.pages.settings import SettingsPage

    page = SettingsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert hasattr(page, "autostart_check") and not hasattr(page, "close_to_tray_check")


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args)


class _Notifier:
    def __init__(self, tray):
        self.tray = tray


class _Window:
    def __init__(self):
        self.hidden = False

    def hide(self):
        self.hidden = True


def _controller():
    from app.main import ShopAdminApp

    controller = ShopAdminApp.__new__(ShopAdminApp)
    controller.quit_calls = 0
    controller.quit_application = lambda: setattr(controller, "quit_calls",
                                                  controller.quit_calls + 1)
    return controller


def test_x_goes_to_the_tray_and_never_quits():
    controller = _controller()
    controller.notifier = _Notifier(_Tray())
    controller.main_window = _Window()
    controller._on_main_close()
    assert controller.main_window.hidden and controller.quit_calls == 0
    assert "خروج کامل" in controller.notifier.tray.messages[0][1]


@pytest.mark.parametrize("answer,quits", [(True, 1), (False, 0)])
def test_full_exit_asks_first(monkeypatch, answer, quits):
    from app.ui import widgets

    controller = _controller()
    asked = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: asked.append(a) or answer)
    controller._confirm_quit()
    assert asked and controller.quit_calls == quits


def test_the_tray_menu_is_wired_to_the_question():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "quit_requested.connect(self.quit_application)" not in source
    assert source.count("quit_requested.connect(self._confirm_quit)") == 2
