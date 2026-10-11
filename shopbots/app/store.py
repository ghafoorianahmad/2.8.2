"""Bot state in a small SQLite file.

Only bot state lives here: the last processed update id per platform, the
conversation state per (platform, chat_id), the shopping cart, which pending
users/receipts were already announced to admins, and the customer chat that
belongs to each announced item (so the customer can be notified). No accounting
data and no personal data beyond the chat identity the conversation needs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_state (
    platform TEXT PRIMARY KEY,
    last_update_id INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversations (
    platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, chat_id)
);

CREATE TABLE IF NOT EXISTS carts (
    platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    kala_code INTEGER NOT NULL,
    variant_id INTEGER NOT NULL DEFAULT 0,   -- phone color (0 = none)
    name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL,
    PRIMARY KEY (platform, chat_id, kala_code, variant_id)
);

CREATE TABLE IF NOT EXISTS admin_notices (
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    announced_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    order_id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    file_ref TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._migrate_carts()
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _migrate_carts(self) -> None:
        """Carts of an older version have no color column: rename the table so
        SCHEMA recreates it, then copy the rows (SQLite cannot change a key)."""
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(carts)")}
        if not columns or "variant_id" in columns:
            return
        self._conn.execute("ALTER TABLE carts RENAME TO carts_old")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT INTO carts (platform, chat_id, kala_code, variant_id, name, qty, unit_price) "
            "SELECT platform, chat_id, kala_code, 0, name, qty, unit_price FROM carts_old"
        )
        self._conn.execute("DROP TABLE carts_old")

    # ---- low level -------------------------------------------------------
    def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ---- update ids ------------------------------------------------------
    def get_last_update_id(self, platform: str) -> int:
        with self._lock:
            row = self._fetchone(
                "SELECT last_update_id FROM platform_state WHERE platform=?", (platform,)
            )
            return int(row["last_update_id"]) if row else 0

    def set_last_update_id(self, platform: str, update_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO platform_state (platform, last_update_id) VALUES (?,?) "
                "ON CONFLICT(platform) DO UPDATE SET last_update_id=excluded.last_update_id",
                (platform, int(update_id)),
            )
            self._conn.commit()

    def is_new_update(self, platform: str, update_id: int) -> bool:
        """True when this update id has never been processed."""
        return int(update_id) > self.get_last_update_id(platform)

    # ---- conversation ----------------------------------------------------
    def get_conversation(self, platform: str, chat_id: str | int) -> tuple[str, dict]:
        with self._lock:
            row = self._fetchone(
                "SELECT state, data FROM conversations WHERE platform=? AND chat_id=?",
                (platform, str(chat_id)),
            )
            if row is None:
                return "", {}
            try:
                data = json.loads(row["data"] or "{}")
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            return row["state"], data

    def set_conversation(
        self, platform: str, chat_id: str | int, state: str, data: dict
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (platform, chat_id, state, data, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(platform, chat_id) DO UPDATE SET "
                "state=excluded.state, data=excluded.data, updated_at=excluded.updated_at",
                (platform, str(chat_id), state, json.dumps(data, ensure_ascii=False), _now()),
            )
            self._conn.commit()

    def clear_conversation(self, platform: str, chat_id: str | int) -> None:
        self.set_conversation(platform, chat_id, "", {})

    # ---- cart ------------------------------------------------------------
    def cart_add(
        self,
        platform: str,
        chat_id: str | int,
        kala_code: int,
        name: str,
        qty: float,
        unit_price: float,
        variant_id: int = 0,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO carts (platform, chat_id, kala_code, variant_id, name, qty, "
                "unit_price) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(platform, chat_id, kala_code, variant_id) DO UPDATE SET "
                "qty=carts.qty+excluded.qty, name=excluded.name, unit_price=excluded.unit_price",
                (platform, str(chat_id), int(kala_code), int(variant_id or 0), name,
                 float(qty), float(unit_price)),
            )
            self._conn.commit()

    def cart_set_qty(
        self, platform: str, chat_id: str | int, kala_code: int, qty: float,
        variant_id: int = 0,
    ) -> None:
        with self._lock:
            if qty <= 0:
                self.cart_remove(platform, chat_id, kala_code, variant_id)
                return
            self._conn.execute(
                "UPDATE carts SET qty=? WHERE platform=? AND chat_id=? AND kala_code=? "
                "AND variant_id=?",
                (float(qty), platform, str(chat_id), int(kala_code), int(variant_id or 0)),
            )
            self._conn.commit()

    def cart_remove(
        self, platform: str, chat_id: str | int, kala_code: int, variant_id: int = 0
    ) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM carts WHERE platform=? AND chat_id=? AND kala_code=? "
                "AND variant_id=?",
                (platform, str(chat_id), int(kala_code), int(variant_id or 0)),
            )
            self._conn.commit()

    def cart_clear(self, platform: str, chat_id: str | int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM carts WHERE platform=? AND chat_id=?", (platform, str(chat_id))
            )
            self._conn.commit()

    def cart_list(self, platform: str, chat_id: str | int) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT kala_code, variant_id, name, qty, unit_price FROM carts "
                "WHERE platform=? AND chat_id=? ORDER BY kala_code, variant_id",
                (platform, str(chat_id)),
            )

    # ---- admin notices ---------------------------------------------------
    def is_announced(self, kind: str, ref_id: int) -> bool:
        with self._lock:
            return (
                self._fetchone(
                    "SELECT 1 AS x FROM admin_notices WHERE kind=? AND ref_id=?",
                    (kind, int(ref_id)),
                )
                is not None
            )

    def mark_announced(
        self,
        kind: str,
        ref_id: int,
        platform: str = "",
        chat_id: str | int = "",
        payload: dict | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO admin_notices "
                "(kind, ref_id, platform, chat_id, payload, announced_at) VALUES (?,?,?,?,?,?)",
                (
                    kind,
                    int(ref_id),
                    platform,
                    str(chat_id),
                    json.dumps(payload or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            self._conn.commit()

    def get_notice(self, kind: str, ref_id: int) -> dict | None:
        with self._lock:
            row = self._fetchone(
                "SELECT platform, chat_id, payload FROM admin_notices WHERE kind=? AND ref_id=?",
                (kind, int(ref_id)),
            )
            if row is None:
                return None
            try:
                row["payload"] = json.loads(row["payload"] or "{}")
            except ValueError:
                row["payload"] = {}
            return row

    # ---- small key/value state (e.g. the shopapi event cursor) ------------
    def get_value(self, key: str) -> str | None:
        with self._lock:
            row = self._fetchone("SELECT value FROM kv WHERE key=?", (key,))
            return row["value"] if row else None

    def set_value(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self._conn.commit()

    # ---- receipt file references (needed to show the photo to admins) ----
    def save_receipt(
        self, order_id: int, platform: str, chat_id: str | int, file_ref: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO receipts (order_id, platform, chat_id, file_ref, created_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(order_id) DO UPDATE SET "
                "platform=excluded.platform, chat_id=excluded.chat_id, "
                "file_ref=excluded.file_ref, created_at=excluded.created_at",
                (int(order_id), platform, str(chat_id), file_ref, _now()),
            )
            self._conn.commit()

    def get_receipt(self, order_id: int) -> dict | None:
        with self._lock:
            return self._fetchone("SELECT * FROM receipts WHERE order_id=?", (int(order_id),))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
