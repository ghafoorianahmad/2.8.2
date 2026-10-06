"""Per-platform health, for the server status page in ShopAdmin.

Only states and times are kept — never a token, a chat id or message text.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_STATUS: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entry(platform: str) -> dict:
    return _STATUS.setdefault(platform, {
        "running": False, "started_at": None, "last_ok_at": None,
        "last_error_at": None, "last_error": None, "consecutive_errors": 0,
    })


def mark_started(platform: str) -> None:
    with _LOCK:
        entry = _entry(platform)
        entry.update(running=True, started_at=_now(), consecutive_errors=0)


def mark_stopped(platform: str) -> None:
    with _LOCK:
        _entry(platform)["running"] = False


def mark_ok(platform: str) -> None:
    with _LOCK:
        entry = _entry(platform)
        entry["last_ok_at"] = _now()
        entry["consecutive_errors"] = 0


def mark_error(platform: str, error: str) -> None:
    with _LOCK:
        entry = _entry(platform)
        entry["last_error_at"] = _now()
        entry["last_error"] = str(error)[:200]
        entry["consecutive_errors"] = int(entry["consecutive_errors"]) + 1


def snapshot() -> dict[str, dict]:
    with _LOCK:
        return {name: dict(values) for name, values in _STATUS.items()}


def reset() -> None:
    with _LOCK:
        _STATUS.clear()
