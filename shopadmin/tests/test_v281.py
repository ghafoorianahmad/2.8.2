"""v2.8.1: «تنظیمات سرور» (server wizard with the saved values), real writing per
database, clear reasons on «سرور فروشگاه», no APIPA addresses, a right-aligned
side bar, whole table headers, clear filters, responsive dialogs, Telegram keys
and the theme choice for everyone."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import (QDialog, QLabel, QPushButton, QScrollArea,  # noqa: E402
                               QVBoxLayout)

from app import server_setup as setup  # noqa: E402
from app.statuses import ROLE_OPERATOR  # noqa: E402
from app.ui import theme, widgets  # noqa: E402

from .test_ui import _pump, make_context_with_role, ui_context  # noqa: E402,F401
from .test_v280 import _purchase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ---- 4: only addresses staff computers can reach -------------------------------------------
@pytest.mark.parametrize("address,usable", [
    ("192.168.1.10", True), ("10.0.0.5", True), ("172.16.3.4", True),
    ("169.254.12.7", False), ("127.0.0.1", False), ("0.0.0.0", False),
    ("224.0.0.1", False), ("240.0.0.1", False), ("fe80::1", False), ("junk", False),
])
def test_link_local_and_invalid_addresses_are_hidden(address, usable):
    assert setup.usable_lan_address(address) is usable


def test_lan_addresses_drop_apipa(monkeypatch):
    infos = [(2, 1, 6, "", (a, 0)) for a in ("169.254.3.4", "192.168.1.20", "127.0.0.1",
                                             "192.168.1.3")]
    monkeypatch.setattr(setup.socket, "getaddrinfo", lambda *a, **k: infos)
    assert setup.lan_addresses() == ["192.168.1.3", "192.168.1.20"]


# ---- 1/3/9: the saved settings for «تنظیمات سرور» ---------------------------------------
ENV = """DB_SERVER=.\\SQLEXPRESS
DB_NAME=hesab5
DB_TRUSTED=no
DB_USER=shopbot
DB_PASSWORD=S3cret!pw
API_PORT=9443
FIREWALL_ALLOWED_IPS=192.168.1.0/24
BANK_ACCOUNT_TEXT=حساب ملت
ADMIN_CHAT_IDS=bale:1
BALE_TOKEN=123456:abcdefghijklmnopqrstuvwxyz
TG_API_ID=12345
ACCOUNTING_ALLOWED_DATABASES="hesab5 t,hesab5"
ACCOUNTING_WRITE_DATABASES="hesab5 t"
"""


@pytest.fixture
def server_folder(tmp_path, monkeypatch):
    folder = tmp_path / "ShopServer"
    folder.mkdir()
    (folder / ".env").write_text(ENV, encoding="utf-8")
    monkeypatch.setattr(setup, "data_dir", lambda: folder)
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "lan_addresses", lambda: ["192.168.1.20"])
    return folder


def test_current_config_never_returns_secrets(server_folder):
    current = setup.read_current_config()
    assert (current.db_server, current.db_name, current.db_user, current.port) == \
        (r".\SQLEXPRESS", "hesab5", "shopbot", 9443)
    assert current.db_password_set and current.allowed_ips == "192.168.1.0/24"
    assert current.allowed_databases == ["hesab5 t", "hesab5"]
    assert current.write_databases == ["hesab5 t"]
    assert current.secrets_set == {"BALE_TOKEN": True, "TELEGRAM_BOT_TOKEN": False,
                                   "TG_API_ID": True, "TG_API_HASH": False, "TG_PROXY": False,
                                   "BACKUP_PASSPHRASE": False, "BACKUP_SHARE_PASSWORD": False}
    assert "S3cret" not in repr(current) and "abcdefgh" not in repr(current)


def test_settings_wizard_is_filled_and_keeps_untouched_secrets(server_folder, admin_qapp,
                                                              monkeypatch):
    from app.ui import server_setup_wizard as wiz

    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        # v2.9.4: «مدیر کل» in settings too (blank = keep), plus «ابزارها»
        assert wizard.settings_mode and "admin" in wizard._steps and "tools" in wizard._steps
        assert wizard.windowTitle() == "تنظیمات سرور فروشگاه"
        assert wizard.db_name.text() == "hesab5" and wizard.port.value() == 9443
        assert wizard.db_password.text() == "" and wizard.db_password.placeholderText() == wiz.KEEP_SECRET
        assert wizard.bale_token.text() == "" and wizard.bale_token.placeholderText() == wiz.KEEP_SECRET
        assert wizard.bale_token.echoMode() == wizard.bale_token.EchoMode.Password
        assert wizard.tg_api_hash.placeholderText() != wiz.KEEP_SECRET
        assert wizard._db_ok   # unchanged settings need no new test
        # an empty password keeps the saved one (no SQL password asked again)
        assert wizard._db_input_problem(wizard._db_config()) == ""
        extra = wizard.config_extra()
        assert extra["bale_token"] is None and extra["tg_api_id"] is None
        assert extra["allowed_databases"] == "hesab5 t,hesab5"
        assert extra["write_databases"] == "hesab5 t"
        wizard.telegram_token.setText("777777:" + "B" * 30)
        assert wizard.config_extra()["telegram_bot_token"] == "777777:" + "B" * 30
        # «hesab5» is allowed, but writing is off for it: said plainly
        text, _color = wizard.database_state_text()
        assert "«hesab5» مجاز است" in text
        wizard.db_name.setText("hesab9")
        assert "در فهرست مجاز نیست" in wizard.database_state_text()[0]
        wizard.db_name.textEdited.emit("hesab9")
        assert not wizard._db_ok
    finally:
        wizard.close()


def test_real_writing_needs_a_confirmation_per_database(server_folder, admin_qapp, monkeypatch):
    from app.ui import server_setup_wizard as wiz

    answers = []
    monkeypatch.setattr(wiz.widgets, "confirm", lambda *a, **k: answers.pop(0))
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        access = wizard.db_access
        answers.append(False)
        assert access.set_write("hesab5", True) is False   # declined: stays off
        assert access.writing() == ["hesab5 t"]
        answers.append(True)
        assert access.set_write("hesab5", True) is True
        assert access.writing() == ["hesab5 t", "hesab5"]
        assert "ثبت واقعی در «hesab5» روشن است" in wizard.database_state_text()[0]
        # the run asks once more for databases newly switched on
        answers.append(False)
        assert wizard._confirm_run() is False
        access.add("shop_copy")
        assert access.allowed() == ["hesab5 t", "hesab5", "shop_copy"]
        assert "shop_copy" not in access.writing()
    finally:
        wizard.close()


def test_first_setup_writes_nothing_and_shows_no_write_switch_on(admin_qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path / "none")
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    from app.ui import server_setup_wizard as wiz

    # «تنظیمات سرور» before any setup = the normal first setup
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        assert not wizard.settings_mode and "admin" in wizard._steps and "tools" not in wizard._steps
        assert wizard.db_access.allowed() == [] and wizard.db_access.writing() == []
        assert wizard.config_extra()["write_databases"] == ""
    finally:
        wizard.close()


def test_launcher_writes_the_new_settings():
    text = (ROOT.parent / "shopsystem" / "launcher.py").read_text(encoding="utf-8")
    for field, key in (("telegram_bot_token", "TELEGRAM_BOT_TOKEN"), ("tg_api_id", "TG_API_ID"),
                       ("tg_api_hash", "TG_API_HASH"),
                       ("allowed_databases", "ACCOUNTING_ALLOWED_DATABASES"),
                       ("write_databases", "ACCOUNTING_WRITE_DATABASES")):
        assert f'"{field}": "{key}"' in text
    assert '"ACCOUNTING_WRITE_ENABLED": "false"' in text   # new installs: still off


def test_installer_server_shortcut_opens_server_settings():
    iss = (ROOT / "installer" / "ShopAdmin.iss").read_text(encoding="utf-8")
    server_part = iss[iss.index("#ifdef SERVER\n; v2.8.1: on the server the desktop shortcut"):]
    desktop = server_part[:server_part.index("#else")]
    assert "{autodesktop}\\تنظیمات سرور" in desktop and '"--server-settings"' in desktop
    assert "{group}\\تنظیمات سرور" in iss
    assert '[InstallDelete]' in iss and "{commondesktop}\\{#MyAppNameFa}.lnk" in iss


def test_main_understands_server_settings():
    text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '"--server-settings" in args' in text
    assert "relaunch_elevated([elevated_flag])" in text


# ---- 2: clear reasons on «سرور فروشگاه» --------------------------------------------------------
def test_status_rows_say_why():
    from app.ui.pages.server import accounting_text, write_text

    text, color = accounting_text({"accounting_database": "hesab5", "accounting": {
        "ok": False, "error_code": "4060",
        "message_fa": "پایگاه‌دادهٔ حسابداری باز نشد: نام پایگاه‌داده اشتباه است یا این کاربر به آن دسترسی ندارد."}})
    assert text.startswith("قطع — «hesab5»: پایگاه‌دادهٔ حسابداری باز نشد")
    assert "grant_shop_app.ps1" in text and color == theme.DANGER
    assert "دسترسی ندارد" not in accounting_text({"accounting": {"ok": True, "latency_ms": 4}})[0]

    base = {"accounting_database": "hesab5", "accounting_write_enabled": False}
    assert "در فهرست پایگاه‌داده‌های مجاز نیست" in write_text({**base, "write_block_reason": "not_allowed"})[0]
    assert "«ثبت واقعی» برایش روشن نشده" in write_text({**base, "write_block_reason": "write_off"})[0]
    on = write_text({"accounting_database": "hesab5", "accounting_write_enabled": True,
                     "status_code_configured": True})
    assert on == ("فعال — ثبت واقعی در «hesab5»", theme.SUCCESS_DARK)
    assert "کد وضعیت سفارش" in write_text({"accounting_database": "hesab5",
                                           "accounting_write_enabled": True,
                                           "status_code_configured": False})[0]


def test_server_settings_button_only_on_the_server(ui_context, admin_qapp, monkeypatch):
    from app.ui.pages import server as server_page

    monkeypatch.setattr(server_page, "server_settings_available", lambda: False)
    page = server_page.ServerPage(ui_context)
    assert not page.server_settings_button.isVisibleTo(page)
    monkeypatch.setattr(server_page, "server_settings_available", lambda: True)
    page = server_page.ServerPage(ui_context)
    assert page.server_settings_button.isVisibleTo(page)
    asked = []
    monkeypatch.setattr(setup, "relaunch_elevated", lambda args: asked.append(args) or True)
    page._open_server_settings()
    assert asked == [["--server-settings"]]


def test_server_settings_need_the_server_edition(monkeypatch):
    from app.ui.pages import server as server_page

    monkeypatch.setattr(server_page, "is_server_edition", lambda: False)
    assert server_page.server_settings_available() is False


# ---- 9: Telegram keys in the remote settings ------------------------------------------------------
def test_telegram_keys_have_persian_labels():
    from app.server_settings import SETTINGS_FA, translate_problem

    for key in ("TELEGRAM_BOT_TOKEN", "TG_API_ID", "TG_API_HASH"):
        assert SETTINGS_FA[key][2] == "secret"
    assert translate_problem("must be a Telegram api_id") == "api_id باید فقط عدد باشد"


# ---- 5: the side bar starts at the right edge ----------------------------------------------------------
def test_nav_buttons_are_flush_right(admin_qapp):
    """In a right-to-left button Qt mirrors «text-align»; «left» is the right edge."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon, QPixmap

    assert "padding: 2px 12px; text-align: left;" in theme.stylesheet()
    button = QPushButton("  سفارش‌ها")
    button.setObjectName("NavButton")
    pixmap = QPixmap(20, 20)
    pixmap.fill(QColor("#FF0000"))
    button.setIcon(QIcon(pixmap))
    button.setIconSize(QSize(20, 20))
    button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    button.setStyleSheet("QPushButton { background: white; border: none; padding: 10px 12px; "
                         "text-align: left; }")
    button.resize(240, 44)
    image = button.grab().toImage()
    reds = [x for x in range(image.width())
            if QColor(image.pixel(x, 22)).red() > 200 and QColor(image.pixel(x, 22)).green() < 60]
    assert reds and min(reds) > image.width() // 2   # the icon sits on the right half


# ---- 6: whole table headers ---------------------------------------------------------------------------
def test_headers_are_never_cut(admin_qapp):
    store = {"table_widths.t281": [60, 60, 60, 60, 60]}

    class Store:
        def get_setting(self, key, default=None):
            return store.get(key, default)

        def set_setting(self, key, value):
            store[key] = value

    from app.ui.pages.catalog_models import ITEM_HEADERS

    widgets.DataTable.settings_store = Store()
    try:
        table = widgets.DataTable(ITEM_HEADERS[:5], key="t281")   # old narrow widths saved
    finally:
        widgets.DataTable.settings_store = None
    for column, text in enumerate(ITEM_HEADERS[:5]):
        assert table.columnWidth(column) >= table.header_width(text), text
    empty = widgets.DataTable(("برچسب برای مشتری", "نام فعلی در حسابداری"))
    assert empty.columnWidth(0) >= empty.header_width("برچسب برای مشتری")


# ---- 7: filters say what they cover ---------------------------------------------------------------
def test_request_filters_are_not_two_plain_alls(ui_context, admin_qapp):
    from app.ui.pages import item_requests as page_mod

    page = page_mod.ItemRequestsPage(ui_context)
    texts = [b.text() for b in (*page._scope_buttons.values(), *page._tab_buttons.values())]
    texts.append(page.kind_combo.itemText(0))
    assert "همه" not in texts and len(set(texts)) == len(texts)
    assert {"همهٔ درخواست‌ها", "همهٔ وضعیت‌ها", "همهٔ انواع"} <= set(texts)
    labels = [w.text() for w in page.findChildren(QLabel)]
    assert any("وضعیت:" in t for t in labels) and any("نوع:" in t for t in labels)


# ---- 8: dialogs scroll, resize, maximise and fit the screen ------------------------------------
def test_every_dialog_is_responsive():
    sources = list((ROOT / "app" / "ui").rglob("*.py"))
    plain = [f"{p.name}: {m}" for p in sources
             for m in re.findall(r"^class (\w+)\(QDialog\)", p.read_text(encoding="utf-8"), re.M)
             if not (p.name == "widgets.py" and m == "ResponsiveDialog")]
    assert plain == []


def test_request_dialog_keeps_its_buttons_on_a_small_screen(ui_context, fake_api, admin_qapp,
                                                           monkeypatch):
    from app.ui.pages import item_requests as page_mod

    small = QRect(0, 0, 800, 520)   # e.g. 1366x768 at 150% Windows scaling, minus the taskbar
    monkeypatch.setattr(widgets, "available_geometry", lambda _w: small)
    row = _purchase(fake_api)
    dialog = page_mod.ItemRequestDialog(make_context_with_role(ui_context, ROLE_OPERATOR), row)
    try:
        widgets.make_responsive(dialog)
        flags = dialog.windowFlags()
        assert flags & Qt.WindowType.WindowMaximizeButtonHint and dialog.isSizeGripEnabled()
        dialog.show()
        _pump(admin_qapp)
        assert dialog.width() <= 800 and dialog.height() <= 520
        scroll = dialog._fit_scroll
        assert isinstance(scroll, QScrollArea)
        # «تأیید موجودی» is in the footer, outside the scrolled part, and on screen
        assert not scroll.widget().isAncestorOf(dialog.stock_button)
        assert dialog.stock_button.isVisibleTo(dialog)
        bottom = dialog.stock_button.mapTo(dialog, dialog.stock_button.rect().bottomLeft()).y()
        assert bottom <= dialog.height()
    finally:
        dialog.close()


def test_message_dialog_still_fits_its_text(admin_qapp):
    long_text = "متن بسیار طولانی " * 60
    dialog = widgets.MessageDialog(None, "عنوان", long_text)
    widgets.make_responsive(dialog)
    dialog.show()
    admin_qapp.processEvents()
    try:
        assert dialog.ok_button.isVisibleTo(dialog)
        assert dialog.height() <= widgets.available_geometry(dialog).height()
    finally:
        dialog.close()


def test_plain_dialog_layout_without_footer_is_wrapped(admin_qapp):
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("یک"))
    layout.addWidget(QLabel("دو"))
    widgets.make_responsive(dialog)
    assert isinstance(dialog._fit_scroll, QScrollArea)
    assert len(dialog._fit_scroll.widget().findChildren(QLabel)) == 2
    widgets.make_responsive(dialog)    # a second call changes nothing
    assert dialog.layout().count() == 1


# ---- 10: light / dark is reachable for everyone ----------------------------------------------------
def test_theme_choice_is_in_everyones_preferences(ui_context, admin_qapp, monkeypatch):
    from app.ui.main_window import NotificationDialog

    monkeypatch.setattr(widgets, "info", lambda *a, **k: None)
    dialog = NotificationDialog(make_context_with_role(ui_context, ROLE_OPERATOR))
    # v2.9.0: option cards (palette × mode × effects) instead of one combo box
    assert list(dialog.appearance.cards["mode"]) == ["light", "dark", "system"]
    dialog.appearance.select(mode="dark")
    dialog.save()
    assert ui_context.store.get_setting("theme_mode") == "dark"
