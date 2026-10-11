"""Configuration loaded from environment / .env.

Tokens live only here (and in httpx clients built from here). They are never
logged, never included in exceptions and never written to the state database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_BALE_API_BASE = "https://tapi.bale.ai"


def _load_dotenv() -> None:
    load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    return float(raw) if raw else default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key).lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(key: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _env(key).split(",") if part.strip())


#: Channels this process can run (one adapter each in app/platforms/).
SUPPORTED_PLATFORMS = ("bale",)


@dataclass
class Settings:
    # --- shopapi ---
    shopapi_base_url: str = "http://127.0.0.1:8000"
    #: The server's own certificate when the API runs over HTTPS (pinned).
    shopapi_ca_file: str = ""
    bot_api_key: str = ""
    admin_api_key: str = ""

    # --- bots ---
    # Bale is the only channel (REQUIREMENTS §2). A later channel plugs in as a
    # new adapter in app/platforms/ on the same core; the old Telegram Bot-API
    # adapter and its HTTP/SOCKS proxy were removed (2026-10-11).
    bale_token: str = ""
    bale_api_base: str = DEFAULT_BALE_API_BASE

    # --- admins ---
    admin_chat_ids: tuple[str, ...] = ()

    # --- behaviour ---
    sqlite_path: str = str(BASE_DIR / "shopbots.db")
    poll_timeout: int = 25
    admin_sweep_seconds: int = 30
    rate_limit_messages: int = 20
    rate_limit_window: float = 60.0
    max_input_len: int = 500
    max_name_len: int = 80
    http_timeout: float = 15.0
    product_page_size: int = 5
    #: Receipt images (photo or JPEG/PNG file) up to this size, and at most
    #: RECEIPT_RATE_COUNT uploads per RECEIPT_RATE_WINDOW seconds per customer.
    receipt_max_bytes: int = 5 * 1024 * 1024
    receipt_rate_count: int = 5
    receipt_rate_window: float = 600.0
    statement_page_size: int = 8
    #: List out-of-stock products too (marked "ناموجود"); they cannot be ordered.
    show_out_of_stock: bool = True
    #: Operator copy of messages.fa.json ("" = built-in texts only).
    messages_file: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            shopapi_base_url=_env("SHOPAPI_BASE_URL", cls.shopapi_base_url),
            shopapi_ca_file=_env("SHOPAPI_CA_FILE", ""),
            bot_api_key=_env("BOT_API_KEY", ""),
            admin_api_key=_env("ADMIN_API_KEY", ""),
            bale_token=_env("BALE_TOKEN", ""),
            bale_api_base=_env("BALE_API_BASE", DEFAULT_BALE_API_BASE),
            admin_chat_ids=_env_list("ADMIN_CHAT_IDS"),
            sqlite_path=_env("SQLITE_PATH", str(BASE_DIR / "shopbots.db")),
            poll_timeout=_env_int("POLL_TIMEOUT", 25),
            admin_sweep_seconds=_env_int("ADMIN_SWEEP_SECONDS", 30),
            rate_limit_messages=_env_int("RATE_LIMIT_MESSAGES", 20),
            rate_limit_window=_env_float("RATE_LIMIT_WINDOW", 60.0),
            max_input_len=_env_int("MAX_INPUT_LEN", 500),
            max_name_len=_env_int("MAX_NAME_LEN", 80),
            http_timeout=_env_float("HTTP_TIMEOUT", 15.0),
            product_page_size=_env_int("PRODUCT_PAGE_SIZE", 5),
            receipt_max_bytes=_env_int("RECEIPT_MAX_BYTES", 5 * 1024 * 1024),
            receipt_rate_count=_env_int("RECEIPT_RATE_COUNT", 5),
            receipt_rate_window=_env_float("RECEIPT_RATE_WINDOW", 600.0),
            statement_page_size=_env_int("STATEMENT_PAGE_SIZE", 8),
            show_out_of_stock=_env_bool("SHOW_OUT_OF_STOCK", True),
            messages_file=_env("BOT_MESSAGES_FILE", ""),
        )

    # --- helpers ---
    def admin_entries(self) -> list[tuple[str | None, str]]:
        """Admin chats as (platform|None, chat_id).

        `ADMIN_CHAT_IDS` accepts `12345` (any platform) and `bale:12345` for an
        unambiguous target. Entries for other platforms (e.g. a leftover
        `telegram:12345`) are ignored, never matched against a Bale chat.
        """
        entries: list[tuple[str | None, str]] = []
        for raw in self.admin_chat_ids:
            platform, sep, chat_id = raw.partition(":")
            platform = platform.strip().lower()
            if not sep:
                entries.append((None, raw))
            elif platform in SUPPORTED_PLATFORMS and chat_id.strip():
                entries.append((platform, chat_id.strip()))
        return entries

    def is_admin_chat(self, platform: str, chat_id: str | int) -> bool:
        """Admin actions are refused unless this exact chat is configured."""
        cid = str(chat_id)
        for entry_platform, entry_chat in self.admin_entries():
            if entry_chat == cid and (entry_platform is None or entry_platform == platform):
                return True
        return False

    def admin_targets(self, available_platforms) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        for entry_platform, entry_chat in self.admin_entries():
            if entry_platform is None:
                for platform in available_platforms:
                    targets.append((platform, entry_chat))
            elif entry_platform in available_platforms:
                targets.append((entry_platform, entry_chat))
        return targets

    def enabled_platforms(self) -> tuple[str, ...]:
        return ("bale",) if self.bale_token else ()
