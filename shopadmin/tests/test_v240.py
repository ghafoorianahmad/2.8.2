"""v2.4.0: remember-me checkmark, forgot password, reset to 12345, server edition."""
from __future__ import annotations

import pytest

from app import edition
from app.auth import AuthError, AuthService
from app.permissions import PASSWORDS_DECIDE, has_permission
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER
from app.store import Store

from .conftest import OWNER_PASSWORD, SERVICE_KEY, make_client
from .test_ui import _pump, make_context_with_role, ui_context  # noqa: F401


# ---- remember-me checkbox shows its state --------------------------------------------
def _indicator_stats(image):
    """(blue pixels, white pixels inside the blue square's bounding box)."""
    from app.ui import theme
    from PySide6.QtGui import QColor

    blue = QColor(theme.PRIMARY_DARK)
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if abs(c.red() - blue.red()) < 12 and abs(c.green() - blue.green()) < 12 \
                    and abs(c.blue() - blue.blue()) < 12:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0, 0
    white = 0
    for y in range(min(ys), max(ys) + 1):
        for x in range(min(xs), max(xs) + 1):
            c = image.pixelColor(x, y)
            if c.red() > 235 and c.green() > 235 and c.blue() > 235:
                white += 1
    return len(xs), white


def test_checked_checkbox_draws_a_visible_checkmark(admin_qapp):
    from PySide6.QtWidgets import QCheckBox

    from app.ui import theme

    # Qt style sheets cannot load data: URIs, so the glyph must be a real file.
    import re
    from pathlib import Path

    match = re.search(r'QCheckBox::indicator:checked \{[^}]*image: url\("([^"]+)"\)',
                      theme.stylesheet())
    assert match and Path(match.group(1)).is_file()

    checked, unchecked = QCheckBox("مرا به خاطر بسپار"), QCheckBox("مرا به خاطر بسپار")
    checked.setChecked(True)
    for box in (checked, unchecked):
        box.show()
        admin_qapp.processEvents()
    blue_on, white_on = _indicator_stats(checked.grab().toImage())
    blue_off, _ = _indicator_stats(unchecked.grab().toImage())
    assert blue_off == 0                 # unticked: no blue fill
    assert blue_on > 100                 # ticked: filled square ...
    assert white_on >= 15                # ... with a white checkmark inside
    checked.close()
    unchecked.close()


# ---- forgot password ---------------------------------------------------------------
@pytest.fixture
def anon_auth(store, fake_api):
    client = make_client(fake_api, token="")
    yield AuthService(store, client)
    client.close()


def test_forgot_flow_end_to_end(anon_auth, fake_api):
    fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    request = anon_auth.request_password_reset("sara")
    rid, token = request["request_id"], request["token"]
    assert anon_auth.password_request_status(rid, token) == "pending"
    with pytest.raises(AuthError):
        anon_auth.complete_password_reset(rid, token, "Brandnew99", "Brandnew99")  # not approved

    admin = AuthService(anon_auth.store, make_client(fake_api))   # the owner approves
    pending = admin.list_password_requests()
    assert [p["username"] for p in pending] == ["sara"]
    admin.decide_password_request(pending[0]["id"], True)
    assert anon_auth.password_request_status(rid, token) == "approved"

    with pytest.raises(AuthError):
        anon_auth.complete_password_reset(rid, token, "Brandnew99", "Different99")
    with pytest.raises(AuthError):
        anon_auth.complete_password_reset(rid, token, "short", "short")
    anon_auth.complete_password_reset(rid, token, "Brandnew99", "Brandnew99")
    with pytest.raises(AuthError):
        anon_auth.authenticate("sara", "Oldpass123")                 # old one is dead
    assert anon_auth.authenticate("sara", "Brandnew99").principal.username == "sara"


def test_forgot_rejected_request(anon_auth, fake_api):
    fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    request = anon_auth.request_password_reset("sara")
    admin = AuthService(anon_auth.store, make_client(fake_api))
    admin.decide_password_request(admin.list_password_requests()[0]["id"], False)
    assert anon_auth.password_request_status(request["request_id"], request["token"]) == "rejected"


def test_forgot_validates_the_username_locally(anon_auth):
    with pytest.raises(AuthError):
        anon_auth.request_password_reset("a")


def test_passwords_decide_permission():
    assert has_permission(ROLE_ADMIN, PASSWORDS_DECIDE)
    assert has_permission(ROLE_SUPER_ADMIN, PASSWORDS_DECIDE)
    assert not has_permission(ROLE_OPERATOR, PASSWORDS_DECIDE)
    assert not has_permission(ROLE_VIEWER, PASSWORDS_DECIDE)


def test_forgot_dialog_walks_through_the_states(tmp_path, admin_qapp, fake_api):
    from app.ui.forgot_dialog import PAGE_ASK, PAGE_NEW, PAGE_WAIT, ForgotPasswordDialog

    fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    store = Store(tmp_path / "forgot.db")
    client = make_client(fake_api, token="")
    try:
        dialog = ForgotPasswordDialog(AuthService(store, client), "sara")
        assert dialog.stack.currentIndex() == PAGE_ASK
        dialog._send_request()
        _pump(admin_qapp)
        assert dialog.stack.currentIndex() == PAGE_WAIT
        dialog._poll()
        _pump(admin_qapp)
        assert dialog.stack.currentIndex() == PAGE_WAIT          # nobody approved yet
        fake_api.pw_requests[1]["status"] = "approved"
        dialog._poll()
        _pump(admin_qapp)
        assert dialog.stack.currentIndex() == PAGE_NEW
        dialog.password_input.setText("Brandnew99")
        dialog.confirm_input.setText("Brandnew99")
        dialog._complete()
        _pump(admin_qapp)
        assert dialog.completed
        assert fake_api.find_staff("sara")["password"] == "Brandnew99"
        assert dialog.password_input.text() == ""                # nothing left on screen
    finally:
        dialog.close()
        client.close()
        store.close()


def test_login_window_has_a_forgot_button(tmp_path, admin_qapp, fake_api):
    from app.ui.login_window import LoginWindow

    store = Store(tmp_path / "login_forgot.db")
    client = make_client(fake_api, token="")
    try:
        window = LoginWindow(store, AuthService(store, client))
        assert window.forgot_button.text() == "فراموشی گذرواژه"
        window.close()
    finally:
        client.close()
        store.close()


# ---- super admin: reset to 12345 / choose a password ----------------------------------
def test_reset_to_default_requires_a_change(auth, fake_api):
    row = fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    admin = AuthService(auth.store, make_client(fake_api))
    admin.reset_password_to_default(row["id"])
    result = auth.authenticate("sara", "12345")
    assert result.must_change_password is True
    assert fake_api.find_staff("sara")["must_change_password"] is True


def test_super_admin_sets_a_chosen_password(auth, fake_api):
    row = fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    admin = AuthService(auth.store, make_client(fake_api))
    admin.reset_password(row["id"], "Chosen12345", must_change_password=False)
    result = auth.authenticate("sara", "Chosen12345")
    assert result.must_change_password is False


def test_users_page_offers_reset_default_and_requests_page_decides(ui_context, admin_qapp, fake_api):
    from app.ui.pages.password_requests import PasswordRequestsPage
    from app.ui.pages.users import UsersPage

    fake_api.add_staff("sara", "Oldpass123", ROLE_OPERATOR)
    fake_api.pw_requests[1] = {"id": 1, "staff_id": 2, "token": "t", "status": "pending",
                               "created_at": "2025-01-01T10:00:00+00:00"}
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    users = UsersPage(context)
    users.load()
    _pump(admin_qapp)
    # v2.8.2: in the row's «بیشتر» menu
    labels = {a.text() for b in users.findChildren(type(users.add_button))
              for a in getattr(b, "menu_actions", [])}
    assert "بازنشانی گذرواژه به ۱۲۳۴۵" in labels and "تغییر گذرواژه" in labels

    page = PasswordRequestsPage(context)
    page.load()
    _pump(admin_qapp)
    assert page.table.rowCount() == 1
    page._decide({"id": 1, "username": "sara"}, False)
    _pump(admin_qapp)
    assert fake_api.pw_requests[1]["status"] == "rejected"


# ---- server edition: no login screen ---------------------------------------------------
def test_edition_detection(monkeypatch):
    monkeypatch.setenv("SHOPADMIN_EDITION", "client")
    assert not edition.is_server_edition()
    monkeypatch.setenv("SHOPADMIN_EDITION", "server")
    assert edition.is_server_edition()
    monkeypatch.delenv("SHOPADMIN_EDITION")
    # without an override the edition is "has app.server_setup" (absent in the client build)
    from build_shopadmin import SERVER_ONLY_MODULES

    assert "app.server_setup" in SERVER_ONLY_MODULES
    assert edition.edition() == edition.EDITION_SERVER


def test_console_sign_in_uses_only_the_service_key(auth, fake_api):
    result = auth.console_sign_in(SERVICE_KEY)
    assert result.principal.role == ROLE_SUPER_ADMIN
    assert auth.api.token
    assert OWNER_PASSWORD not in str(fake_api.login_bodies)      # no password involved
    with pytest.raises(AuthError):
        auth.console_sign_in("wrong-key")


def test_server_edition_never_builds_a_login_window(tmp_path, admin_qapp, fake_api, monkeypatch):
    from app import main as app_main
    from app import server_setup

    monkeypatch.setenv("SHOPADMIN_EDITION", "server")
    monkeypatch.setattr(server_setup, "service_key", lambda: SERVICE_KEY)
    store = Store(tmp_path / "srv.db")
    store.configure_connection("http://shopapi.test")
    store.set_setting("wizard_completed", True)
    controller = app_main.ShopAdminApp(admin_qapp)
    controller.store = store
    controller.api = make_client(fake_api, token="")
    controller.auth = AuthService(store, controller.api)
    opened = []
    monkeypatch.setattr(controller, "_open_main_window",
                        lambda principal, **kw: opened.append(principal.role))
    try:
        assert controller.server_edition
        controller.show_login()
        _pump(admin_qapp)
        assert controller.login_window is None
        assert opened == [ROLE_SUPER_ADMIN]
        assert ("POST", "/auth/login") not in fake_api.requests
    finally:
        controller.api.close()
        store.close()


def test_client_edition_keeps_the_login_window(tmp_path, admin_qapp, fake_api, monkeypatch):
    from app import main as app_main

    monkeypatch.setenv("SHOPADMIN_EDITION", "client")
    store = Store(tmp_path / "cli.db")
    store.configure_connection("http://shopapi.test")
    controller = app_main.ShopAdminApp(admin_qapp)
    controller.store = store
    controller.api = make_client(fake_api, token="")
    controller.auth = AuthService(store, controller.api)
    try:
        controller.show_login()
        assert controller.login_window is not None
        controller.login_window.close()
    finally:
        controller.api.close()
        store.close()
