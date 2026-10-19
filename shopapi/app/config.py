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
# The accounting copies used for testing (test mode only for these).
_DEFAULT_TEST_DATABASES = ("hesab5 t",)
#: Status codes known to be wrong: refused even when configured.
INVALID_STATUS_CODES = frozenset({6808})


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


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    return float(raw) if raw else default


def _env_list(key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _env(key)
    if not raw:
        return default
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _env_optional_int(key: str) -> int | None:
    raw = _env(key)
    return int(raw) if raw else None


def _env_int_list(key: str) -> tuple[int, ...]:
    raw = _env(key).replace(" ", "")
    if not raw:
        return ()
    return tuple(int(part) for part in raw.split(",") if part)


#: SQL logins the shop refuses to use (REQUIREMENTS §10).
FORBIDDEN_SQL_LOGINS = frozenset({"sa"})


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
    #: Databases that may receive real (production) writes. Empty = none: a
    #: production database must be named here explicitly (with the switch and
    #: the host) before anything is committed to it.
    accounting_allowed_databases: tuple[str, ...] = ()
    #: Test copies: only these switch on test mode (writes without the switch).
    accounting_test_databases: tuple[str, ...] = _DEFAULT_TEST_DATABASES

    # --- Accounting config values ---
    #: KalaOrder.Status for our orders. No default on purpose: 6808 does not
    #: exist (reference §9.2) and the real value comes from GUI test G2. Until
    #: it is set, orders are never committed (a dry run still works).
    accounting_status_code: int | None = None
    accounting_usercode: int = 1
    accounting_anbarcode: int = 1
    stock_warehouses: tuple[int, ...] = ()

    # --- Business ---
    price_level_bot: int = 3
    price_level_site: int = 3
    #: The customer uploads the payment receipt within this many minutes of
    #: ordering; afterwards the order is cancelled locally (no gateway).
    receipt_deadline_minutes: int = 30
    #: Seconds between checks for orders past the receipt deadline (0 = off).
    order_timeout_check_seconds: int = 30
    #: v2.8.0: a phone is ordered only while its product has stock in «سازه حساب»;
    #: otherwise the bot offers «درخواست خرید». false = the list alone decides.
    phone_stock_required: bool = True

    # --- Sales windows (Asia/Tehran; decision 2026-10-14) ---
    #: false = sales follow only the manual buttons in ShopAdmin.
    sales_windows_enabled: bool = True
    #: A list posted before this time is the morning list: sales open until then.
    sales_morning_close: str = "13:30"
    #: A list posted before this time is the evening list: sales open until then.
    sales_evening_close: str = "20:30"
    #: Python weekday numbers without sales (4 = Friday).
    sales_closed_weekdays: tuple[int, ...] = (4,)
    bank_account_text: str = ""
    #: Payment details shown to the customer after checkout. v2.6.0: a valid
    #: 16-digit PAYMENT_CARD_NUMBER is REQUIRED; without it orders are refused
    #: (the bot never shows a placeholder card) and ShopAdmin warns.
    payment_card_number: str = ""
    payment_sheba: str = ""
    payment_owner: str = ""
    max_order_qty: int = 10000
    allow_shared_person_code: bool = False
    #: Customers awaiting approval may order up to these limits; the totals
    #: include their other open orders (REQUIREMENTS §3). 0 = may not order.
    pending_max_order_items: int = 3

    # --- Receipts / tracking ---
    receipt_max_bytes: int = 5 * 1024 * 1024
    #: "" = a ``receipts`` folder next to the SQLite file.
    receipts_dir: str = ""
    #: How often orders written to accounting are checked for invoices (0 = off).
    invoice_sync_seconds: int = 300
    #: Health monitor (REQUIREMENTS §8): seconds between checks; 0 = off.
    health_check_seconds: int = 60
    #: Consecutive bad checks before a component is reported down.
    health_fail_threshold: int = 2
    #: The Telegram worker's status older than this = worker not running.
    tg_status_stale_minutes: int = 20
    #: Most recent KOL rows read for a customer statement.
    statement_max_rows: int = 2000

    # --- Site catalog models (REQUIREMENTS §9a) ---
    #: Server-local hour of the nightly mapping check; -1 = off.
    model_check_hour: int = 2
    #: A renamed product stays visible (only "drifted") at or above this name similarity.
    model_drift_min_score: float = 0.7
    #: The bot accepts a fuzzy model-name match at or above this similarity.
    model_resolve_min_score: float = 0.75

    # --- Distributor price list / Telegram worker (REQUIREMENTS §4–6) ---
    #: PDF prices are thousand Toman -> Rial.
    pricelist_unit_rial: int = 10_000
    #: Added to نقد when روال is empty: 500,000 Toman = 5,000,000 Rial.
    pricelist_cash_surcharge_rial: int = 5_000_000
    #: A mapped price moving more than this (percent) holds the new list.
    pricelist_max_change_pct: float = 15.0
    #: Phone prices older than this are not sold (inquiry only); 0 = no limit.
    pricelist_max_age_hours: int = 72
    pricelist_max_bytes: int = 10 * 1024 * 1024
    #: "" = a ``pricelists`` folder next to the SQLite file (PDF copies).
    pricelists_dir: str = ""

    # --- API keys ---
    bot_api_key: str = ""
    site_api_key: str = ""
    admin_api_key: str = ""
    #: The Telegram price/proxy worker (shoptg); loopback only, worker endpoints only.
    worker_api_key: str = ""
    #: BOT/ADMIN keys are accepted only from this machine (the bots run in the
    #: same process). LAN clients sign in as staff instead. SITE key is exempt
    #: (a future site relay calls from outside).
    service_keys_local_only: bool = True

    # --- Staff sign-in ---
    staff_session_hours: int = 12
    staff_remember_days: int = 7
    login_max_attempts: int = 5
    login_lock_minutes: int = 15

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
            accounting_allowed_databases=_env_list("ACCOUNTING_ALLOWED_DATABASES"),
            accounting_test_databases=_env_list(
                "ACCOUNTING_TEST_DATABASES", _DEFAULT_TEST_DATABASES),
            accounting_status_code=_env_optional_int("ACCOUNTING_STATUS_CODE"),
            accounting_usercode=_env_int("ACCOUNTING_USERCODE", 1),
            accounting_anbarcode=_env_int("ACCOUNTING_ANBARCODE", 1),
            stock_warehouses=_env_int_list("STOCK_WAREHOUSES"),
            price_level_bot=_env_int("PRICE_LEVEL_BOT", 3),
            price_level_site=_env_int("PRICE_LEVEL_SITE", 3),
            receipt_deadline_minutes=max(1, _env_int("RECEIPT_DEADLINE_MINUTES", 30)),
            order_timeout_check_seconds=_env_int("ORDER_TIMEOUT_CHECK_SECONDS", 30),
            phone_stock_required=_env_bool("PHONE_STOCK_REQUIRED", True),
            sales_windows_enabled=_env_bool("SALES_WINDOWS_ENABLED", True),
            sales_morning_close=_env("SALES_MORNING_CLOSE", "13:30"),
            sales_evening_close=_env("SALES_EVENING_CLOSE", "20:30"),
            sales_closed_weekdays=(
                _env_int_list("SALES_CLOSED_WEEKDAYS") if _env("SALES_CLOSED_WEEKDAYS") else (4,)),
            bank_account_text=_env("BANK_ACCOUNT_TEXT", ""),
            payment_card_number=_env("PAYMENT_CARD_NUMBER", ""),
            payment_sheba=_env("PAYMENT_SHEBA", ""),
            payment_owner=_env("PAYMENT_OWNER", ""),
            max_order_qty=_env_int("MAX_ORDER_QTY", 10000),
            allow_shared_person_code=_env_bool("ALLOW_SHARED_PERSON_CODE", False),
            pending_max_order_items=_env_int("PENDING_MAX_ORDER_ITEMS", 3),
            receipt_max_bytes=_env_int("RECEIPT_MAX_BYTES", 5 * 1024 * 1024),
            receipts_dir=_env("RECEIPTS_DIR", ""),
            invoice_sync_seconds=_env_int("INVOICE_SYNC_SECONDS", 300),
            health_check_seconds=_env_int("HEALTH_CHECK_SECONDS", 60),
            health_fail_threshold=max(1, _env_int("HEALTH_FAIL_THRESHOLD", 2)),
            tg_status_stale_minutes=max(5, _env_int("TG_STATUS_STALE_MINUTES", 20)),
            statement_max_rows=_env_int("STATEMENT_MAX_ROWS", 2000),
            model_check_hour=_env_int("MODEL_CHECK_HOUR", 2),
            model_drift_min_score=_env_float("MODEL_DRIFT_MIN_SCORE", 0.7),
            model_resolve_min_score=_env_float("MODEL_RESOLVE_MIN_SCORE", 0.75),
            pricelist_unit_rial=_env_int("PRICELIST_UNIT_RIAL", 10_000),
            pricelist_cash_surcharge_rial=_env_int("PRICELIST_CASH_SURCHARGE_RIAL", 5_000_000),
            pricelist_max_change_pct=float(_env("PRICELIST_MAX_CHANGE_PCT", "15") or 15),
            pricelist_max_age_hours=_env_int("PRICELIST_MAX_AGE_HOURS", 72),
            pricelist_max_bytes=_env_int("PRICELIST_MAX_BYTES", 10 * 1024 * 1024),
            pricelists_dir=_env("PRICELISTS_DIR", ""),
            bot_api_key=_env("BOT_API_KEY", ""),
            site_api_key=_env("SITE_API_KEY", ""),
            admin_api_key=_env("ADMIN_API_KEY", ""),
            worker_api_key=_env("WORKER_API_KEY", ""),
            service_keys_local_only=_env_bool("SERVICE_KEYS_LOCAL_ONLY", True),
            staff_session_hours=_env_int("STAFF_SESSION_HOURS", 12),
            staff_remember_days=_env_int("STAFF_REMEMBER_DAYS", 7),
            login_max_attempts=_env_int("LOGIN_MAX_ATTEMPTS", 5),
            login_lock_minutes=_env_int("LOGIN_LOCK_MINUTES", 15),
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
            if self.accounting_username.strip().lower() in FORBIDDEN_SQL_LOGINS:
                # SECURITY.md: the shop never uses sa (its password cannot be changed)
                raise ValueError("the SQL login 'sa' is refused - use the least-privilege "
                                 "login from sql/create_api_user.sql")
            parts.append("UID=" + _odbc_value(self.accounting_username))
            parts.append("PWD=" + _odbc_value(self.accounting_password))
        parts.append("Encrypt=" + self.accounting_encrypt)
        if self.accounting_trust_server_certificate:
            parts.append("TrustServerCertificate=" + self.accounting_trust_server_certificate)
        return ";".join(parts) + ";"

    def price_level_for(self, channel: str) -> int:
        # Staff browse the catalogue at the bot price level (what customers see).
        return self.price_level_bot if channel in ("bot", "staff") else self.price_level_site

    def receipts_path(self) -> Path | None:
        """Folder for receipt images; None for an in-memory database (tests)."""
        if self.receipts_dir:
            return Path(self.receipts_dir)
        if self.sqlite_path == ":memory:":
            return None
        return Path(self.sqlite_path).resolve().parent / "receipts"

    def pricelists_path(self) -> Path | None:
        """Folder for copies of imported price-list PDFs; None for in-memory DBs."""
        if self.pricelists_dir:
            return Path(self.pricelists_dir)
        if self.sqlite_path == ":memory:":
            return None
        return Path(self.sqlite_path).resolve().parent / "pricelists"

    #: The default accounting copy used for testing.
    TEST_DATABASE = "hesab5 t"

    def database_name(self) -> str:
        """The configured accounting database, as stored with every order."""
        return self.accounting_database.strip()

    def is_test_db(self) -> bool:
        """Test mode: the database is on the test allowlist
        (``ACCOUNTING_TEST_DATABASES``, default ``hesab5 t``). Connected to a test
        copy, writes need no switch (nothing real can be damaged there)."""
        name = self.database_name().lower()
        return bool(name) and name in {d.strip().lower() for d in self.accounting_test_databases}

    def database_allowlisted(self) -> bool:
        """The database is a production database named in
        ``ACCOUNTING_ALLOWED_DATABASES`` (never true while that is empty)."""
        name = self.database_name().lower()
        return bool(name) and name in {d.strip().lower() for d in self.accounting_allowed_databases}

    def payment_card_digits(self) -> str:
        """The configured card number as 16 digits, or "" when missing/invalid."""
        digits = "".join(ch for ch in str(self.payment_card_number or "") if ch.isdigit())
        if len(digits) != 16 or len(set(digits)) == 1:
            return ""
        return digits

    def payment_ready(self) -> bool:
        """Customers can be told where to pay (v2.6.0: else no checkout)."""
        return bool(self.payment_card_digits())

    def status_code_problem(self) -> str | None:
        """Why orders cannot be committed with the configured Status, or None."""
        if self.accounting_status_code is None:
            return "ACCOUNTING_STATUS_CODE is not set"
        if self.accounting_status_code in INVALID_STATUS_CODES:
            return f"ACCOUNTING_STATUS_CODE={self.accounting_status_code} is not a valid status"
        return None

    def write_allowed(self) -> bool:
        """Real (committed) writes. Test mode: allowlisted test copies. Otherwise
        all three: the switch, an allowed host and an allowlisted database."""
        if self.is_test_db():
            return True
        allowed = {h.lower() for h in self.accounting_allowed_hosts}
        return (self.accounting_write_enabled
                and self.accounting_server.lower() in allowed
                and self.database_allowlisted())


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
