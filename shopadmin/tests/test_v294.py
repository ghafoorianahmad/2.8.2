"""v2.9.4: database drop-down and precise connection errors (tested as the service
account), «مدیر کل» on reinstall / settings, the eye on every password field, the
look applied live, the money input with Persian words, Persian-only errors, the
faint «بستن» (and the audit that catches it), the status-code helper and the
test-data cleanup."""
from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from app import api_client, persian, server_setup as setup, user_messages  # noqa: E402
from app.ui import password_eye, theme, widgets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOPAPI = ROOT.parent / "shopapi" / "app"
SCRIPTS = ROOT / "scripts"


def _pump(rounds: int = 80, until=None) -> None:
    for _ in range(rounds):
        QApplication.processEvents()
        if until is not None and until():
            return


@pytest.fixture
def server_folder(tmp_path, monkeypatch):
    folder = tmp_path / "ShopServer"
    folder.mkdir()
    (folder / ".env").write_text("DB_SERVER=.\\SQLEXPRESS\nDB_NAME=hesab5\nDB_USER=shopbot\n"
                                 "DB_PASSWORD=S3cret\nAPI_PORT=9443\nADMIN_API_KEY=k\n",
                                 encoding="utf-8")
    monkeypatch.setattr(setup, "data_dir", lambda: folder)
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "lan_addresses", lambda: ["192.168.1.20"])
    monkeypatch.setattr(setup, "list_databases", lambda *a, **k: ["hesab2", "hesab5", "hesab5 t"])
    monkeypatch.setattr(setup, "current_owners", lambda port: [{"username": "owner"}])
    return folder


# ---- 1. database drop-down -------------------------------------------------------------------------
def test_database_is_chosen_from_the_servers_list(server_folder, admin_qapp):
    from app.ui import server_setup_wizard as wiz

    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        assert isinstance(wizard.db_name, wiz.DatabasePicker)
        assert not wizard.db_name.isEditable()                 # no free typing
        wizard._step = wizard._steps.index("database")
        wizard._update()
        _pump(until=lambda: wizard.db_name.loaded)
        assert wizard.db_name.names() == ["hesab2", "hesab5", "hesab5 t"]
        assert wizard.db_name.text() == "hesab5"                # the saved one stays chosen
        wizard.db_name.setText("hesab9")                        # not on this server: marked
        assert wizard.db_name.text() == "hesab9"
        assert "پیدا نشد" in wizard.db_name.currentText()
        # the allowed-databases list is chosen from the same names
        assert isinstance(wizard.db_access.name_input, wiz.DatabasePicker)
        assert wizard.db_access.name_input.names() == ["hesab2", "hesab5", "hesab5 t"]
    finally:
        wizard.close()


def test_database_list_password_goes_on_stdin_never_the_command_line(monkeypatch, tmp_path):
    seen = {}

    def tool(args, timeout=60, stdin=None):
        seen["args"], seen["stdin"] = args, stdin
        return {"ok": True, "databases": ["hesab5"]}

    monkeypatch.setattr(setup, "run_server_tool", tool)
    assert setup.list_databases(r".\SQLEXPRESS", user="shopbot", password="S3cret") == ["hesab5"]
    assert seen["args"] == ["--list-dbs"] and "S3cret" not in " ".join(seen["args"])
    assert seen["stdin"]["password"] == "S3cret"


# ---- 2. precise errors --------------------------------------------------------------------------------
@pytest.mark.parametrize("kind, title, grant", [
    ("server_not_found", "SQL Server پیدا نشد", False),
    ("db_missing", "این پایگاه‌داده وجود ندارد", False),
    ("no_access", "دسترسی نیست", True),
    ("bad_password", "نام کاربری یا گذرواژهٔ SQL نادرست است", False),
])
def test_each_connection_problem_has_its_own_title_and_fix(server_folder, admin_qapp,
                                                          monkeypatch, kind, title, grant):
    from app.ui import server_setup_wizard as wiz

    answer = {"ok": False, "kind": kind, "title_fa": title, "fix_fa": "راه رفع این مشکل.",
              "error_code": "4060"}
    monkeypatch.setattr(setup, "harden_data_dir", lambda *a, **k: None)
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: {"ok": True})

    def failed():
        raise setup.database_error(answer)

    monkeypatch.setattr(setup, "check_database", failed)
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        wizard._test_database()
        _pump(200, until=lambda: wizard.db_result_title.text())
        assert title in wizard.db_result_title.text()
        assert wizard.db_result.text() == "راه رفع این مشکل."
        assert (not wizard.grant_button.isHidden()) is grant
        assert not wizard._db_ok
    finally:
        wizard.close()


def test_success_says_it_was_tested_as_the_service(server_folder, admin_qapp, monkeypatch):
    from app.ui import server_setup_wizard as wiz

    monkeypatch.setattr(setup, "harden_data_dir", lambda *a, **k: None)
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(setup, "check_database", lambda: {
        "ok": True, "groups": 12, "windows": True, "as_service": True,
        "login": "NT SERVICE\\ShopServer"})
    monkeypatch.setattr(setup, "service_db_check", lambda *a: {"ok": True, "groups": 12})
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        wizard.auth_windows.setChecked(True)
        wizard._test_database()
        _pump(200, until=lambda: "حساب خود سرویس" in wizard.db_result.text())
        assert "NT SERVICE\\ShopServer" in wizard.db_result.text() and wizard._db_ok
        # the running service itself refuses: «دسترسی نیست» + the grant button
        monkeypatch.setattr(setup, "service_db_check", lambda *a: {
            "ok": False, "message_fa": "ورود ناموفق"})
        wizard._test_database()
        _pump(200, until=lambda: "دسترسی نیست" in wizard.db_result_title.text())
        assert not wizard.grant_button.isHidden() and not wizard._db_ok
        assert wizard.shop_login_name() == "NT SERVICE\\ShopServer"
    finally:
        wizard.close()


def test_database_error_mapping():
    error = setup.database_error({"ok": False, "kind": "no_access", "title_fa": "دسترسی نیست",
                                  "fix_fa": "دکمه را بزنید.", "error_code": "916"})
    assert isinstance(error, setup.DatabaseAccessError) and error.kind == "db_access"
    assert error.message == "دسترسی نیست: دکمه را بزنید." and error.code == "916"
    error = setup.database_error({"ok": False, "kind": "db_missing", "databases": ["a"]})
    assert error.kind == "db_missing" and error.databases == ["a"]


# ---- 5. «مدیر کل» -----------------------------------------------------------------------------------
def test_owner_step_shows_the_current_owner_and_blank_keeps_it(server_folder, admin_qapp):
    from app.ui import server_setup_wizard as wiz

    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        assert "admin" in wizard._steps
        wizard._step = wizard._steps.index("admin")
        wizard._update()
        _pump(until=lambda: "owner" in wizard.owner_current.text())
        assert wizard.owner_current.text() == \
            "مدیر کل فعلی: owner — اگر خالی بگذارید همان می‌ماند"
        assert wizard._validate_admin() and wizard.owner_request() is None     # blank = keep
        wizard.admin_password.setText("New12345")
        wizard.admin_confirm.setText("New12345")
        assert not wizard._validate_admin()                 # a password needs the username
        wizard.admin_username.setText("owner")
        assert wizard._validate_admin()
        assert wizard.owner_request() == ("owner", "", "New12345")
    finally:
        wizard.close()


def test_first_owner_is_still_required(admin_qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path / "none")
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    from app.ui import server_setup_wizard as wiz

    wizard = wiz.ServerSetupWizard()
    try:
        assert wizard.owner_exists() is False
        assert not wizard._validate_admin()
        assert "هنوز «مدیر کل»ی نیست" in wizard.admin_error.text()
    finally:
        wizard.close()


def test_the_installer_never_stores_a_password():
    iss = (ROOT / "installer" / "ShopAdmin.iss").read_text(encoding="utf-8-sig")
    assert "Password" not in re.sub(r"(?im)^\s*;.*$", "", iss).replace("PasswordEdit", "")


# ---- 6. eye on every password field ---------------------------------------------------------------
def test_every_password_field_gets_an_eye_that_never_shows_a_saved_one(admin_qapp):
    password_eye.install(admin_qapp)
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    typed = QLineEdit()
    typed.setEchoMode(QLineEdit.EchoMode.Password)
    saved = QLineEdit("saved-secret")
    saved.setEchoMode(QLineEdit.EchoMode.Password)
    layout.addWidget(typed)
    layout.addWidget(saved)
    dialog.show()
    _pump(10)
    try:
        eye = typed._password_eye
        assert typed.property("password_eye") and saved.property("password_eye")
        typed.setFocus()
        typed.textEdited.emit("abc")       # what the person typed
        typed.setText("abc")
        typed.textEdited.emit("abc")
        _pump(5)
        eye.toggle()
        assert typed.echoMode() == QLineEdit.EchoMode.Normal
        eye.toggle()
        assert typed.echoMode() == QLineEdit.EchoMode.Password
        saved_eye = saved._password_eye
        assert saved_eye.saved and not saved_eye.action.isEnabled()
        saved_eye.toggle()
        assert saved.echoMode() == QLineEdit.EchoMode.Password
        saved.setText("")                  # emptied: what is typed next may be shown
        _pump(5)
        assert not saved_eye.saved and saved_eye.action.isEnabled()
    finally:
        dialog.close()


def test_eye_on_the_wizard_and_user_forms(server_folder, admin_qapp):
    from app.ui import server_setup_wizard as wiz

    password_eye.install(admin_qapp)
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        wizard.show()
        for key in ("database", "admin"):
            wizard._step = wizard._steps.index(key)
            wizard._update()
            _pump(10)
        for field in (wizard.db_password, wizard.admin_password, wizard.admin_confirm):
            assert field.property("password_eye"), field.placeholderText()
    finally:
        wizard.close()


# ---- 8. the look applied live ----------------------------------------------------------------------------
def test_look_is_applied_in_place_without_a_new_window(admin_qapp, monkeypatch):
    from app.main import ShopAdminApp

    # The global style sheet is not what is tested here: re-polishing every widget
    # earlier tests left in this process takes minutes. Only the colours change.
    applied = []

    def tokens_only(app, mode=None, *, palette=None, effects=None):
        applied.append((mode, palette, effects))
        theme.set_mode(mode or theme.MODE, palette)
        return theme.EFFECTS

    monkeypatch.setattr(theme, "apply_theme", tokens_only)
    theme.set_mode("light", "ocean")
    window = QWidget()
    window.setStyleSheet(f"background: {theme.SURFACE}; color: {theme.PRIMARY};")
    button = widgets.button("ذخیره", icon_name="save")
    layout = QVBoxLayout(window)
    layout.addWidget(button)
    window.show()
    old_primary = theme.PRIMARY

    class Store:
        values = {"theme_palette": "aurora", "theme_mode": "dark", "theme_effects": "simple"}

        def get_setting(self, key, default=None):
            return self.values.get(key, default)

    emitted = []
    host = types.SimpleNamespace(
        store=Store(), app=admin_qapp, main_window=window,
        context=types.SimpleNamespace(data_changed=types.SimpleNamespace(
            emit=lambda: emitted.append(True))))
    try:
        ShopAdminApp.apply_look_live(host)
        assert host.main_window is window and window.isVisible()       # no rebuilt window
        assert theme.PALETTE == "aurora" and theme.MODE == "dark"
        assert theme.PRIMARY != old_primary
        assert theme.PRIMARY.upper() in window.styleSheet().upper()
        assert old_primary.upper() not in window.styleSheet().upper()
        assert button.property("icon_spec").startswith("save|18|")
        assert emitted == [True]                                        # tables reload
        assert applied == [("dark", "aurora", "simple")]
    finally:
        window.close()
        theme.set_mode("light", "ocean")


def test_colour_map_and_remap():
    old, new = theme.palette_tokens("ocean", "light"), theme.palette_tokens("emerald", "dark")
    mapping = theme.colour_map(old, new)
    text = f"color: {old['TEXT']}; background: {old['SURFACE'].lower()}; border: #123456;"
    out = theme.remap(text, mapping)
    assert new["TEXT"].upper() in out.upper() and new["SURFACE"].upper() in out.upper()
    assert "#123456" in out                                             # not a token: kept


# ---- 9. money input and Persian errors ---------------------------------------------------------------
def test_number_words():
    assert persian.number_to_words(525_000_000) == "پانصد و بیست و پنج میلیون"
    assert persian.number_to_words(1000) == "هزار"
    assert persian.number_to_words(2_000_010) == "دو میلیون و ده"
    assert persian.number_to_words(100_000_000_000) == "صد میلیارد"
    assert persian.money_in_words(5_250_000_000) == (
        "پنج میلیارد و دویست و پنجاه میلیون ریال (پانصد و بیست و پنج میلیون تومان)")


def test_money_input_groups_digits_and_shows_words(admin_qapp):
    field = widgets.MoneyInput()
    field.edit.setText("")
    field.edit.insert("525000000")
    field.edit.textEdited.emit(field.edit.text())
    assert field.text() == "۵۲۵٬۰۰۰٬۰۰۰" and field.value() == 525_000_000
    assert field.unit.text() == "ریال"
    assert "پانصد و بیست و پنج میلیون ریال" in field.words.text()
    field.setText("5250000000000")           # one zero too many: refused in Persian
    assert "بیش از حد مجاز" in field.problem() and "صد میلیارد" in field.problem()
    field.setText("۱۲۳")
    assert field.value() == 123 and field.problem() == ""
    field.clear()
    assert field.value() is None and field.words.text() == ""


def test_price_dialog_refuses_a_huge_price_in_persian(admin_qapp):
    from app.ui.pages.item_requests import StockConfirmDialog

    dialog = StockConfirmDialog(None, {"id": 1, "kind": "purchase", "kala_code": 5,
                                       "product_name": "گوشی", "price_rial": 0})
    try:
        dialog.price_input.setText("1000000000000")
        dialog._accept()
        assert dialog.error_label.isVisibleTo(dialog)
        assert "بیش از حد مجاز" in dialog.error_label.text()
        assert not re.search(r"[A-Za-z]{4,}", dialog.error_label.text())
    finally:
        dialog.close()


def test_validation_errors_are_persian():
    detail = [{"loc": ["body", "price_rial"], "msg": "Input should be less than or equal to "
               "100000000000", "type": "less_than_equal", "ctx": {"le": 100000000000}}]
    text = api_client.translate_detail(detail, 422)
    assert text == "اطلاعات واردشده درست نیست: «قیمت» نباید بیشتر از ۱۰۰٬۰۰۰٬۰۰۰٬۰۰۰ باشد."
    assert not re.search(r"[A-Za-z]", text)
    text = api_client.translate_detail([{"loc": ["body", "username"], "type": "missing"}], 422)
    assert "«نام کاربری» لازم است" in text
    # the exact 2.9.3 message, if it ever arrives as plain text
    assert user_messages.humanize("price_rial: Input should be less than or equal to "
                                  "100000000000").startswith("«قیمت» نباید بیشتر از")


def _server_details() -> list[str]:
    """Every English HTTPException text in shopapi ({...} filled with a sample)."""
    texts = set()
    for path in SHOPAPI.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r'HTTPException\([^"\)]*?f?"([^"]+)"', source):
            text = re.sub(r"\{[^}]*\}", "12", match.group(1))
            # a key of a structured detail, or a text made only of other values
            if text != "message" and re.search(r"[A-Za-z]{3}", text):
                texts.add(text)
    return sorted(texts)


def test_every_server_message_reaches_staff_in_persian():
    details = _server_details()
    assert len(details) > 60
    untranslated = []
    for detail in details:
        text = api_client.translate_detail(detail, 409)
        if text == api_client.MSG_SERVER_REFUSED or re.search(r"[A-Za-z]{5,} [a-z]{2,}", text):
            untranslated.append(detail)
    assert untranslated == []


def test_unknown_english_never_shown_and_exception_names_are_persian():
    assert api_client.translate_detail("Some brand new failure", 400) == \
        api_client.MSG_SERVER_REFUSED
    shown = user_messages.humanize("برنامهٔ سرور با خطا متوقف شد: PermissionError: [Errno 13] "
                                   "Permission denied: 'C:\\x\\.env'")
    assert shown == "برنامهٔ سرور با خطا متوقف شد: دسترسی رد شد"
    assert user_messages.humanize("Traceback (most recent call last)") == user_messages.GENERIC
    assert user_messages.humanize("«hesab5» روی NT SERVICE\\ShopServer") == \
        "«hesab5» روی NT SERVICE\\ShopServer"


def test_message_boxes_and_toasts_humanize(admin_qapp, monkeypatch):
    shown = []
    from PySide6.QtWidgets import QLabel

    monkeypatch.setattr(widgets.MessageDialog, "exec", lambda self: shown.append(
        [lbl.text() for lbl in self.findChildren(QLabel)]))
    widgets.error(None, "خطا", "ValueError: invalid literal for int()")
    texts = shown[0]
    assert any(user_messages.GENERIC in t for t in texts)
    assert not any("ValueError" in t for t in texts)


# ---- 10. «بستن» is a real button, and the audit catches a faint one ----------------------------------
def _dialog_with_close(sheet: str):
    """A dialog with «ذخیره» and «بستن»; the theme's style sheet on the dialog only
    (re-polishing every widget earlier tests left behind would take minutes)."""
    dialog = QDialog()
    dialog.setObjectName("WindowRoot")
    dialog.setStyleSheet(sheet)
    layout = QVBoxLayout(dialog)
    layout.addWidget(widgets.label("پیام"))
    layout.addLayout(widgets.footer(widgets.button("ذخیره", variant="primary"),
                                    close=widgets.button("بستن")))
    dialog.resize(420, 160)
    return dialog


def test_close_button_stands_out_and_a_faint_one_is_caught(admin_qapp, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import button_audit

    monkeypatch.setattr(theme, "EFFECTS", "simple")
    try:
        for palette in theme.PALETTE_NAMES:
            for mode in ("light", "dark"):
                theme.set_mode(mode, palette)
                dialog = _dialog_with_close(theme.stylesheet())
                dialog.show()
                _pump(10)
                close = [b for b in dialog.findChildren(type(widgets.button("x")))
                         if b.text() == "بستن"][0]
                measured = button_audit.edge_contrast(dialog.grab().toImage(), close, dialog)
                assert measured is not None and measured >= 3.0, (palette, mode, measured)
                dialog.close()
        # the 2.9.3 look (a 1.3:1 frame) is reported
        theme.set_mode("light", "ocean")
        faint = theme.stylesheet().replace("border: 1px solid " + theme.BUTTON_BORDER,
                                           "border: 1px solid " + theme.BORDER_STRONG)
        faint = faint.replace("border-bottom: 2px solid " + theme.BUTTON_BORDER,
                              "border-bottom: 2px solid " + theme.BORDER_STRONG)
        dialog = _dialog_with_close(faint)
        dialog.show()
        _pump(10)
        problems = button_audit.problems_in(dialog, "test dialog",
                                            button_audit.standard_height())
        assert any("«بستن»" in p and "looks faint" in p for p in problems), problems
        dialog.close()
    finally:
        theme.set_mode("light", "ocean")


# ---- 11 / 12. cleanup and status codes ---------------------------------------------------------------
def test_cleanup_needs_a_backup_then_the_typed_word(admin_qapp, monkeypatch):
    from app.ui import cleanup_dialog

    calls = []
    monkeypatch.setattr(setup, "cleanup_preview", lambda port: {
        "counts": {"orders": 3, "users": 2, "staff": 1}, "owners": ["owner"],
        "staff_removed": ["test1"], "labels": {"orders": "سفارش", "users": "مشتری",
                                               "staff": "کاربر"}, "confirm_text": "پاک‌سازی"})
    monkeypatch.setattr(setup, "backup_now", lambda: calls.append("backup") or {
        "file": "ShopServer_1.zip", "verify": {"ok": True}, "offsite": {}})
    monkeypatch.setattr(setup, "cleanup_run", lambda port, confirm: calls.append(confirm) or {
        "counts": {"orders": 3, "users": 2}, "owners": ["owner"], "staff_removed": ["test1"],
        "labels": {"orders": "سفارش", "users": "مشتری"}})
    monkeypatch.setattr(cleanup_dialog.widgets, "confirm", lambda *a, **k: True)
    dialog = cleanup_dialog.CleanupDialog(None, port=8443)
    try:
        _pump(until=lambda: "سفارش" in dialog.counts_label.text())
        assert "سفارش: ۳" in dialog.counts_label.text() and "owner" in dialog.counts_label.text()
        assert not dialog.confirm_input.isEnabled() and not dialog.run_button.isEnabled()
        dialog._backup()
        _pump(until=lambda: dialog.backed_up)
        assert calls == ["backup"] and dialog.confirm_input.isEnabled()
        dialog.confirm_input.setText("بله")
        assert not dialog.run_button.isEnabled()
        dialog.confirm_input.setText("پاک‌سازی")
        assert dialog.run_button.isEnabled()
        dialog._run()
        _pump(until=lambda: dialog.result_label.isVisibleTo(dialog))
        assert calls == ["backup", "پاک‌سازی"] and "پاک شد" in dialog.result_label.text()
    finally:
        dialog.close()


def test_status_codes_dialog_shows_counts_and_latest(admin_qapp):
    from app.ui.status_codes import StatusCodesDialog, status_rows

    payload = {"ok": True, "database": "hesab5 t",
               "statuses": [{"status": 1, "internet": False, "count": 5, "last_order": 90,
                             "last_date": "1405/08/01"},
                            {"status": 1, "internet": True, "count": 2, "last_order": 91,
                             "last_date": "1405/08/02"},
                            {"status": None, "internet": True, "count": 7, "last_order": 92,
                             "last_date": "1405/08/03"}],
               "latest_sazeh": [{"order": 90, "date": "1405/08/01", "status": 1,
                                 "user_code": 2, "total": 1000, "items": 1}]}
    rows = status_rows(payload)
    assert rows[0][:3] == ("۱", "۵", "۲") and rows[-1][0] == "خالی (NULL)"
    dialog = StatusCodesDialog(None, lambda: payload)
    try:
        _pump(until=lambda: dialog.latest_table.rowCount() == 1)
        assert dialog.status_table.rowCount() == 2 and "hesab5 t" in dialog.database_label.text()
    finally:
        dialog.close()
