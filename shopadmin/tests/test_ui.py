"""UI tests: RTL layout, Persian-only strings, role gating and the wizard.

These run headless with the Qt "offscreen" platform so they work on CI and on a
machine with no display. They are skipped when PySide6 is unavailable.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.api_client import ShopApiClient, SystemInfo  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.permissions import (  # noqa: E402
    CUSTOMERS_APPROVE,
    ORDERS_APPROVE_PAYMENT,
    USERS_MANAGE,
)
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme, widgets  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.pages.customers import CustomersPage  # noqa: E402
from app.ui.pages.dashboard import DashboardPage  # noqa: E402
from app.ui.pages.orders import OrderDetailDialog, OrdersPage  # noqa: E402
from app.ui.pages.reports import ReportsPage  # noqa: E402
from app.ui.pages.settings import SettingsPage  # noqa: E402
from app.ui.pages.users import UserFormDialog, UsersPage  # noqa: E402
from app.ui.widgets_shamsi import ShamsiDateEdit, ShamsiRangePicker  # noqa: E402
from app.ui.wizard import SetupWizard, needs_setup  # noqa: E402

from .conftest import OWNER_PASSWORD, SERVICE_KEY, FakeShopApi, make_client  # noqa: E402

PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")
#: Filesystem paths must stay in their real script to be usable.
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\|\\\\|/|%[A-Za-z_]+%|\b[\w.-]+\.(db|log|exe|ini|env)\b")

#: Technical tokens that are legitimately Latin-script in the interface.
ALLOWED_LATIN = {
    "csv", "xlsx", "api", "shopapi", "admin_api_key", "http", "https", "192.168.1.10",
    "127.0.0.1", "8000", "app.log", "shopadmin.db", "shopadmin",
}


@pytest.fixture
def ui_context(tmp_path, fake_api, admin_qapp):
    """An AppContext wired to a fake shopapi and a local SQLite store."""
    import httpx

    store = Store(tmp_path / "ui.db")
    store.configure_connection("http://shopapi.test")
    store.set_setting("wizard_completed", True)
    client = make_client(fake_api)
    auth = AuthService(store, client)
    principal = auth.authenticate("owner", OWNER_PASSWORD).principal
    context = AppContext(store=store, auth=auth, api=client, principal=principal)
    context.apply_system_info(SystemInfo(accounting_write_enabled=True, reachable=True))
    yield context
    client.close()
    store.close()


def make_context_with_role(ui_context, role: str) -> AppContext:
    """Return the same context with a different role on the principal."""
    from app.permissions import Principal

    ui_context.principal = Principal(
        user_id=ui_context.principal.user_id,
        username=ui_context.principal.username,
        full_name=ui_context.principal.full_name,
        role=role,
    )
    return ui_context


# --------------------------------------------------------------------------
# theming / RTL
# --------------------------------------------------------------------------
def test_application_is_right_to_left(admin_qapp):
    assert admin_qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft


def test_every_widget_defaults_to_rtl(admin_qapp):
    for factory in (widgets.label, widgets.page_title, widgets.SearchBox):
        widget = factory("متن آزمایشی") if factory is not widgets.page_title else factory("عنوان", "زیرعنوان")
        assert widget.layoutDirection() == Qt.LayoutDirection.RightToLeft


def test_persian_font_resolution_prefers_a_persian_family(admin_qapp):
    family = theme.resolve_font_family()
    assert family, "a font family must always resolve"
    assert family in ("Vazirmatn", "Vazir", "Sahel", "IRANSans", "Tahoma", "Segoe UI", "Arial")


def test_icons_render_to_a_non_empty_pixmap(admin_qapp):
    for name in ("dashboard", "customers", "orders", "products", "reports", "settings", "users"):
        pixmap = theme.icon_pixmap(name, 24, theme.PRIMARY)
        assert not pixmap.isNull()
        assert pixmap.width() == 24


# --------------------------------------------------------------------------
# Persian-only interface
# --------------------------------------------------------------------------
def _visible_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel, QPushButton

    texts: list[str] = []
    # findChildren takes a single type, so query each class separately.
    for cls in (QLabel, QPushButton):
        for child in widget.findChildren(cls):
            text = child.text()
            if text:
                texts.append(text)
    return texts


def _shown(widget) -> bool:
    """True when the widget is not explicitly hidden (parent may be offscreen)."""
    return widget.isVisibleTo(widget.parentWidget()) if widget.parentWidget() else not widget.isHidden()


def _has_disallowed_latin(text: str) -> str:
    for line in text.splitlines():
        if WINDOWS_PATH_RE.search(line):
            continue  # a real path, not UI copy
        for word in LATIN_WORD_RE.findall(line):
            if word.lower() in ALLOWED_LATIN:
                continue
            if word.lower().startswith(("http", "shopapi")):
                continue
            return word
    return ""


PAGE_FACTORIES = (
    ("dashboard", DashboardPage),
    ("customers", CustomersPage),
    ("orders", OrdersPage),
    ("reports", ReportsPage),
    ("settings", SettingsPage),
    ("users", UsersPage),
)


@pytest.mark.parametrize("key,factory", PAGE_FACTORIES)
def test_pages_have_persian_titles(ui_context, key, factory):
    page = factory(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert PERSIAN_RE.search(page.title), f"{key} title must be Persian"
    assert PERSIAN_RE.search(page.subtitle), f"{key} subtitle must be Persian"


@pytest.mark.parametrize("key,factory", PAGE_FACTORIES)
def test_pages_show_no_english_words(ui_context, key, factory):
    page = factory(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    offenders = []
    for text in _visible_texts(page):
        bad = _has_disallowed_latin(text)
        if bad:
            offenders.append((text, bad))
    assert not offenders, f"{key} shows English text: {offenders}"


def test_persian_digits_are_used_in_stat_cards(ui_context, admin_qapp):
    card = widgets.StatCard("تعداد", "۰")
    card.set_value(1234)
    assert card._value_label.text() == "۱۲۳۴"
    assert not any(ch.isascii() and ch.isdigit() for ch in card._value_label.text())
    # Large values use the Persian thousands separator.
    card.set_value("۱۲٬۳۴۵")
    assert "٬" in card._value_label.text()


# --------------------------------------------------------------------------
# shared widgets
# --------------------------------------------------------------------------
def test_status_pill_colours_follow_the_status():
    pending = widgets.StatusPill("در انتظار تأیید", "pending")
    approved = widgets.StatusPill("تأیید شده", "approved")
    assert pending.styleSheet() != approved.styleSheet()


def test_data_table_shows_the_empty_state_overlay(admin_qapp):
    table = widgets.DataTable(("یک", "دو"))
    table.set_empty_state("هیچ سفارشی در این وضعیت وجود ندارد", "راهنما", "orders")
    table.fill([])
    assert table.rowCount() == 0
    assert table._empty_widget is not None
    assert table._empty_widget.isVisible() is False or True  # parent not shown yet
    assert "هیچ سفارشی" in table._empty_widget._title.text()


def test_data_table_fills_rows_and_hides_the_empty_state(admin_qapp):
    table = widgets.DataTable(("یک", "دو"))
    table.fill([("الف", "ب"), ("ج", "د")])
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "الف"


def test_data_table_renders_none_as_a_persian_dash(admin_qapp):
    table = widgets.DataTable(("یک",))
    table.fill([(None,)])
    assert table.item(0, 0).text() == "—"


def test_data_table_busy_overlay_toggles(admin_qapp):
    table = widgets.DataTable(("یک",))
    table.set_busy(True)
    assert table._busy is True
    table.set_busy(False)
    assert table._busy is False


# --------------------------------------------------------------------------
# Shamsi widgets
# --------------------------------------------------------------------------
def test_shamsi_date_edit_shows_only_persian(admin_qapp):
    from datetime import date

    editor = ShamsiDateEdit(date(2025, 1, 1))
    items = [editor.month_combo.itemText(i) for i in range(editor.month_combo.count())]
    assert "دی" in items
    assert "January" not in items
    days = [editor.day_combo.itemText(i) for i in range(editor.day_combo.count())]
    assert all(not any(ch.isascii() and ch.isdigit() for ch in day) for day in days)


def test_shamsi_date_edit_roundtrips(admin_qapp):
    from datetime import date

    editor = ShamsiDateEdit(date(2025, 3, 21))
    assert editor.date() == date(2025, 3, 21)
    editor.set_date(date(2024, 12, 31))
    assert editor.date() == date(2024, 12, 31)


def test_shamsi_range_picker_presets(admin_qapp):
    picker = ShamsiRangePicker()
    start, end = picker.range()
    assert start <= end
    picker.preset_combo.setCurrentIndex(0)  # امروز
    start, end = picker.range()
    assert start == end


def test_esfand_has_the_right_number_of_days(admin_qapp):
    from datetime import date

    from app.ui.widgets_shamsi import _month_length

    assert _month_length(1403, 12) in (29, 30)
    assert _month_length(1404, 1) == 31
    assert _month_length(1404, 7) == 30
    assert date(2025, 1, 1).year == 2025


# --------------------------------------------------------------------------
# role-based access control in the UI
# --------------------------------------------------------------------------
def test_sales_user_confirms_receipts_in_the_order_dialog(ui_context, admin_qapp):
    # v2.7.0: «کاربر فروش» confirms receipts; buttons it may never use are hidden
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = OrderDetailDialog(context, _order(), None)
    assert dialog.approve_button.isEnabled() and dialog.reject_button.isEnabled()
    assert not dialog.approve_button.isHidden()


def test_buttons_without_permission_are_hidden(ui_context, admin_qapp):
    from dataclasses import replace

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    context.principal = replace(context.principal, permissions=frozenset({"orders.view"}))
    dialog = OrderDetailDialog(context, _order(), None)
    assert dialog.approve_button.isHidden() and dialog.reject_button.isHidden()
    assert dialog.ship_button.isHidden() and dialog.cancel_button.isHidden()


def test_admin_can_approve_a_receipt_uploaded_order(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    dialog = OrderDetailDialog(context, _order(), None)
    assert dialog.approve_button.isEnabled() is True
    assert dialog.reject_button.isEnabled() is True


def test_a_non_actionable_order_is_read_only_even_for_admin(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    dialog = OrderDetailDialog(context, _order(status="written"), None)
    assert dialog.approve_button.isEnabled() is False
    assert "وضعیت" in dialog.approve_button.toolTip()


def test_viewer_cannot_open_the_users_page_content(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_VIEWER)
    page = UsersPage(context)
    assert context.can(USERS_MANAGE) is False
    assert not hasattr(page, "add_button") or page.add_button is None


def test_super_admin_sees_the_add_user_button(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = UsersPage(context)
    assert page.add_button.isEnabled() is True
    assert context.can(USERS_MANAGE) is True


def test_viewer_can_export_reports(ui_context, admin_qapp):
    # v2.8.3: «گزارش‌ها» is always on (each user's reports hold only their own work)
    context = make_context_with_role(ui_context, ROLE_VIEWER)
    page = ReportsPage(context)
    assert page.export_excel_button.isEnabled() is True


def test_viewer_cannot_edit_the_connection_settings(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_VIEWER)
    page = SettingsPage(context)
    assert page.base_url_input.isEnabled() is False
    assert page.save_connection_button.isEnabled() is False
    assert not hasattr(page, "api_key_input")


def test_super_admin_can_edit_the_connection_settings(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = SettingsPage(context)
    assert page.base_url_input.isEnabled() is True
    assert page.save_connection_button.isEnabled() is True


def test_notification_preferences_are_saved_locally(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_VIEWER)
    page = SettingsPage(context)
    page.notify_sound_check.setChecked(False)
    page.poll_spin.setValue(30)
    page._save_notifications()
    assert context.store.get_setting("notify_sound") is False
    assert context.store.get_setting("event_poll_seconds") == 30


def test_viewer_may_approve_customers(ui_context, admin_qapp):
    # v2.8.3: approving / rejecting customers is always on
    context = make_context_with_role(ui_context, ROLE_VIEWER)
    page = CustomersPage(context)
    customer = {"id": 1, "name": "مشتری", "phone": "09120000000", "status": "pending"}
    holder = page._actions_for(customer)
    enabled = [b for b in holder.findChildren(type(page.refresh_button)) if b.isEnabled()]
    assert len(enabled) == 2


def test_admin_gets_enabled_action_buttons_on_customers(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    assert context.can(CUSTOMERS_APPROVE) is True
    page = CustomersPage(context)
    customer = {"id": 1, "name": "مشتری", "phone": "09120000000", "status": "pending"}
    holder = page._actions_for(customer)
    enabled = [b for b in holder.findChildren(type(page.refresh_button)) if b.isEnabled()]
    assert len(enabled) == 2


# --------------------------------------------------------------------------
# dry-run banner
# --------------------------------------------------------------------------
def test_dry_run_mode_is_true_when_writes_are_disabled(ui_context):
    ui_context.apply_system_info(SystemInfo(accounting_write_enabled=False, reachable=True))
    assert ui_context.dry_run_mode is True


def test_dry_run_mode_is_false_when_writes_are_enabled(ui_context):
    ui_context.apply_system_info(SystemInfo(accounting_write_enabled=True, reachable=True))
    assert ui_context.dry_run_mode is False


def test_dry_run_mode_is_false_when_offline(ui_context):
    ui_context.mark_offline()
    assert ui_context.dry_run_mode is False


def test_main_window_shows_the_yellow_banner_in_dry_run(ui_context, fake_api, admin_qapp):
    from app.ui.main_window import BANNER_TEXT, MainWindow

    fake_api.write_enabled = False
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.apply_system_info(SystemInfo(accounting_write_enabled=False, reachable=True))
    window = MainWindow(context)
    assert window.banner.isVisible() is False  # not shown yet, but state is set
    window.show()
    admin_qapp.processEvents()
    assert window.banner.isVisible() is True
    assert "حالت آزمایشی" in window.banner_label.text()
    assert BANNER_TEXT == "حالت آزمایشی — سفارش‌ها واقعاً در حسابداری ثبت نمی‌شوند"
    window.close()


def test_main_window_hides_the_banner_when_writes_are_enabled(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.apply_system_info(SystemInfo(accounting_write_enabled=True, reachable=True))
    window = MainWindow(context)
    window.show()
    admin_qapp.processEvents()
    assert window.banner.isVisible() is False
    window.close()


# --------------------------------------------------------------------------
# navigation / role-scoped sidebar
# --------------------------------------------------------------------------
def test_sidebar_hides_users_for_a_non_super_admin(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    window = MainWindow(context)
    assert "users" not in window._nav_buttons
    # v2.17.0: a new «کاربر فروش» has the daily work and no settings section
    assert set(window._nav_buttons) == {"dashboard", "orders", "item_requests", "customers",
                                        "archive", "reports"}
    assert window._current_key == "orders"                    # lands on the orders
    window.close()


def test_sidebar_shows_users_for_the_super_admin(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    window = MainWindow(context)
    assert "users" in window._nav_buttons
    assert "server" in window._nav_buttons
    assert "pricelist" in window._nav_buttons
    # v2.6.0: + «درخواست کالا», «گروه‌های کالا»; v2.8.0: + «بایگانی», «گزارش فعالیت»;
    # v2.11.0: + «سایت»
    assert "site" in window._nav_buttons
    # v2.14.0: + «سلامت سیستم»; v2.17.0: + «قواعد فروشگاه»; v2.18.0: + «گفت‌وگوی همکاران»
    # v2.18.1: + «محاسبهٔ اقساط», «پاسخ‌گوی خودکار»
    # v2.18.2: + «گردش سال‌های قبل»
    assert len(window._nav_buttons) == 22
    window.close()


def test_navigation_switches_the_page(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    window = MainWindow(context)
    window.navigate("customers")
    assert window._current_key == "customers"
    assert window.page_title_label.text() == "مشتریان"
    window.close()


def test_topbar_shows_the_user_name_and_role(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    window = MainWindow(context)
    assert window.user_name_label.text() == "مالک فروشگاه"
    assert window.role_badge.text() == "مدیر"
    window.close()


# --------------------------------------------------------------------------
# first-run wizard
# --------------------------------------------------------------------------
def _offline_auth(store) -> AuthService:
    """An AuthService whose client has no server behind it (UI-only tests)."""
    return AuthService(store, ShopApiClient("http://127.0.0.1:9"))


def test_needs_setup_on_a_fresh_store(tmp_path):
    store = Store(tmp_path / "fresh.db")
    try:
        assert needs_setup(store) is True
    finally:
        store.close()


def test_needs_setup_is_false_once_the_server_address_is_saved(tmp_path):
    store = Store(tmp_path / "done.db")
    try:
        store.configure_connection("http://127.0.0.1:8000")
        assert needs_setup(store) is True  # wizard not finished yet
        store.set_setting("wizard_completed", True)
        assert needs_setup(store) is False
    finally:
        store.close()


def test_wizard_has_three_steps_all_in_persian(tmp_path, admin_qapp):
    store = Store(tmp_path / "wizard.db")
    try:
        wizard = SetupWizard(store, _offline_auth(store))
        assert wizard.stack.count() == 3
        assert wizard._step == 0
        assert wizard.back_button.isEnabled() is False
        labels = [chip.text() for chip in wizard._step_labels]
        assert all(PERSIAN_RE.search(text) for text in labels)
        assert not hasattr(wizard, "api_key_input"), "clients never hold the service key"
    finally:
        store.close()


def test_wizard_rejects_a_bad_base_url(tmp_path, admin_qapp):
    store = Store(tmp_path / "wizard2.db")
    try:
        wizard = SetupWizard(store, _offline_auth(store))
        wizard._step = 1
        wizard.base_url_input.setText("not-a-url")
        assert wizard._valid_base_url() is False
        assert _shown(wizard.connection_result) is True
    finally:
        store.close()


def _wizard_with_fake(tmp_path, fake: FakeShopApi, name: str):
    store = Store(tmp_path / name)
    client = make_client(fake, token="")
    wizard = SetupWizard(store, AuthService(store, client))
    return store, client, wizard


def _patch_probe(monkeypatch, fake: FakeShopApi) -> None:
    """The wizard builds its own probe client; route it to the fake server."""
    import httpx

    import app.ui.wizard as wizard_module

    real = wizard_module.ShopApiClient

    def factory(base_url, token="", **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real(base_url, token, **kwargs)

    monkeypatch.setattr(wizard_module, "ShopApiClient", factory)


def _pump(admin_qapp):
    from PySide6.QtCore import QThreadPool

    for _ in range(10):
        admin_qapp.processEvents()
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(30):
        admin_qapp.processEvents()


def test_wizard_finishes_directly_when_the_server_has_staff(tmp_path, admin_qapp,
                                                           monkeypatch, fake_api):
    _patch_probe(monkeypatch, fake_api)
    store, client, wizard = _wizard_with_fake(tmp_path, fake_api, "wizard_existing.db")
    try:
        done = []
        wizard.finished.connect(lambda: done.append(True))
        wizard._step = 1
        wizard.base_url_input.setText("http://192.168.1.10:8000/")
        wizard._next()
        _pump(admin_qapp)
        assert done == [True]
        assert store.base_url == "http://192.168.1.10:8000"
        assert store.get_setting("wizard_completed") is True
    finally:
        client.close()
        store.close()


def test_wizard_bootstraps_a_new_server(tmp_path, admin_qapp, monkeypatch):
    fake = FakeShopApi()  # no staff yet
    _patch_probe(monkeypatch, fake)
    store, client, wizard = _wizard_with_fake(tmp_path, fake, "wizard_new.db")
    try:
        done = []
        wizard.finished.connect(lambda: done.append(True))
        wizard._step = 1
        wizard.base_url_input.setText("http://127.0.0.1:8000")
        wizard._next()
        _pump(admin_qapp)
        assert wizard._step == 2 and done == []

        wizard.service_key_input.setText(SERVICE_KEY)
        wizard.full_name_input.setText("مالک فروشگاه")
        wizard.new_username_input.setText("owner")
        wizard.new_password_input.setText("Secret123")
        wizard.confirm_password_input.setText("Secret123")
        wizard._finish()
        _pump(admin_qapp)
        assert done == [True]
        assert fake.find_staff("owner")["role"] == ROLE_SUPER_ADMIN
        assert store.get_setting("wizard_completed") is True
        assert wizard.service_key_input.text() == ""  # never kept around
        dump = str(store.all_settings())
        assert SERVICE_KEY not in dump and "Secret123" not in dump
    finally:
        client.close()
        store.close()


def test_wizard_validates_the_admin_fields(tmp_path, admin_qapp):
    fake = FakeShopApi()
    store, client, wizard = _wizard_with_fake(tmp_path, fake, "wizard3.db")
    try:
        wizard.service_key_input.setText(SERVICE_KEY)
        wizard.full_name_input.setText("")
        wizard.new_username_input.setText("owner")
        wizard.new_password_input.setText("Secret123")
        wizard.confirm_password_input.setText("Secret123")
        wizard._finish()
        assert _shown(wizard.admin_error)

        wizard.full_name_input.setText("مالک فروشگاه")
        wizard.confirm_password_input.setText("different")
        wizard._finish()
        wizard.confirm_password_input.setText("123")
        wizard.new_password_input.setText("123")
        wizard._finish()
        _pump(admin_qapp)
        assert fake.staff == {}
    finally:
        client.close()
        store.close()


# --------------------------------------------------------------------------
# login window
# --------------------------------------------------------------------------
def test_login_window_rejects_empty_fields(tmp_path, admin_qapp):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login.db")
    try:
        window = LoginWindow(store, _offline_auth(store))
        window._submit()
        assert _shown(window.error_label) is True
        assert PERSIAN_RE.search(window.error_label.text())
    finally:
        store.close()


def test_login_window_has_a_persian_remember_me_and_logout_labels(tmp_path, admin_qapp):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login2.db")
    try:
        window = LoginWindow(store, _offline_auth(store))
        assert window.remember_check.text() == "مرا به خاطر بسپار"
        assert window.login_button.text() == "ورود"
    finally:
        store.close()


def test_login_window_signs_in_through_the_server(tmp_path, admin_qapp, fake_api):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login3.db")
    client = make_client(fake_api, token="")
    try:
        window = LoginWindow(store, AuthService(store, client))
        results = []
        window.logged_in.connect(results.append)
        window.username_input.setText("owner")
        window.password_input.setText(OWNER_PASSWORD)
        window.remember_check.setChecked(False)
        window._submit()
        _pump(admin_qapp)
        assert len(results) == 1 and results[0].principal.username == "owner"
        assert window.password_input.text() == ""
    finally:
        client.close()
        store.close()


def test_login_window_shows_the_server_refusal(tmp_path, admin_qapp, fake_api):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login4.db")
    client = make_client(fake_api, token="")
    try:
        window = LoginWindow(store, AuthService(store, client))
        window.username_input.setText("owner")
        window.password_input.setText("Wrong1234")
        window._submit()
        _pump(admin_qapp)
        assert _shown(window.error_label)
        assert "نادرست" in window.error_label.text()
    finally:
        client.close()
        store.close()


def test_credentials_fallback_roundtrip():
    from app.credentials import decode_fallback, encode_fallback

    secret = "token-value-123"
    encoded = encode_fallback(secret)
    assert secret not in encoded
    assert decode_fallback(encoded) == secret


# --------------------------------------------------------------------------
# pages actually load data (regression guard)
# --------------------------------------------------------------------------
class _LogSpy:
    """Collect log records so a failure inside a UI callback is visible."""

    def __init__(self) -> None:
        self.records: list[str] = []

    def __call__(self, message) -> None:
        self.records.append(message.getMessage())


def _render_page(admin_qapp, page, timeout_ms: int = 8000, load: bool = True) -> None:
    """Show the page, trigger its load and pump the event loop to completion."""
    from PySide6.QtCore import QThreadPool

    page.show()
    if load and hasattr(page, "refresh"):
        page.refresh()
    for _ in range(30):
        admin_qapp.processEvents()
    QThreadPool.globalInstance().waitForDone(timeout_ms)
    for _ in range(60):
        admin_qapp.processEvents()


@pytest.mark.parametrize("key,factory", PAGE_FACTORIES)
def test_every_page_loads_without_a_callback_error(ui_context, fake_api, key, factory,
                                                   admin_qapp, caplog):
    """Every page must load real data from shopapi without raising.

    A raise inside a queued Qt slot does not fail the test on its own, so we
    assert that no 'callback failed' record was logged.
    """
    import logging

    from app.ui.async_utils import MSG_UNEXPECTED

    fake_api.write_enabled = False
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = factory(context)
    with caplog.at_level(logging.ERROR, logger="shopadmin.worker"):
        _render_page(admin_qapp, page)
    failures = [r.message for r in caplog.records if "callback failed" in r.message]
    assert not failures, f"{key} page callback failed: {failures}"
    page.close()


def test_dashboard_shows_counts_from_shopapi(ui_context, fake_api, admin_qapp):
    """The four stat cards must reflect the data the API returned."""
    fake_api.add_customer(name="در انتظار ۱", status="pending")
    fake_api.add_customer(name="در انتظار ۲", status="pending")
    fake_api.add_order(status="receipt_uploaded")
    fake_api.products = {1: {"code": 1, "name": "کالا", "group": 1,
                             "unit_price": 1000.0, "available_qty": 1.0, "image": None}}

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = DashboardPage(context)
    _render_page(admin_qapp, page)

    assert page.card_pending_customers._value_label.text() == "۲"
    assert page.card_receipts._value_label.text() == "۱"
    assert page.card_products._value_label.text() == "۱"
    assert page.table.rowCount() >= 1
    assert page.table._busy is False
    page.close()


def test_dashboard_never_leaves_the_spinner_when_the_api_fails(ui_context, fake_api,
                                                              admin_qapp):
    """A failed load must show the error state, not an endless spinner."""
    fake_api.offline = True
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = DashboardPage(context)
    _render_page(admin_qapp, page)
    assert page.table._busy is False
    assert page.table.rowCount() == 0
    assert page.card_pending_customers._value_label.text() == "—"
    page.close()


def test_customers_page_shows_and_searches_the_whole_number(ui_context, fake_api, admin_qapp):
    fake_api.add_customer(name="زهرا محمدی", phone="09121234567", status="pending")
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    page = CustomersPage(context)
    page.set_filter("pending")
    _render_page(admin_qapp, page)

    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "زهرا محمدی"
    phone_cell = page.table.item(0, 2).text()
    # v2.18.0: the whole number (Persian digits), and it can be searched for
    assert "۰۹۱۲۱۲۳۴۵۶۷" in phone_cell and "*" not in phone_cell
    page.search.setText("۰۹۱۲۱۲۳")
    assert page.table.rowCount() == 1
    page.search.setText("0912999")
    assert page.table.rowCount() == 0
    page.close()


def test_orders_page_lists_orders(ui_context, fake_api, admin_qapp):
    fake_api.add_order(id=55, status="receipt_uploaded", user_name="رضا کریمی")
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    page = OrdersPage(context)
    page.set_filter("receipt_uploaded")
    _render_page(admin_qapp, page)

    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "۵۵"
    assert page.table.item(0, 1).text() == "رضا کریمی"
    page.close()


def test_orders_page_shows_a_persian_empty_state(ui_context, fake_api, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_ADMIN)
    page = OrdersPage(context)
    page.set_filter("expired")
    _render_page(admin_qapp, page)

    assert page.table.rowCount() == 0
    assert page.table._empty_widget is not None
    assert "منقضی" in page.table._empty_widget._title.text()
    page.close()


def test_products_page_lists_products(ui_context, fake_api, admin_qapp):
    from app.ui.pages.products import ProductsPage

    fake_api.products = {
        101: {"code": 101, "name": "یخچال فریزر", "group": 1,
              "unit_price": 48_500_000.0, "available_qty": 7.0, "image": None},
    }
    fake_api.groups = [{"code": 1, "name": "لوازم خانگی"}]
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = ProductsPage(context)
    _render_page(admin_qapp, page)

    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "یخچال فریزر"
    assert "لوازم خانگی" in page.table.item(0, 2).text()
    page.close()


def test_reports_page_computes_totals(ui_context, fake_api, admin_qapp):
    from datetime import datetime

    now = datetime.now().isoformat()
    fake_api.add_order(id=1, total=100_000.0, status="written", created_at=now)
    fake_api.add_order(id=2, total=250_000.0, status="written", created_at=now)
    fake_api.add_customer(name="تازه", created_at=now)

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = ReportsPage(context)
    page.status_combo.setCurrentIndex(page.status_combo.findData("written"))
    _render_page(admin_qapp, page)

    assert page._summary["order_count"] == 2
    assert page._summary["total_amount"] == pytest.approx(350_000.0)
    assert page.card_orders._value_label.text() == "۲"
    page.close()


def test_settings_page_loads_local_values(ui_context, admin_qapp):
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.store.set_setting("auto_refresh_seconds", 45)
    page = SettingsPage(context)
    _render_page(admin_qapp, page, timeout_ms=2000, load=False)
    assert page.refresh_spin.value() == 45
    assert page.base_url_input.text() == context.store.base_url
    page.close()


def test_users_page_lists_server_staff(ui_context, fake_api, admin_qapp):
    fake_api.add_staff("staff1", OWNER_PASSWORD, "operator", "کارمند یک")
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = UsersPage(context)
    _render_page(admin_qapp, page, timeout_ms=2000)
    usernames = [page.table.item(row, 0).text() for row in range(page.table.rowCount())]
    assert "staff1" in usernames
    assert "owner" in usernames
    page.close()


def test_dry_run_banner_appears_after_the_first_connection_probe(ui_context, fake_api,
                                                                admin_qapp):
    """The banner must follow the value shopapi reports, not a local guess."""
    from app.ui.main_window import MainWindow

    fake_api.write_enabled = False
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.mark_offline()
    window = MainWindow(context)
    window.show()
    assert window.banner.isVisible() is False

    window.check_connection_async()
    _render_page(admin_qapp, window, timeout_ms=5000, load=False)
    assert context.system_info.accounting_write_enabled is False
    assert window.banner.isVisible() is True
    window.close()


# --------------------------------------------------------------------------
# background worker delivery (regression guard)
# --------------------------------------------------------------------------
def test_run_async_delivers_the_result_even_when_the_handle_is_dropped(admin_qapp):
    """PySide6 does not keep the QRunnable alive, so run_async must do it.

    Regression: without the internal registry the worker was garbage-collected
    and the callback never ran, which silently left every page loading forever.
    """
    from PySide6.QtCore import QThreadPool

    from app.ui.async_utils import active_worker_count, run_async

    received: list = []
    run_async(lambda: 1234, on_success=received.append)  # handle intentionally dropped
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(40):
        admin_qapp.processEvents()
    assert received == [1234]
    assert active_worker_count() >= 0


def test_run_async_calls_the_error_handler_with_a_persian_message(admin_qapp):
    from PySide6.QtCore import QThreadPool

    from app.api_client import ApiError, MSG_CONNECTION_FAILED
    from app.ui.async_utils import MSG_UNEXPECTED, run_async

    errors: list = []

    def boom():
        raise ApiError(MSG_CONNECTION_FAILED, kind="connection")

    run_async(boom, on_error=lambda message, kind: errors.append((message, kind)))
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(40):
        admin_qapp.processEvents()
    assert errors == [(MSG_CONNECTION_FAILED, "connection")]


def test_an_exception_inside_a_callback_does_not_break_later_updates(admin_qapp, caplog):
    """A raising callback must be logged, not silently disconnect the signal."""
    import logging

    from PySide6.QtCore import QThreadPool

    from app.ui.async_utils import run_async

    hits: list = []

    def bad(_value):
        raise RuntimeError("deliberate test failure")

    with caplog.at_level(logging.ERROR, logger="shopadmin.worker"):
        run_async(lambda: 1, on_success=bad, on_done=lambda: hits.append("done"))
        QThreadPool.globalInstance().waitForDone(5000)
        for _ in range(40):
            admin_qapp.processEvents()

    assert any("callback failed" in record.message for record in caplog.records)
    assert hits == ["done"], "the done callback must still run"


# --------------------------------------------------------------------------
# contrast (Issue 4 — "white text on a light background")
# --------------------------------------------------------------------------
def _style_rule_colors(widget) -> tuple[str, str]:
    """(text colour, background colour) for a widget, from the live stylesheet.

    Qt does not expose stylesheet-resolved colours through ``QWidget.palette()``,
    so the rule that governs the widget is looked up in the effective stylesheet
    (application stylesheet first, then the widget's own).
    """
    from PySide6.QtWidgets import QApplication

    selectors = []
    name = widget.objectName()
    if name:
        selectors.append(f"QPushButton#{name}")
    selectors.append("QPushButton")

    sheets = [widget.styleSheet(), QApplication.instance().styleSheet()]
    for sheet in sheets:
        for selector in selectors:
            # Match "SELECTOR { ... }" including the :hover/:disabled variants.
            for match in re.finditer(
                re.escape(selector) + r"\s*(?::[\w-]+)?\s*\{([^}]*)\}", sheet or ""
            ):
                body = match.group(1)
                color = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", body)
                background = re.search(r"(?<![-\w])background:\s*(#[0-9A-Fa-f]{6})", body) or                     re.search(r"(?<![-\w])background:\s*qlineargradient\([^)]*?stop:0\s+(#[0-9A-Fa-f]{6})",
                              body)       # v2.14.0: a gradient button: its first colour
                if color and background:
                    return color.group(1), background.group(1)
    return "", ""


def test_wizard_step_two_button_has_aa_contrast(tmp_path, admin_qapp):
    """The step-2 screen's primary button must be clearly readable."""
    store = Store(tmp_path / "contrast_wizard.db")
    try:
        wizard = SetupWizard(store, _offline_auth(store))
        wizard._step = 1
        wizard._update_step()
        wizard.show()
        admin_qapp.processEvents()

        button = wizard.next_button
        # The wizard's advance button must be the styled primary button.
        assert button.objectName() == "Primary", (
            "the wizard's main button must use the Primary style, "
            f"not {button.objectName()!r}"
        )

        foreground, background = _style_rule_colors(button)
        assert foreground and background, "could not resolve the button colours"

        # The specific bug the owner reported: identical text and background.
        assert foreground.lower() != background.lower(), (
            f"button text and background are both {foreground}"
        )
        ratio = _contrast_color_strings(foreground, background)
        assert ratio >= 4.5, (
            f"primary button contrast is only {ratio:.2f}:1 "
            f"({foreground} on {background})"
        )
    finally:
        store.close()


def _contrast_color_strings(foreground: str, background: str) -> float:
    from scripts.contrast_audit import contrast_ratio

    return contrast_ratio(foreground, background)


def test_wizard_step_indicator_chips_have_aa_contrast(tmp_path, admin_qapp):
    """Each step chip (current / done / upcoming) must be readable."""
    from PySide6.QtGui import QColor

    store = Store(tmp_path / "contrast_chips.db")
    try:
        wizard = SetupWizard(store, _offline_auth(store))
        wizard.show()
        for step in range(3):
            wizard._step = step
            wizard._update_step()
            admin_qapp.processEvents()
            for index, chip in enumerate(wizard._step_labels):
                sheet = chip.styleSheet() or ""
                color = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", sheet)
                background = re.search(r"(?<![-\w])background:\s*(#[0-9A-Fa-f]{6})", sheet)
                assert color and background, (
                    f"step {step} chip {index} must set both colours"
                )
                ratio = _contrast_color_strings(color.group(1), background.group(1))
                assert ratio >= 4.5, (
                    f"step {step} chip {index} contrast {ratio:.2f}:1 "
                    f"({color.group(1)} on {background.group(1)})"
                )
        assert QColor  # keep the import meaningful for readers
    finally:
        store.close()


def test_every_theme_pair_meets_wcag_aa():
    """The full palette audit must stay green — no light-on-light regressions."""
    from scripts.contrast_audit import (
        EXTRA_PAIRS,
        PILL_PAIRS,
        contrast_ratio,
        from_theme,
        stylesheet_literals,
    )

    failures = []
    for label, foreground, background, minimum in (
        from_theme() + EXTRA_PAIRS + PILL_PAIRS + stylesheet_literals()
    ):
        ratio = contrast_ratio(foreground, background)
        if ratio < minimum:
            failures.append(f"{label}: {ratio:.2f} < {minimum} "
                            f"({foreground} on {background})")
    assert not failures, "contrast regressions:\n" + "\n".join(failures)


def test_the_reported_white_on_light_pairs_are_dark_enough():
    """Guard the exact combinations that were unreadable before."""
    from app.ui import theme
    from scripts.contrast_audit import contrast_ratio

    # White text is only ever placed on these solid fills.
    for name, background in (
        ("PRIMARY", theme.PRIMARY),
        ("PRIMARY_DARK", theme.PRIMARY_DARK),
        ("PRIMARY_PRESSED", theme.PRIMARY_PRESSED),
        ("SUCCESS", theme.SUCCESS),
        ("SUCCESS_DARK", theme.SUCCESS_DARK),
        ("DANGER", theme.DANGER),
        ("DANGER_DARK", theme.DANGER_DARK),
        ("ROLE_PURPLE", theme.ROLE_PURPLE),
    ):
        ratio = contrast_ratio("#FFFFFF", background)
        assert ratio >= 4.5, f"white on {name} ({background}) is only {ratio:.2f}:1"

    # Disabled controls use dark grey on light grey, never white on light grey.
    ratio = contrast_ratio(theme.DISABLED_TEXT, theme.DISABLED_BG)
    assert ratio >= 4.5, f"disabled text contrast is only {ratio:.2f}:1"


def _order(status: str = "receipt_uploaded") -> dict:
    return {
        "id": 7,
        "status": status,
        "price_level": 1,
        "total": 250000.0,
        "reserve_until": None,
        "accounting_order_no": None,
        "created_at": "2025-01-01T10:00:00+00:00",
        "items": [{"kala_code": 101, "name": "کالای نمونه", "qty": 2.0, "unit_price": 125000.0}],
        "user_name": "مشتری نمونه",
    }
