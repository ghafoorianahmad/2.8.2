"""Configuration for the Telegram price/proxy worker (shoptg).

Read from ``shoptg/.env`` (or the file named by ``SHOPTG_ENV``) and the process
environment. ``TG_API_HASH``, ``WORKER_API_KEY`` and proxy secrets live only
here; they are never logged, printed or put into exception messages.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_PRICE_CHANNEL = "AbrishamiiPhoneMashhad"
#: v2.9.0: public channel the proxy pool is filled from (daily).
DEFAULT_PROXY_CHANNEL = "ProxyMTProto"

#: v2.9.0 (owner's decision, temporary): the PUBLIC api_id / api_hash that the
#: official Telegram Desktop app ships with (open source, telegramdesktop/tdesktop),
#: used for a separate secondary account until the owner's own my.telegram.org
#: app is entered in «تنظیمات سرور». Telegram may restrict accounts that use these
#: from other software; the device parameters below match Telegram Desktop.
TDESKTOP_API_ID = 2040
TDESKTOP_API_HASH = "b18441a1ff607e10a989891a5462e627"
API_PRESETS = ("tdesktop", "custom")

#: InitConnection parameters per preset (device_model, system_version, app_version,
#: lang_code, system_lang_code, lang_pack). TG_DEVICE_MODEL / TG_SYSTEM_VERSION /
#: TG_APP_VERSION override the first three.
DEVICE_PRESETS: dict[str, dict[str, str]] = {
    "tdesktop": {"device_model": "Desktop", "system_version": "Windows 10",
                 "app_version": "5.12.3 x64", "lang_code": "en", "system_lang_code": "en-US",
                 "lang_pack": "tdesktop"},
    "custom": {"device_model": "ShopServer", "system_version": "Windows",
               "app_version": "shoptg 1.1", "lang_code": "fa", "system_lang_code": "fa",
               "lang_pack": ""},
}


def default_data_dir() -> Path:
    root = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(root) / "ShopServer" / "shoptg"


def dotenv_disabled() -> bool:
    """Started by ShopSystem: every setting comes in the environment."""
    return os.environ.get("SHOPTG_NO_DOTENV") == "1"


def load_env_file() -> None:
    if dotenv_disabled():
        return
    explicit = os.environ.get("SHOPTG_ENV", "").strip()
    load_dotenv(Path(explicit) if explicit else BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


_CHANNEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def channel_username(raw: str) -> str:
    """``https://t.me/Name``, ``t.me/Name``, ``@Name`` or ``Name`` -> ``Name``."""
    value = (raw or "").strip()
    value = re.sub(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?", "", value, flags=re.I)
    value = value.lstrip("@").split("/")[0].split("?")[0]
    if not _CHANNEL.match(value):
        raise ValueError(f"not a public channel username: {raw!r}")
    return value


def _split(raw: str) -> list[str]:
    return [part for part in re.split(r"[\s,;]+", raw or "") if part]


def resolve_preset(raw: str, api_id: str) -> str:
    """``TG_API_PRESET``: tdesktop / custom; unset = custom when TG_API_ID is set."""
    value = (raw or "").strip().lower()
    if value in API_PRESETS:
        return value
    if value:
        raise ValueError("TG_API_PRESET must be tdesktop or custom")
    return "custom" if api_id else "tdesktop"


@dataclass
class Settings:
    api_id: int = 0
    api_hash: str = field(default="", repr=False)
    #: v2.9.0: "tdesktop" = the public Telegram Desktop key (temporary), "custom" = own
    api_preset: str = "custom"
    device_model: str = ""
    system_version: str = ""
    app_version: str = ""
    price_channel: str = DEFAULT_PRICE_CHANNEL
    proxy_channels: list[str] = field(default_factory=list)
    #: Local known-good proxies (tg://proxy links), tried after the pool.
    local_proxies: list[str] = field(default_factory=list, repr=False)
    #: Try a direct connection after every proxy failed.
    allow_direct: bool = True
    data_dir: Path = field(default_factory=default_data_dir)
    #: Windows account (Phase 4 service) that may read the session file.
    service_account: str = ""

    shopapi_base_url: str = "http://127.0.0.1:8000"
    shopapi_ca_file: str = ""
    worker_api_key: str = field(default="", repr=False)

    #: Price channel poll (decision 2026-10-14: every 10 min; sales windows follow the list).
    price_interval_sec: int = 10 * 60
    #: v2.9.0: the proxy channel is read every day (was weekly)
    proxy_collect_hours: int = 24
    #: working proxies the pool should hold; new links are tested until it does
    pool_size: int = 5
    #: at most this many new links are tested per collection (anonymous clients)
    proxy_test_max: int = 40
    #: read the channel's public web preview (t.me/s/...) when not logged in / no proxy
    web_preview: bool = True
    health_interval_sec: int = 180
    probe_interval_sec: int = 60 * 60
    probe_max: int = 15
    connect_timeout_sec: int = 20
    #: How long Telegram may be unreachable before the owner is alerted.
    unreachable_alert_sec: int = 15 * 60
    pdf_max_bytes: int = 10 * 1024 * 1024
    #: First run (no cursor yet): only this many newest messages are scanned.
    first_run_scan: int = 30
    #: log file (ShopSystem: in the server's data folder, where the service may write)
    log_file: str = ""

    @property
    def session_file(self) -> Path:
        return self.data_dir / "tg_session.dpapi"

    @property
    def proxy_collect_days(self) -> float:
        return self.proxy_collect_hours / 24

    def device(self) -> dict[str, str]:
        """InitConnection parameters (no secrets) for the chosen preset."""
        out = dict(DEVICE_PRESETS.get(self.api_preset, DEVICE_PRESETS["custom"]))
        for key in ("device_model", "system_version", "app_version"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        return out

    def missing(self) -> list[str]:
        """Names of required settings that are empty (never their values)."""
        out = []
        if self.api_preset != "tdesktop" and not self.api_id:
            out.append("TG_API_ID")
        if self.api_preset != "tdesktop" and not self.api_hash:
            out.append("TG_API_HASH")
        if not self.worker_api_key:
            out.append("WORKER_API_KEY")
        return out

    @classmethod
    def from_env(cls, *, load_file: bool = True) -> "Settings":
        if load_file:
            load_env_file()
        api_id_raw = _env("TG_API_ID")
        if api_id_raw and not api_id_raw.isdigit():
            raise ValueError("TG_API_ID must be a number")
        preset = resolve_preset(_env("TG_API_PRESET"), api_id_raw)
        if preset == "tdesktop":
            api_id, api_hash = TDESKTOP_API_ID, TDESKTOP_API_HASH
        else:
            api_id, api_hash = int(api_id_raw or 0), _env("TG_API_HASH")
        data_dir = _env("TG_DATA_DIR")
        channels_raw = os.getenv("TG_PROXY_CHANNELS")
        if channels_raw is None:
            channels_raw = DEFAULT_PROXY_CHANNEL
        channels_raw = "" if channels_raw.strip().lower() in ("-", "none", "off") else channels_raw
        collect_hours = _env_int("TG_PROXY_COLLECT_HOURS", 0)
        if not collect_hours:
            days = _env("TG_PROXY_COLLECT_DAYS")
            collect_hours = int(days) * 24 if days.isdigit() else 24
        return cls(
            api_id=api_id,
            api_hash=api_hash,
            api_preset=preset,
            device_model=_env("TG_DEVICE_MODEL")[:64],
            system_version=_env("TG_SYSTEM_VERSION")[:64],
            app_version=_env("TG_APP_VERSION")[:64],
            price_channel=channel_username(_env("TG_PRICE_CHANNEL") or DEFAULT_PRICE_CHANNEL),
            proxy_channels=[channel_username(c) for c in _split(channels_raw)],
            local_proxies=_split(_env("TG_PROXY")),
            allow_direct=_env("TG_ALLOW_DIRECT", "true").lower() in ("1", "true", "yes", "on"),
            data_dir=Path(os.path.expandvars(data_dir)) if data_dir else default_data_dir(),
            service_account=_env("TG_SERVICE_ACCOUNT"),
            shopapi_base_url=_env("SHOPAPI_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            shopapi_ca_file=_env("SHOPAPI_CA_FILE"),
            worker_api_key=_env("WORKER_API_KEY"),
            price_interval_sec=max(300, _env_int("TG_PRICE_INTERVAL_MIN", 10) * 60),
            proxy_collect_hours=max(1, collect_hours),
            pool_size=min(50, max(1, _env_int("TG_PROXY_POOL_SIZE", 5))),
            proxy_test_max=min(200, max(1, _env_int("TG_PROXY_TEST_MAX", 40))),
            web_preview=_env("TG_PROXY_WEB_PREVIEW", "true").lower() in ("1", "true", "yes", "on"),
            log_file=_env("TG_LOG_FILE"),
            health_interval_sec=max(30, _env_int("TG_HEALTH_INTERVAL_SEC", 180)),
            probe_interval_sec=max(600, _env_int("TG_PROBE_INTERVAL_MIN", 60) * 60),
            probe_max=max(1, _env_int("TG_PROBE_MAX", 15)),
            connect_timeout_sec=max(5, _env_int("TG_CONNECT_TIMEOUT_SEC", 20)),
            unreachable_alert_sec=max(60, _env_int("TG_UNREACHABLE_ALERT_MIN", 15) * 60),
            pdf_max_bytes=_env_int("TG_PDF_MAX_BYTES", 10 * 1024 * 1024),
        )
