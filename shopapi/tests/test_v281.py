"""v2.8.1: real writing per database (no built-in name), clear reasons, Telegram keys."""
from __future__ import annotations

from app import control
from app.config import Settings


def test_no_database_name_is_built_in():
    for name in ("hesab5 t", "hesab5"):
        settings = Settings(accounting_database=name)
        assert not settings.write_allowed()
        assert settings.write_block_reason() == "not_allowed"


def test_real_writing_is_switched_on_per_database():
    both = dict(accounting_allowed_databases=("hesab5 t", "hesab5"),
                accounting_write_databases=("hesab5 t", "HESAB5"))
    assert Settings(accounting_database="hesab5 t", **both).write_allowed()
    assert Settings(accounting_database="hesab5", **both).write_allowed()
    # on the allowed list, but writing not switched on for it
    only_test = dict(accounting_allowed_databases=("hesab5 t", "hesab5"),
                     accounting_write_databases=("hesab5 t",))
    prod = Settings(accounting_database="hesab5", **only_test)
    assert not prod.write_allowed() and prod.write_block_reason() == "write_off"
    # switched on but not on the allowed list -> still off
    stray = Settings(accounting_database="other", accounting_write_databases=("other",))
    assert not stray.write_allowed() and stray.write_block_reason() == "not_allowed"
    assert Settings(accounting_database="").write_block_reason() == "no_database"


def test_write_info_has_names_only(monkeypatch):
    monkeypatch.setenv("ACCOUNTING_DATABASE", "hesab5")
    monkeypatch.setenv("ACCOUNTING_ALLOWED_DATABASES", "hesab5 t,hesab5")
    monkeypatch.setenv("ACCOUNTING_WRITE_DATABASES", "hesab5")
    info = Settings.from_env().write_info()
    assert info == {"accounting_database": "hesab5",
                    "allowed_databases": ["hesab5 t", "hesab5"],
                    "write_databases": ["hesab5"], "write_block_reason": None}


def test_telegram_keys_are_editable_secrets():
    for key in ("TELEGRAM_BOT_TOKEN", "TG_API_ID", "TG_API_HASH"):
        assert control.EDITABLE[key][1] is True
    assert control.validate_settings({
        "TELEGRAM_BOT_TOKEN": "123456:" + "A" * 30,
        "TG_API_ID": "1234567",
        "TG_API_HASH": "0123456789abcdef0123456789ABCDEF",
    }) == {}
    problems = control.validate_settings({"TG_API_ID": "abc", "TG_API_HASH": "short",
                                          "TELEGRAM_BOT_TOKEN": "nope"})
    assert set(problems) == {"TG_API_ID", "TG_API_HASH", "TELEGRAM_BOT_TOKEN"}
    # the switch for real writing stays server-only
    assert "ACCOUNTING_WRITE_DATABASES" not in control.EDITABLE
    assert "ACCOUNTING_ALLOWED_DATABASES" not in control.EDITABLE
