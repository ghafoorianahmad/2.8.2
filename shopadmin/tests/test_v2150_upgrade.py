"""v2.15.0 #2: installing a new version over a working server never changes its
settings. The installer opened «راه‌اندازی سرور» (empty fields) after every
upgrade; saving it replaced the database, the allowed list and «ثبت واقعی».
Now the setup over existing settings opens WITH them, the server's key order is
used (ACCOUNTING_DATABASE before DB_NAME) and an unreadable .env is never
overwritten with blanks."""
from __future__ import annotations

import json

import pytest

from app import errors
from app import server_setup as setup

ENV = """DB_SERVER=.\\SQLEXPRESS
DB_NAME=hesab5
ACCOUNTING_DATABASE="hesab5 t"
DB_DRIVER="ODBC Driver 18 for SQL Server"
DB_TRUSTED=yes
API_PORT=8443
ADMIN_CHAT_IDS=bale:1
BALE_TOKEN=123456:abcdefghijklmnopqrstuvwxyz
TG_READER_ENABLED=yes
TG_PRICE_CHANNEL=AbrishamiiPhoneMashhad
BACKUP_COPY_DIR=E:\\ShopServerBackup
BACKUP_KEEP_DAYS=21
ACCOUNTING_ALLOWED_DATABASES="hesab5 t,hesab5"
ACCOUNTING_WRITE_DATABASES="hesab5 t"
"""


@pytest.fixture
def server_folder(tmp_path, monkeypatch):
    folder = tmp_path / "ShopServerData"
    folder.mkdir()
    (folder / ".env").write_text(ENV, encoding="utf-8")
    monkeypatch.setattr(setup, "data_dir", lambda: folder)
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "lan_addresses", lambda: ["192.168.1.20"])
    return folder


def test_the_database_shown_is_the_one_the_server_uses(server_folder):
    current = setup.read_current_config()
    assert current.db_name == "hesab5 t"                 # ACCOUNTING_DATABASE wins, as on the server
    assert current.db_driver == "ODBC Driver 18 for SQL Server"


def test_setup_after_an_upgrade_opens_with_the_saved_settings(server_folder, admin_qapp,
                                                              monkeypatch):
    from app.ui import server_setup_wizard as wiz

    sent = {}

    def fake_tool(args, timeout=60, stdin=None):
        if args and args[0] == "--init-config":
            sent.update(json.loads(open(args[1], encoding="utf-8").read()))
        return {"ok": True}

    monkeypatch.setattr(setup, "run_server_tool", fake_tool)
    # what the installer starts after installing: «--server-setup»
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETUP)
    try:
        assert wizard.settings_mode and not wizard.load_failed
        wizard.db_name.set_names(["hesab5", "hesab5 t", "master2"])   # the list arrives
        assert wizard.db_name.text() == "hesab5 t"                   # never the first in the list
        assert wizard.db_access.allowed() == ["hesab5 t", "hesab5"]
        assert wizard.db_access.writing() == ["hesab5 t"]
        setup.write_config(wizard._db_config(), port=wizard.port.value(),
                           extra=wizard.config_extra())
    finally:
        wizard.close()
    assert sent["db_name"] == "hesab5 t" and sent["db_driver"] == "ODBC Driver 18 for SQL Server"
    assert sent["allowed_databases"] == "hesab5 t,hesab5"
    assert sent["write_databases"] == "hesab5 t"
    assert sent["admin_chat_ids"] == "bale:1" and sent["backup_keep_days"] == "21"
    assert sent["backup_copy_dir"] == r"E:\ShopServerBackup"
    assert sent["tg_reader_enabled"] is True
    assert sent["tg_price_channel"] == "AbrishamiiPhoneMashhad"
    assert "bale_token" not in sent                               # untouched secret: kept


def test_unreadable_settings_are_never_replaced(server_folder, admin_qapp, monkeypatch):
    from app.ui import server_setup_wizard as wiz

    def denied():
        raise errors.SetupError("تنظیمات فعلی سرور خوانده نشد.")

    monkeypatch.setattr(setup, "read_current_config", denied)
    written = []
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: written.append(a))
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETUP)
    try:
        assert wizard.load_failed and wizard.settings_mode
        wizard._execute()
        assert written == []
        assert "ذخیره انجام نشد" in wizard.progress.toPlainText()
    finally:
        wizard.close()


def test_a_new_server_still_gets_the_full_setup(tmp_path, admin_qapp, monkeypatch):
    from app.ui import server_setup_wizard as wiz

    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path / "none")
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETUP)
    try:
        assert not wizard.settings_mode and not wizard.load_failed
        assert wizard.db_access.allowed() == [] and wizard.db_access.writing() == []
    finally:
        wizard.close()
