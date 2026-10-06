"""Local SQLite storage for the desktop app's OWN data.

This database is completely separate from shopapi's SQLite file. It holds:

* internal admin users of this desktop app (a handful of people),
* settings (shopapi address, API key, intervals),
* a local audit trail of privileged actions.

Customer accounts are NOT stored here — they live in shopapi and are only ever
read through the HTTP API.
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
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN
                  ('super_admin','admin','operator','viewer')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    last_login_at TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

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

-- "مرا به خاطر بسپار": a short-lived session token per user. The password is
-- never stored; only a hash of a random token plus an expiry.
CREATE TABLE IF NOT EXISTS remembered_sessions (
    user_id    INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "shopapi_base_url": "http://127.0.0.1:8000",
    "shopapi_api_key": "",
    "auto_refresh_seconds": 30,
    "session_timeout_minutes": 30,
    "low_stock_threshold": 5,
    "wizard_completed": False,
    "remember_me": False,
}

# The API key is only ever written/read through these helpers; it is never
# logged and never included in an audit detail string.
SECRET_SETTING_KEYS = frozenset({"shopapi_api_key"})


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

    @property
    def api_key(self) -> str:
        return str(self.get_setting("shopapi_api_key", "") or "")

    def configure_connection(self, base_url: str, api_key: str) -> None:
        self.set_setting("shopapi_base_url", str(base_url).strip().rstrip("/"))
        self.set_setting("shopapi_api_key", str(api_key).strip())

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.get_setting("wizard_completed", False))

    # ------------------------------------------------------------------ admin users
    def count_admin_users(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM admin_users")
        return int(row["n"]) if row else 0

    def count_active_super_admins(self, exclude_user_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM admin_users WHERE role='super_admin' AND is_active=1"
        params: tuple = ()
        if exclude_user_id is not None:
            sql += " AND id <> ?"
            params = (exclude_user_id,)
        row = self._one(sql, params)
        return int(row["n"]) if row else 0

    def list_admin_users(self) -> list[dict]:
        return self._all("SELECT * FROM admin_users ORDER BY role, username COLLATE NOCASE")

    def get_admin_user(self, user_id: int) -> Optional[dict]:
        return self._one("SELECT * FROM admin_users WHERE id=?", (user_id,))

    def get_admin_user_by_username(self, username: str) -> Optional[dict]:
        row = self._one(
            "SELECT * FROM admin_users WHERE username = ? COLLATE NOCASE",
            (str(username or "").strip(),),
        )
        return row

    def create_admin_user(
        self,
        username: str,
        full_name: str,
        password_hash: str,
        role: str,
        is_active: bool = True,
    ) -> dict:
        ts = now_utc_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, role, is_active, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    str(username).strip(),
                    str(full_name).strip(),
                    password_hash,
                    role,
                    1 if is_active else 0,
                    ts,
                    ts,
                ),
            )
            new_id = cur.lastrowid
        log.info("internal admin user created: id=%s role=%s", new_id, role)
        return self.get_admin_user(int(new_id))  # type: ignore[arg-type]

    def update_admin_user(
        self,
        user_id: int,
        *,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> Optional[dict]:
        fields: list[str] = []
        params: list[Any] = []
        if full_name is not None:
            fields.append("full_name=?")
            params.append(str(full_name).strip())
        if role is not None:
            fields.append("role=?")
            params.append(role)
        if is_active is not None:
            fields.append("is_active=?")
            params.append(1 if is_active else 0)
        if not fields:
            return self.get_admin_user(user_id)
        fields.append("updated_at=?")
        params.append(now_utc_iso())
        params.append(user_id)
        with self._cursor() as cur:
            cur.execute(f"UPDATE admin_users SET {', '.join(fields)} WHERE id=?", tuple(params))
        return self.get_admin_user(user_id)

    def set_admin_password(self, user_id: int, password_hash: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE admin_users SET password_hash=?, failed_attempts=0, locked_until=NULL, "
                "updated_at=? WHERE id=?",
                (password_hash, now_utc_iso(), user_id),
            )
        log.info("password changed for internal admin user id=%s", user_id)

    def delete_admin_user(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id=?", (user_id,))
        log.info("internal admin user deleted: id=%s", user_id)

    def register_failed_attempt(self, user_id: int, max_attempts: int, lock_minutes: int) -> dict:
        """Increment the failure counter and lock the account when it exceeds the limit."""
        from datetime import datetime, timedelta, timezone

        user = self.get_admin_user(user_id)
        if user is None:
            return {}
        attempts = int(user["failed_attempts"]) + 1
        locked_until = None
        if attempts >= max_attempts:
            locked_until = (
                datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
            ).isoformat(timespec="seconds")
            log.warning("internal admin user id=%s locked after %s attempts", user_id, attempts)
        with self._cursor() as cur:
            cur.execute(
                "UPDATE admin_users SET failed_attempts=?, locked_until=?, updated_at=? WHERE id=?",
                (attempts, locked_until, now_utc_iso(), user_id),
            )
        return self.get_admin_user(user_id) or {}

    def clear_failed_attempts(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE admin_users SET failed_attempts=0, locked_until=NULL, last_login_at=?, "
                "updated_at=? WHERE id=?",
                (now_utc_iso(), now_utc_iso(), user_id),
            )

    # ------------------------------------------------------------------ remember me
    def save_remembered_user(self, username: str, token: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO remembered_user (id, username, token, updated_at) VALUES (1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET username=excluded.username, token=excluded.token, "
                "updated_at=excluded.updated_at",
                (str(username).strip(), token, now_utc_iso()),
            )

    def get_remembered_user(self) -> Optional[dict]:
        return self._one("SELECT * FROM remembered_user WHERE id=1")

    def clear_remembered_user(self) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM remembered_user WHERE id=1")

    # ---- remember-me sessions (never store the password) ------------------
    def save_session_token(self, user_id: int, token_hash: str, expires_at: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO remembered_sessions (user_id, token_hash, expires_at, created_at) "
                "VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "token_hash=excluded.token_hash, expires_at=excluded.expires_at, "
                "created_at=excluded.created_at",
                (int(user_id), token_hash, expires_at, now_utc_iso()),
            )

    def get_session_token(self, user_id: int) -> Optional[dict]:
        return self._one("SELECT * FROM remembered_sessions WHERE user_id=?", (int(user_id),))

    def clear_session_token(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM remembered_sessions WHERE user_id=?", (int(user_id),))

    def clear_all_session_tokens(self) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM remembered_sessions")

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, detail: str = "") -> None:
        """Local audit trail. ``detail`` must never contain secrets."""
        safe = detail
        for secret_key in SECRET_SETTING_KEYS:
            value = str(self.get_setting(secret_key, "") or "")
            if value:
                safe = safe.replace(value, "<secret>")
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
                (now_utc_iso(), actor, action, safe[:500]),
            )

    def list_audit(self, limit: int = 200) -> list[dict]:
        return self._all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),))

    @staticmethod
    def new_remember_token() -> str:
        return uuid.uuid4().hex


def masked_phone_for_log(phone: str | None) -> str:
    """Small helper used by callers that log a customer phone."""
    return mask_phone(phone)
