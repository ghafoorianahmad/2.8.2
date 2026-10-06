"""Application configuration, loaded from environment variables / .env.

No real credentials belong in code or this repo. Secrets come only from the
environment or a .env file (see .env.example).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Host names (SQL Server names) that may receive real writes.
_DEFAULT_ALLOWED_HOSTS = ("localhost", r".\SQLEXPRESS")


def _load_dotenv() -> None:
    load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key).lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


def _env_int_list(key: str) -> tuple[int, ...]:
    raw = _env(key).replace(" ", "")
    if not raw:
        return ()
    return tuple(int(part) for part in raw.split(",") if part)


def _odbc_value(value: str) -> str:
    """Quote an ODBC connection-string value with braces when it contains a
    semicolon, a brace or edge whitespace (the ODBC escaping rule)."""
    text = str(value)
    if text != text.strip() or any(ch in text for ch in ";{}"):
        return "{" + text.replace("}", "}}") + "}"
    return text


@dataclass
class Settings:
    # --- Accounting (SQL Server) connection ---
    accounting_driver: str = "ODBC Driver 17 for SQL Server"
    accounting_server: str = r".\SQLEXPRESS"
    accounting_database: str = "hesab5 t"
    accounting_trusted: bool = True
    accounting_username: str = ""
    accounting_password: str = ""
    accounting_encrypt: str = "no"
    accounting_trust_server_certificate: str = "yes"
    accounting_connect_timeout: int = 5
    accounting_query_timeout: int = 15

    # --- Writer safety ---
    accounting_write_enabled: bool = False
    accounting_allowed_hosts: tuple[str, ...] = _DEFAULT_ALLOWED_HOSTS

    # --- Accounting config values ---
    accounting_status_code: int = 6808
    accounting_usercode: int = 1
    accounting_anbarcode: int = 1
    stock_warehouses: tuple[int, ...] = ()

    # --- Business ---
    price_level_bot: int = 3
    price_level_site: int = 3
    reserve_hours: int = 12
    bank_account_text: str = ""
    max_order_qty: int = 10000
    allow_shared_person_code: bool = False

    # --- API keys ---
    bot_api_key: str = ""
    site_api_key: str = ""
    admin_api_key: str = ""

    # --- Own DB ---
    sqlite_path: str = str(BASE_DIR / "shopapi.db")

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        allowed = tuple(
            h.strip() for h in _env("ACCOUNTING_ALLOWED_HOSTS", "").split(",") if h.strip()
        ) or _DEFAULT_ALLOWED_HOSTS
        return cls(
            accounting_driver=_env("ACCOUNTING_DRIVER", cls.accounting_driver),
            accounting_server=_env("ACCOUNTING_SERVER", cls.accounting_server),
            accounting_database=_env("ACCOUNTING_DATABASE", cls.accounting_database),
            accounting_trusted=_env_bool("ACCOUNTING_TRUSTED_CONNECTION", True),
            accounting_username=_env("ACCOUNTING_USERNAME", ""),
            accounting_password=_env("ACCOUNTING_PASSWORD", ""),
            accounting_encrypt=_env("ACCOUNTING_ENCRYPT", "no"),
            accounting_trust_server_certificate=_env(
                "ACCOUNTING_TRUST_SERVER_CERTIFICATE", "yes"
            ),
            accounting_connect_timeout=_env_int("ACCOUNTING_CONNECT_TIMEOUT", 5),
            accounting_query_timeout=_env_int("ACCOUNTING_QUERY_TIMEOUT", 15),
            accounting_write_enabled=_env_bool("ACCOUNTING_WRITE_ENABLED", False),
            accounting_allowed_hosts=allowed,
            accounting_status_code=_env_int("ACCOUNTING_STATUS_CODE", 6808),
            accounting_usercode=_env_int("ACCOUNTING_USERCODE", 1),
            accounting_anbarcode=_env_int("ACCOUNTING_ANBARCODE", 1),
            stock_warehouses=_env_int_list("STOCK_WAREHOUSES"),
            price_level_bot=_env_int("PRICE_LEVEL_BOT", 3),
            price_level_site=_env_int("PRICE_LEVEL_SITE", 3),
            reserve_hours=_env_int("RESERVE_HOURS", 12),
            bank_account_text=_env("BANK_ACCOUNT_TEXT", ""),
            max_order_qty=_env_int("MAX_ORDER_QTY", 10000),
            allow_shared_person_code=_env_bool("ALLOW_SHARED_PERSON_CODE", False),
            bot_api_key=_env("BOT_API_KEY", ""),
            site_api_key=_env("SITE_API_KEY", ""),
            admin_api_key=_env("ADMIN_API_KEY", ""),
            sqlite_path=_env("SQLITE_PATH", str(BASE_DIR / "shopapi.db")),
        )

    def accounting_connection_string(self) -> str:
        parts = [
            "DRIVER={" + self.accounting_driver.replace("}", "}}") + "}",
            "SERVER=" + _odbc_value(self.accounting_server),
            "DATABASE=" + _odbc_value(self.accounting_database),
        ]
        if self.accounting_trusted:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append("UID=" + _odbc_value(self.accounting_username))
            parts.append("PWD=" + _odbc_value(self.accounting_password))
        parts.append("Encrypt=" + self.accounting_encrypt)
        if self.accounting_trust_server_certificate:
            parts.append("TrustServerCertificate=" + self.accounting_trust_server_certificate)
        return ";".join(parts) + ";"

    def price_level_for(self, channel: str) -> int:
        return self.price_level_bot if channel == "bot" else self.price_level_site

    def write_allowed(self) -> bool:
        allowed = {h.lower() for h in self.accounting_allowed_hosts}
        return self.accounting_write_enabled and self.accounting_server.lower() in allowed


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance (override in tests via dependency override)."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
