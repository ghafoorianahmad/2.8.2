"""Configuration loaded from environment / .env.

Tokens live only here (and in httpx clients built from here). They are never
logged, never included in exceptions and never written to the state database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
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


def _tg_api_id() -> int:
    raw = _env("TG_API_ID")
    if raw and not raw.isdigit():
        raise ValueError("TG_API_ID must be a number")
    return int(raw or 0)


def _env_list(key: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _env(key).split(",") if part.strip())


#: Channels that can hold ADMIN chats. Owner alerts and admin actions are Bale
#: only: a Telegram user id must never match an admin id configured for Bale.
SUPPORTED_PLATFORMS = ("bale",)
#: Customer channels this process can run (one adapter each in app/platforms/).
CUSTOMER_PLATFORMS = ("bale", "telegram")


@dataclass
class Settings:
    # --- shopapi ---
    shopapi_base_url: str = "http://127.0.0.1:8000"
    #: The server's own certificate when the API runs over HTTPS (pinned).
    shopapi_ca_file: str = ""
    bot_api_key: str = ""
    admin_api_key: str = ""

    # --- bots ---
    # Bale is the primary channel (REQUIREMENTS §2). Telegram (Phase 7) is a
    # Telethon *bot* connection through the MTProto proxy pool; it shares
    # TG_API_ID / TG_API_HASH / TG_PROXY / WORKER_API_KEY with shoptg. Secrets
    # come only from the environment.
    bale_token: str = ""
    bale_api_base: str = DEFAULT_BALE_API_BASE
    telegram_bot_token: str = field(default="", repr=False)
    tg_api_id: int = 0
    tg_api_hash: str = field(default="", repr=False)
    worker_api_key: str = field(default="", repr=False)
    #: Local known-good tg://proxy links, tried after the pool's ranking.
    tg_proxies: tuple[str, ...] = field(default=(), repr=False)
    #: Try a direct connection after every proxy failed.
    tg_allow_direct: bool = True
    #: Telethon session file stem of the bot (keeps update state across restarts).
    tg_session_path: str = ""
    tg_health_interval_sec: int = 180
    tg_connect_timeout_sec: int = 20

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
    #: Send branded image cards (price / pre-invoice / invoice) as photos. Off by
    #: default; any rendering or upload failure falls back to the plain text.
    bot_image_cards: bool = False
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
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", ""),
            tg_api_id=_tg_api_id(),
            tg_api_hash=_env("TG_API_HASH", ""),
            worker_api_key=_env("WORKER_API_KEY", ""),
            tg_proxies=tuple(p for p in _env("TG_PROXY", "").replace(";", ",").replace(" ", ",").split(",") if p),
            tg_allow_direct=_env_bool("TG_ALLOW_DIRECT", True),
            tg_session_path=_env("TG_BOT_SESSION", ""),
            tg_health_interval_sec=max(30, _env_int("TG_HEALTH_INTERVAL_SEC", 180)),
            tg_connect_timeout_sec=max(5, _env_int("TG_CONNECT_TIMEOUT_SEC", 20)),
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
            bot_image_cards=_env_bool("BOT_IMAGE_CARDS", False),
            messages_file=_env("BOT_MESSAGES_FILE", ""),
        )

    # --- helpers ---
    def admin_entries(self) -> list[tuple[str | None, str]]:
        """Admin chats as (platform|None, chat_id).

        `ADMIN_CHAT_IDS` accepts `12345` and `bale:12345`; both mean a Bale chat.
        Admin chats exist on Bale only (owner alerts stay on Bale, Phase 7):
        entries for other platforms (e.g. `telegram:12345`) are ignored, and a
        bare id is never matched against a Telegram chat.
        """
        entries: list[tuple[str | None, str]] = []
        for raw in self.admin_chat_ids:
            platform, sep, chat_id = raw.partition(":")
            platform = platform.strip().lower()
            if not sep:
                entries.append(("bale", raw))
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

    @property
    def tg_session_file(self) -> str:
        """Session file stem of the Telegram bot (``.session`` is added by Telethon)."""
        if self.tg_session_path:
            return self.tg_session_path
        return str(Path(self.sqlite_path).resolve().with_name("tg_bot"))

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.tg_api_id and self.tg_api_hash)

    def enabled_platforms(self) -> tuple[str, ...]:
        platforms = []
        if self.bale_token:
            platforms.append("bale")
        if self.telegram_configured:
            platforms.append("telegram")
        return tuple(platforms)
