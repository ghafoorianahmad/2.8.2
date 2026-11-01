"""v2.15.0: an upgrade never changes the server's settings.

After installing 2.14.0 the database went back to «hesab5»: the installer opened
the setup wizard (empty fields) after every upgrade, and the server read
ACCOUNTING_DATABASE before DB_NAME, so a .env with both kept an old name in force.
Here an upgrade is simulated over a full set of settings: the data folder move,
the service registration and a «تنظیمات سرور» save that changes nothing must
leave every value exactly as it was."""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
from dotenv import dotenv_values

import launcher

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT.parent / "shopadmin" / "installer" / "ShopAdmin.iss"

EXISTING = """# Shop server configuration - written by the server setup.
DB_SERVER=.\\SQLEXPRESS
DB_NAME="hesab5 t"
ACCOUNTING_DATABASE="hesab5 t"
DB_DRIVER="ODBC Driver 18 for SQL Server"
DB_TRUSTED=yes
ACCOUNTING_ALLOWED_DATABASES="hesab5 t,hesab5"
ACCOUNTING_WRITE_DATABASES="hesab5 t"
ACCOUNTING_STATUS_CODE=7
API_HOST=0.0.0.0
API_PORT=8443
API_TLS=true
ADMIN_CHAT_IDS=bale:123
BOT_API_KEY=bot-key-kept
ADMIN_API_KEY=admin-key-kept
WORKER_API_KEY=worker-key-kept
SITE_API_KEY=site-key-kept
BALE_TOKEN=bale-token-kept
TG_READER_ENABLED=yes
TG_PRICE_CHANNEL=AbrishamiiPhoneMashhad
BACKUP_COPY_DIR=E:\\ShopServerBackup
BACKUP_KEEP_DAYS=21
PRICE_LEVEL_BOT=4
"""


@pytest.fixture
def control_module(monkeypatch):
    """``shopapi_app.control`` from the source tree (the build renames shopapi's
    ``app`` package to ``shopapi_app``)."""
    package = types.ModuleType("shopapi_app")
    package.__path__ = [str(ROOT.parent / "shopapi" / "app")]
    monkeypatch.setitem(sys.modules, "shopapi_app", package)
    for name in ("shopapi_app.control", "shopapi_app.util"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import importlib

    return importlib.import_module("shopapi_app.control")


def _server(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / ".env").write_text(EXISTING, encoding="utf-8")
    (folder / "shopapi.db").write_bytes(b"db" * 100)
    return folder


def _no_change_payload(values: dict) -> dict:
    """What «تنظیمات سرور» sends when it is opened and saved without a change
    (secrets untouched = not sent; see shopadmin ``config_extra``)."""
    return {
        "db_server": values["DB_SERVER"], "db_name": values["DB_NAME"], "db_trusted": True,
        "db_user": "", "db_password": "", "db_driver": values["DB_DRIVER"],
        "api_port": 8443, "api_host": "0.0.0.0",
        "firewall_allowed_ips": "", "shoptg_dir": "", "admin_chat_ids": values["ADMIN_CHAT_IDS"],
        "allowed_databases": values["ACCOUNTING_ALLOWED_DATABASES"],
        "write_databases": values["ACCOUNTING_WRITE_DATABASES"],
        "tg_reader_enabled": True, "tg_api_preset": "tdesktop",
        "tg_price_channel": values["TG_PRICE_CHANNEL"],
        "backup_copy_dir": values["BACKUP_COPY_DIR"], "backup_keep_days": "21",
        "backup_share_user": "", "backup_share_password": "",
    }


def _init(folder: Path, payload: dict, capsys) -> dict:
    launcher.configure_paths(folder)
    json_path = folder / "setup-test.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    assert launcher.init_config(json_path) == 0
    capsys.readouterr()
    assert not json_path.exists()
    return {k: v for k, v in dotenv_values(folder / ".env").items() if v is not None}


#: settings the owner chose; an upgrade (or an unchanged save) must keep each one
KEPT = ("DB_NAME", "ACCOUNTING_DATABASE", "DB_DRIVER", "ACCOUNTING_ALLOWED_DATABASES",
        "ACCOUNTING_WRITE_DATABASES", "ACCOUNTING_STATUS_CODE", "ADMIN_CHAT_IDS",
        "BOT_API_KEY", "ADMIN_API_KEY", "WORKER_API_KEY", "SITE_API_KEY", "BALE_TOKEN",
        "TG_READER_ENABLED", "BACKUP_COPY_DIR", "BACKUP_KEEP_DAYS", "PRICE_LEVEL_BOT",
        "API_PORT", "API_TLS")


def test_upgrade_keeps_every_setting(tmp_path, monkeypatch, capsys, control_module):
    from test_v294 import FakeService

    service = FakeService()
    monkeypatch.setitem(sys.modules, "winservice", service)
    monkeypatch.setattr(launcher, "register_data_dir", lambda folder: None)
    monkeypatch.setattr(launcher, "registered_data_dir", lambda: None)
    monkeypatch.setattr(launcher, "harden_folder", lambda folder, run=None: None)
    monkeypatch.setattr(launcher, "read_env_values", lambda: {})
    old = _server(tmp_path / "ProgramData" / "ShopServer")
    before_bytes = (old / ".env").read_bytes()
    before = {k: v for k, v in dotenv_values(old / ".env").items() if v is not None}

    # 1. the installer moves the data folder (copy + check + switch)
    launcher.configure_paths(old)
    target = tmp_path / "D" / "ShopServerData"
    assert launcher.move_data(str(target), health=lambda timeout: True) == 0
    capsys.readouterr()
    assert (target / ".env").read_bytes() == before_bytes
    # 2. it registers the service again for the same folder: no .env change
    assert service.installed_for == [target]
    assert (target / ".env").read_bytes() == before_bytes
    # 3. «تنظیمات سرور» opened and saved without a change
    after = _init(target, _no_change_payload(before), capsys)
    for key in KEPT:
        assert after.get(key) == before[key], key


def test_saving_a_new_database_also_replaces_its_old_twin(tmp_path, capsys, control_module):
    folder = _server(tmp_path / "data")
    text = (folder / ".env").read_text(encoding="utf-8").replace(
        'ACCOUNTING_DATABASE="hesab5 t"', "ACCOUNTING_DATABASE=hesab5")
    (folder / ".env").write_text(text, encoding="utf-8")
    values = {k: v for k, v in dotenv_values(folder / ".env").items() if v is not None}
    after = _init(folder, _no_change_payload(values), capsys)
    # the server reads ACCOUNTING_DATABASE first: it must follow the saved choice
    assert after["DB_NAME"] == "hesab5 t" and after["ACCOUNTING_DATABASE"] == "hesab5 t"
    assert after["ACCOUNTING_WRITE_DATABASES"] == "hesab5 t"


def test_first_setup_writes_defaults_only_once(tmp_path, capsys, control_module):
    folder = tmp_path / "fresh"
    folder.mkdir()
    first = _init(folder, {"db_server": "x", "db_name": "hesab5 t"}, capsys)
    assert first["ACCOUNTING_WRITE_ENABLED"] == "false" and "ACCOUNTING_DATABASE" not in first
    keys = {k: first[k] for k in ("BOT_API_KEY", "ADMIN_API_KEY")}
    second = _init(folder, {"db_name": "hesab5 t"}, capsys)
    assert {k: second[k] for k in keys} == keys              # keys never regenerated


def test_installer_offers_the_setup_only_on_a_new_server():
    text = ISS.read_text(encoding="utf-8-sig")
    run_section = text.split("\n[Run]", 1)[1].split("\n[", 1)[0]
    run = re.search(r'Parameters: "--server-setup";[^\n]*\n(?:[^\n]*\\\n)*[^\n]*', run_section)
    assert run is not None
    entry = run.group(0)
    assert "postinstall" in entry and "Check: IsNewServer" in entry
    assert re.search(r"function IsNewServer\(\): Boolean;\s*begin\s*Result := OldDataDir = '';",
                     text)
