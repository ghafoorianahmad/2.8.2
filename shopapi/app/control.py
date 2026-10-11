"""Hooks that let the hosting launcher expose server control to super admins.

shopapi itself knows nothing about processes, bots or files on disk. The
ShopServer launcher registers what it can offer:

* a restart hook (the process is supervised and comes back with fresh settings),
* status providers (e.g. the bots' per-platform health),
* the settings file (``.env``) and the log file,
* the TLS certificate fingerprint clients pin.

Without a launcher (plain ``uvicorn`` in development) these stay empty and the
endpoints say so instead of pretending.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .util import now_utc

VERSION = "2.0.0"
STARTED_AT = now_utc()


@dataclass
class ControlState:
    restart_hook: Optional[Callable[[], None]] = None
    env_file: Optional[Path] = None
    log_file: Optional[Path] = None
    tls_fingerprint: Optional[str] = None
    providers: dict[str, Callable[[], dict]] = field(default_factory=dict)


STATE = ControlState()
_ENV_LOCK = threading.Lock()


def set_restart_hook(hook: Optional[Callable[[], None]]) -> None:
    STATE.restart_hook = hook


def register_status_provider(name: str, provider: Callable[[], dict]) -> None:
    STATE.providers[name] = provider


def set_files(*, env_file: Optional[Path] = None, log_file: Optional[Path] = None) -> None:
    if env_file is not None:
        STATE.env_file = Path(env_file)
    if log_file is not None:
        STATE.log_file = Path(log_file)


def set_tls_fingerprint(fingerprint: Optional[str]) -> None:
    STATE.tls_fingerprint = fingerprint


def reset() -> None:
    """Tests only."""
    global STATE
    STATE = ControlState()


def provider_status() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, provider in STATE.providers.items():
        try:
            out[name] = provider()
        except Exception as exc:  # noqa: BLE001 - a status page must not crash
            out[name] = {"error": type(exc).__name__}
    return out


# --------------------------------------------------------------------------
# settings that a super admin may change remotely
# --------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"^\d{4,15}:[A-Za-z0-9_-]{20,100}$")
_CHAT_IDS_RE = re.compile(r"^(bale:)?-?\d{1,20}$")
_WAREHOUSES_RE = re.compile(r"^\d{1,9}$")


def _int_range(lo: int, hi: int) -> Callable[[str], Optional[str]]:
    def check(value: str) -> Optional[str]:
        if not re.fullmatch(r"\d{1,9}", value) or not lo <= int(value) <= hi:
            return f"must be a whole number between {lo} and {hi}"
        return None
    return check


def _bool(value: str) -> Optional[str]:
    return None if value in ("true", "false") else "must be true or false"


def _text(max_len: int) -> Callable[[str], Optional[str]]:
    def check(value: str) -> Optional[str]:
        return f"must be at most {max_len} characters" if len(value) > max_len else None
    return check


def _chat_ids(value: str) -> Optional[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not all(_CHAT_IDS_RE.match(p) for p in parts):
        return "use entries like bale:123456, separated by commas"
    return None


def _warehouses(value: str) -> Optional[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return None if all(_WAREHOUSES_RE.match(p) for p in parts) else "use warehouse codes separated by commas"


def _token(value: str) -> Optional[str]:
    return None if value == "" or _TOKEN_RE.match(value) else "does not look like a bot token"


#: key -> (validator, secret). Everything NOT listed here — the accounting
#: connection, ACCOUNTING_WRITE_ENABLED, the API keys, the bind address — can
#: only be changed on the server itself.
EDITABLE: dict[str, tuple[Callable[[str], Optional[str]], bool]] = {
    "BANK_ACCOUNT_TEXT": (_text(500), False),
    "RESERVE_HOURS": (_int_range(1, 168), False),
    "MAX_ORDER_QTY": (_int_range(1, 1_000_000), False),
    "PRICE_LEVEL_BOT": (_int_range(1, 5), False),
    "PRICE_LEVEL_SITE": (_int_range(1, 5), False),
    "STOCK_WAREHOUSES": (_warehouses, False),
    "ALLOW_SHARED_PERSON_CODE": (_bool, False),
    "STAFF_SESSION_HOURS": (_int_range(1, 72), False),
    "STAFF_REMEMBER_DAYS": (_int_range(1, 30), False),
    "LOGIN_MAX_ATTEMPTS": (_int_range(3, 20), False),
    "LOGIN_LOCK_MINUTES": (_int_range(1, 1440), False),
    "ADMIN_CHAT_IDS": (_chat_ids, False),
    "ADMIN_SWEEP_SECONDS": (_int_range(10, 3600), False),
    "BALE_TOKEN": (_token, True),
    # TELEGRAM_TOKEN / TELEGRAM_PROXY / PROXY_URL were removed with the old
    # Telegram Bot-API channel (2026-10-11): they are refused as unknown keys.
}


def validate_settings(changes: dict[str, str]) -> dict[str, str]:
    """Return {key: problem} for every rejected entry (empty = all fine)."""
    problems: dict[str, str] = {}
    for key, value in changes.items():
        if key not in EDITABLE:
            problems[key] = "cannot be changed remotely"
            continue
        if not isinstance(value, str) or any(ch in value for ch in "\r\n\x00"):
            problems[key] = "must be a single line of text"
            continue
        problem = EDITABLE[key][0](value.strip())
        if problem:
            problems[key] = problem
    return problems


def _quote(value: str) -> str:
    if value == "" or re.fullmatch(r"[A-Za-z0-9_.:/@,+-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_env_values() -> dict[str, str]:
    path = STATE.env_file
    values: dict[str, str] = {}
    if path is None or not path.exists():
        return values
    from dotenv import dotenv_values

    for key, value in dotenv_values(path).items():
        if key and value is not None:
            values[key] = value
    return values


def current_settings() -> dict[str, dict]:
    """Editable keys with their values; secrets only report whether they are set."""
    values = read_env_values()
    out: dict[str, dict] = {}
    for key, (_validator, secret) in EDITABLE.items():
        value = values.get(key, os.environ.get(key, ""))
        out[key] = {"secret": secret, "set": bool(value)} if secret else \
            {"secret": False, "value": value}
    return out


def write_env_values(changes: dict[str, str]) -> None:
    """Update keys in ``.env`` in place, keeping comments and every other line.

    Written to a temporary file and swapped in, so a crash never leaves a
    half-written configuration behind.
    """
    path = STATE.env_file
    if path is None:
        raise RuntimeError("no settings file registered")
    with _ENV_LOCK:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        pending = {k: v.strip() for k, v in changes.items()}
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
            if key in pending:
                out.append(f"{key}={_quote(pending.pop(key))}")
            else:
                out.append(line)
        for key, value in pending.items():
            out.append(f"{key}={_quote(value)}")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def tail_log(lines: int) -> list[str]:
    path = STATE.log_file
    if path is None or not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 512 * 1024))
        data = handle.read().decode("utf-8", errors="replace")
    return data.splitlines()[-lines:]
