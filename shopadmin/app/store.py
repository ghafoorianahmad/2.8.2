"""Local SQLite storage for the desktop app's OWN, per-computer data.

This database is completely separate from shopapi's SQLite file. It holds only:

* settings (server address, refresh intervals, notification preferences),
* the username remembered for «مرا به خاطر بسپار» (the token itself is in the
  Windows Credential Manager, see ``credentials.py``),
* a local trail of what was done from this computer.

Staff accounts, passwords and roles live ON THE SERVER (shopapi) and are never
stored here. Customer accounts are likewise only read through the HTTP API.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .logging_setup import get_logger, mask_phone
from .paths import db_path as default_db_path
from .persian import now_utc_iso

log = get_logger("store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remembered_user (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    username   TEXT NOT NULL,
    token      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

#: Left over from versions that kept staff accounts and the shared admin API key
#: on every computer. Removed on open: those secrets must not linger on clients.
LEGACY_TABLES = ("admin_users", "remembered_sessions")
LEGACY_SETTINGS = ("shopapi_api_key",)

DEFAULT_SETTINGS: dict[str, Any] = {
    "shopapi_base_url": "http://127.0.0.1:8000",
    "auto_refresh_seconds": 30,
    "session_timeout_minutes": 30,
    "low_stock_threshold": 5,
    "wizard_completed": False,
    "remember_me": False,
    "notify_desktop": True,
    "notify_sound": True,
    "event_poll_seconds": 15,
    "close_to_tray": True,
    "sazeh_watch": True,
    "sazeh_process_names": "Sazeh Hesab, SazehHesab",
}


#: Long or sensitive values never written to the log in clear.
SECRET_SETTING_KEYS: frozenset[str] = frozenset({"server_cert_pem"})


class Store:
    """Thread-safe wrapper around the local SQLite file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path or default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._drop_legacy_secrets()
        self._ensure_default_settings()

    # ------------------------------------------------------------------ low level
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _drop_legacy_secrets(self) -> None:
        with self._cursor() as cur:
            dropped = []
            for table in LEGACY_TABLES:
                exists = cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if exists:
                    cur.execute(f"DROP TABLE {table}")
                    dropped.append(table)
            for key in LEGACY_SETTINGS:
                if cur.execute("DELETE FROM settings WHERE key=?", (key,)).rowcount:
                    dropped.append(key)
        if dropped:
            if self.path != ":memory:":
                # Rewrite the file so the old hashes/key do not survive in free pages.
                with self._lock:
                    self._conn.execute("VACUUM")
            log.info("removed legacy local accounts/keys: %s", ", ".join(dropped))

    # ------------------------------------------------------------------ settings
    def _ensure_default_settings(self) -> None:
        with self._cursor() as cur:
            for key, value in DEFAULT_SETTINGS.items():
                cur.execute(
                    "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?,?,?)",
                    (key, json.dumps(value, ensure_ascii=False), now_utc_iso()),
                )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return DEFAULT_SETTINGS.get(key, default)
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return row["value"]

    def get_int_setting(self, key: str, default: int, minimum: int = 1, maximum: int = 100000) -> int:
        try:
            value = int(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, payload, now_utc_iso()),
            )
        if key in SECRET_SETTING_KEYS:
            log.info("setting updated: %s=<%d chars>", key, len(str(value)))
        else:
            log.info("setting updated: %s=%s", key, value)

    def all_settings(self) -> dict[str, Any]:
        return {row["key"]: self.get_setting(row["key"]) for row in self._all("SELECT key FROM settings")}

    # ------------------------------------------------------------------ connection
    @property
    def base_url(self) -> str:
        return str(self.get_setting("shopapi_base_url", "") or "").strip().rstrip("/")

    def configure_connection(self, base_url: str, server_cert_pem: str | None = None) -> None:
        self.set_setting("shopapi_base_url", str(base_url).strip().rstrip("/"))
        if server_cert_pem is not None:
            self.set_setting("server_cert_pem", server_cert_pem)

    @property
    def server_cert_pem(self) -> str:
        """The server's own certificate, pinned at setup (public; not a secret)."""
        return str(self.get_setting("server_cert_pem", "") or "")

    def is_configured(self) -> bool:
        return bool(self.base_url and self.get_setting("wizard_completed", False))

    # ------------------------------------------------------------------ remember me
    def save_remembered_user(self, username: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO remembered_user (id, username, token, updated_at) VALUES (1,?,'',?) "
                "ON CONFLICT(id) DO UPDATE SET username=excluded.username, token='', "
                "updated_at=excluded.updated_at",
                (str(username).strip(), now_utc_iso()),
            )

    def get_remembered_user(self) -> Optional[dict]:
        return self._one("SELECT username, updated_at FROM remembered_user WHERE id=1")

    def clear_remembered_user(self) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM remembered_user WHERE id=1")

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, detail: str = "") -> None:
        """Local trail of actions taken from this computer. Never holds secrets."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
                (now_utc_iso(), actor, action, str(detail)[:500]),
            )

    def list_audit(self, limit: int = 200) -> list[dict]:
        return self._all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),))

    @staticmethod
    def new_remember_token() -> str:
        return uuid.uuid4().hex


def masked_phone_for_log(phone: str | None) -> str:
    """Small helper used by callers that log a customer phone."""
    return mask_phone(phone)
