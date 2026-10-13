"""Own SQLite database (created at startup; never inside the accounting DB).

Uses a single shared connection guarded by a lock so that in-memory databases
work too and small deployments stay simple.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .util import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL CHECK (platform IN ('bale','telegram','web')),
    chat_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected')),
    person_code INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (platform, chat_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN
        ('awaiting_payment','receipt_uploaded','approved','rejected',
         'written','cancelled','expired')),
    price_level INTEGER NOT NULL,
    total REAL NOT NULL,
    reserve_until TEXT,
    accounting_order_no INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    kala_code INTEGER NOT NULL,
    name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    receipt_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted','approved','rejected')),
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staff_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('super_admin','admin','operator','viewer')),
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS staff_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    client TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref_id INTEGER,
    actor TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON staff_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS shop_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

-- Distributor price lists (REQUIREMENTS §5). Prices in the PDF unit
-- (thousand Toman); price_rial = the customer price after the §4 rules.
CREATE TABLE IF NOT EXISTS price_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_date TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('active','held','rejected','superseded','failed')),
    reason TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0,
    file_name TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    decided_at TEXT,
    decided_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS price_list_rows (
    list_id INTEGER NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    block INTEGER NOT NULL,
    section TEXT NOT NULL,
    description TEXT NOT NULL,
    kind TEXT NOT NULL,
    color TEXT NOT NULL,
    naghd INTEGER,
    raval INTEGER,
    price_rial INTEGER,
    PRIMARY KEY (list_id, row_key)
);

-- PDF row (by key) -> our product + display color, or "ignore" (not sold).
CREATE TABLE IF NOT EXISTS price_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL CHECK (action IN ('map','ignore')),
    kala_code INTEGER,
    color_label TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT '',
    CHECK (action = 'ignore' OR kala_code IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_mappings_kala ON price_mappings(kala_code);

-- "Order/inquiry for an unavailable item" (REQUIREMENTS §4).
CREATE TABLE IF NOT EXISTS inquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kala_code INTEGER NOT NULL,
    mapping_id INTEGER,
    product_name TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- MTProto proxy pool (REQUIREMENTS §6).
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    secret TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK (state IN ('probation','main','retired','disabled')),
    added_at TEXT NOT NULL,
    promoted_at TEXT,
    retired_at TEXT,
    last_ok_at TEXT,
    last_fail_at TEXT,
    last_checked_at TEXT,
    last_latency_ms INTEGER,
    UNIQUE (host, port, secret)
);

CREATE TABLE IF NOT EXISTS proxy_days (
    proxy_id INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    fail INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (proxy_id, day)
);

-- Site catalog models (REQUIREMENTS §9a): permanent slug -> accounting products.
-- hidden = 1: the nightly check lost a product; customers never see the model
-- until the owner confirms it again.
CREATE TABLE IF NOT EXISTS catalog_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '',
    hidden INTEGER NOT NULL DEFAULT 0,
    hidden_reason TEXT NOT NULL DEFAULT '',
    hidden_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

-- One accounting product per row; a product belongs to one model only.
-- state: ok | drifted (name changed a little, still shown) | missing (gone or
-- renamed beyond recognition; the model is hidden). candidates = JSON.
CREATE TABLE IF NOT EXISTS catalog_model_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL REFERENCES catalog_models(id) ON DELETE CASCADE,
    kala_code INTEGER NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    confirmed_name TEXT NOT NULL,
    current_name TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'ok' CHECK (state IN ('ok','drifted','missing')),
    score REAL,
    candidates TEXT NOT NULL DEFAULT '[]',
    sort INTEGER NOT NULL DEFAULT 0,
    confirmed_at TEXT NOT NULL,
    confirmed_by TEXT NOT NULL DEFAULT '',
    checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_items_model ON catalog_model_items(model_id);

-- Idempotency-Key of POST /orders: same key + same customer = the original order.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency_keys(expires_at);
"""

#: Columns added after the first release: (table, column, declaration).
#: SQLite cannot alter a CHECK, so tracking lives in extra columns, not statuses.
MIGRATIONS = (
    ("orders", "invoice_state", "TEXT"),        # NULL | 'partial' | 'full'
    ("orders", "invoiced_qty", "REAL"),
    ("orders", "invoiced_at", "TEXT"),
    ("orders", "shipped_at", "TEXT"),
    ("payments", "file_name", "TEXT"),          # stored receipt image (receipts dir)
    ("payments", "content_type", "TEXT"),
    ("payments", "created_at", "TEXT"),
    ("order_items", "variant_id", "INTEGER"),   # price_mappings.id (phone color)
    ("order_items", "variant", "TEXT"),         # the color shown to the customer
)

# Orders in these statuses hold a stock reservation.
RESERVING_STATUSES = ("awaiting_payment", "receipt_uploaded")
#: Orders that still count against a pending customer's limits.
OPEN_STATUSES = ("awaiting_payment", "receipt_uploaded", "approved")


class OwnDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        for table, column, decl in MIGRATIONS:
            existing = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ---- low level ----
    def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _commit(self) -> None:
        self._conn.commit()

    # ---- users ----
    def register_user(self, platform: str, chat_id: str, name: str, phone: str) -> dict:
        with self._lock:
            existing = self._fetchone(
                "SELECT * FROM users WHERE platform=? AND chat_id=?", (platform, chat_id)
            )
            if existing is not None:
                return existing
            self._conn.execute(
                "INSERT INTO users (platform, chat_id, name, phone, status, created_at) "
                "VALUES (?,?,?,?,'pending',?)",
                (platform, chat_id, name, phone, now_iso()),
            )
            self._commit()
            row = self._conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            return self._fetchone("SELECT * FROM users WHERE id=?", (row["id"],))

    def get_user_by_platform(self, platform: str, chat_id: str) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT * FROM users WHERE platform=? AND chat_id=?", (platform, chat_id)
            )

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._lock:
            return self._fetchone("SELECT * FROM users WHERE id=?", (user_id,))

    def get_user_by_person_code(self, person_code: int) -> dict | None:
        """Return an approved user already linked to this accounting person code."""
        with self._lock:
            return self._fetchone(
                "SELECT * FROM users WHERE person_code=? AND status='approved' "
                "ORDER BY id LIMIT 1",
                (person_code,),
            )

    def list_users(self, status_filter: str | None = None) -> list[dict]:
        with self._lock:
            if status_filter:
                return self._fetchall(
                    "SELECT * FROM users WHERE status=? ORDER BY id", (status_filter,)
                )
            return self._fetchall("SELECT * FROM users ORDER BY id")

    def set_user_approved(self, user_id: int, person_code: int) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET status='approved', person_code=? WHERE id=?",
                (person_code, user_id),
            )
            self._commit()
            return self.get_user_by_id(user_id)

    def update_user_contact(self, user_id: int, name: str | None = None,
                            phone: str | None = None) -> dict:
        with self._lock:
            if name:
                self._conn.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
            if phone:
                self._conn.execute("UPDATE users SET phone=? WHERE id=?", (phone, user_id))
            self._commit()
            return self.get_user_by_id(user_id)

    def open_order_totals(self, user_id: int) -> tuple[float, float]:
        """(sum of totals, sum of quantities) of the user's open orders."""
        with self._lock:
            row = self._fetchone(
                "SELECT COALESCE(SUM(o.total),0) AS total, "
                "COALESCE((SELECT SUM(oi.qty) FROM order_items oi JOIN orders o2 "
                "ON o2.id = oi.order_id WHERE o2.user_id=? AND o2.status IN (?,?,?)),0) AS qty "
                "FROM orders o WHERE o.user_id=? AND o.status IN (?,?,?)",
                (user_id,) + OPEN_STATUSES + (user_id,) + OPEN_STATUSES,
            )
            return float(row["total"]), float(row["qty"])

    def set_user_status(self, user_id: int, status_value: str) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET status=? WHERE id=?", (status_value, user_id)
            )
            self._commit()
            return self.get_user_by_id(user_id)

    # ---- orders ----
    def create_order(
        self,
        user_id: int,
        price_level: int,
        total: float,
        reserve_until: str,
        items: list[tuple[int, str, float, float]],
    ) -> dict:
        """items: (kala_code, name, qty, unit_price[, variant_id, variant])."""
        with self._lock:
            ts = now_iso()
            self._conn.execute(
                "INSERT INTO orders (user_id, status, price_level, total, reserve_until, "
                "created_at, updated_at) VALUES (?,'awaiting_payment',?,?,?,?,?)",
                (user_id, price_level, total, reserve_until, ts, ts),
            )
            row = self._conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            order_id = row["id"]
            for item in items:
                kala_code, name, qty, unit_price = item[:4]
                variant_id = item[4] if len(item) > 4 else None
                variant = item[5] if len(item) > 5 else None
                self._conn.execute(
                    "INSERT INTO order_items (order_id, kala_code, name, qty, unit_price, "
                    "variant_id, variant) VALUES (?,?,?,?,?,?,?)",
                    (order_id, kala_code, name, qty, unit_price, variant_id, variant),
                )
            self._commit()
            return self.get_order(order_id)

    def find_idempotent(self, key: str) -> dict | None:
        """{'user_id', 'order_id'} of a live (unexpired) key; expired keys are purged."""
        with self._lock:
            self._conn.execute("DELETE FROM idempotency_keys WHERE expires_at<=?", (now_iso(),))
            return self._fetchone(
                "SELECT user_id, order_id FROM idempotency_keys WHERE key=?", (key,)
            )

    def save_idempotent(self, key: str, user_id: int, order_id: int, expires_at: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys (key, user_id, order_id, created_at, "
                "expires_at) VALUES (?,?,?,?,?)",
                (key, user_id, order_id, now_iso(), expires_at),
            )
            self._commit()

    def get_order(self, order_id: int) -> dict | None:
        with self._lock:
            order = self._fetchone(
                "SELECT o.*, u.person_code AS user_person_code, u.status AS user_status, "
                "EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.id "
                "AND p.file_name IS NOT NULL) AS has_receipt "
                "FROM orders o JOIN users u ON u.id = o.user_id WHERE o.id=?",
                (order_id,),
            )
            if order is None:
                return None
            order["customer_pending"] = order.get("user_status") != "approved"
            order["items"] = self._fetchall(
                "SELECT kala_code, name, qty, unit_price, variant_id, variant FROM order_items "
                "WHERE order_id=? ORDER BY id",
                (order_id,),
            )
            return order

    def get_order_items(self, order_id: int) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT kala_code, name, qty, unit_price, variant_id, variant FROM order_items "
                "WHERE order_id=? ORDER BY id",
                (order_id,),
            )

    def list_orders_for_user(self, user_id: int) -> list[dict]:
        with self._lock:
            ids = [
                r["id"]
                for r in self._fetchall(
                    "SELECT id FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,)
                )
            ]
            return [self.get_order(i) for i in ids]

    def list_orders(self, status_filter: str | None = None) -> list[dict]:
        with self._lock:
            if status_filter:
                ids = [
                    r["id"]
                    for r in self._fetchall(
                        "SELECT id FROM orders WHERE status=? ORDER BY id", (status_filter,)
                    )
                ]
            else:
                ids = [r["id"] for r in self._fetchall("SELECT id FROM orders ORDER BY id")]
            return [self.get_order(i) for i in ids]

    def set_order_status(
        self, order_id: int, status_value: str, accounting_order_no: int | None = None
    ) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET status=?, "
                "accounting_order_no=COALESCE(?, accounting_order_no), updated_at=? WHERE id=?",
                (status_value, accounting_order_no, now_iso(), order_id),
            )
            self._commit()
            return self.get_order(order_id)

    def add_payment(self, order_id: int, receipt_ref: str, status_value: str = "submitted",
                    file_name: str | None = None, content_type: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO payments (order_id, receipt_ref, status, file_name, content_type, "
                "created_at) VALUES (?,?,?,?,?,?)",
                (order_id, receipt_ref, status_value, file_name, content_type, now_iso()),
            )
            self._commit()

    def latest_receipt_file(self, order_id: int) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT file_name, content_type FROM payments WHERE order_id=? "
                "AND file_name IS NOT NULL ORDER BY id DESC LIMIT 1",
                (order_id,),
            )

    # ---- tracking (invoice / shipping) ----
    def orders_awaiting_invoice(self, limit: int = 200) -> list[dict]:
        """Orders written to accounting whose invoice is not complete yet."""
        with self._lock:
            return self._fetchall(
                "SELECT id, accounting_order_no, invoice_state FROM orders "
                "WHERE status='written' AND accounting_order_no IS NOT NULL "
                "AND COALESCE(invoice_state,'') <> 'full' AND shipped_at IS NULL "
                "ORDER BY id LIMIT ?",
                (limit,),
            )

    def set_invoice_state(self, order_id: int, state: str, invoiced_qty: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET invoice_state=?, invoiced_qty=?, invoiced_at=?, updated_at=? "
                "WHERE id=?",
                (state, invoiced_qty, now_iso(), now_iso(), order_id),
            )
            self._commit()

    def set_shipped(self, order_id: int) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET shipped_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), order_id),
            )
            self._commit()
            return self.get_order(order_id)

    # ---- shop state (closed mode) ----
    def get_state(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._fetchone("SELECT value FROM shop_state WHERE key=?", (key,))
            return row["value"] if row else default

    def set_state(self, key: str, value: str, actor: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO shop_state (key, value, updated_at, updated_by) VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (key, value, now_iso(), actor),
            )
            self._commit()

    def set_payment_decided(self, order_id: int, decision: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE payments SET status=?, decided_at=? WHERE order_id=?",
                (decision, now_iso(), order_id),
            )
            self._commit()

    # ---- reservations ----
    @contextmanager
    def reservation_guard(self):
        """Serialize a check-then-reserve critical section.

        Availability is computed from the accounting DB and then reserved here;
        without holding this lock across both steps, two concurrent orders can
        both pass the availability check and oversell the same stock.
        """
        with self._lock:
            yield

    def pending_reservations(self, exclude_order_id: int | None = None) -> dict[int, float]:
        with self._lock:
            if exclude_order_id is None:
                exclude_order_id = -1
            rows = self._fetchall(
                "SELECT oi.kala_code, SUM(oi.qty) AS qty "
                "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                "WHERE o.status IN (?,?) AND o.id <> ? GROUP BY oi.kala_code",
                RESERVING_STATUSES + (exclude_order_id,),
            )
            return {r["kala_code"]: r["qty"] for r in rows}

    def expire_awaiting_orders(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE orders SET status='expired', updated_at=? "
                "WHERE status='awaiting_payment' AND reserve_until IS NOT NULL "
                "AND reserve_until < ?",
                (now_iso(), now_iso()),
            )
            self._commit()
            return cur.rowcount

    # ---- audit ----
    def audit(self, actor: str, action: str, detail: str) -> None:
        # detail must never contain tokens or full phone numbers.
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
                (now_iso(), actor, action, detail),
            )
            self._commit()

    # ---- events (notification feed for staff clients) ----
    def add_event(self, kind: str, ref_id: int | None = None, actor: str = "") -> int:
        # Only a kind and an id: names and phones stay out of the feed.
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (ts, kind, ref_id, actor) VALUES (?,?,?,?)",
                (now_iso(), kind, ref_id, actor),
            )
            self._commit()
            return cur.lastrowid

    def last_event_id(self) -> int:
        with self._lock:
            row = self._fetchone("SELECT COALESCE(MAX(id), 0) AS m FROM events")
            return int(row["m"])

    def list_events(self, after_id: int, limit: int = 100) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT id, ts, kind, ref_id, actor FROM events WHERE id > ? "
                "ORDER BY id LIMIT ?",
                (after_id, limit),
            )

    # ---- staff users ----
    def count_staff(self) -> int:
        with self._lock:
            return int(self._fetchone("SELECT COUNT(*) AS c FROM staff_users")["c"])

    def count_active_super_admins(self, exclude_id: int | None = None) -> int:
        with self._lock:
            row = self._fetchone(
                "SELECT COUNT(*) AS c FROM staff_users WHERE role='super_admin' "
                "AND active=1 AND id <> ?",
                (exclude_id if exclude_id is not None else -1,),
            )
            return int(row["c"])

    def list_staff(self) -> list[dict]:
        with self._lock:
            return self._fetchall("SELECT * FROM staff_users ORDER BY id")

    def get_staff(self, staff_id: int) -> dict | None:
        with self._lock:
            return self._fetchone("SELECT * FROM staff_users WHERE id=?", (staff_id,))

    def get_staff_by_username(self, username: str) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT * FROM staff_users WHERE username=? COLLATE NOCASE", (username,)
            )

    def create_staff(self, username: str, full_name: str, role: str, password_hash: str,
                     must_change_password: bool = False) -> dict:
        with self._lock:
            ts = now_iso()
            cur = self._conn.execute(
                "INSERT INTO staff_users (username, full_name, role, password_hash, "
                "must_change_password, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (username, full_name, role, password_hash, int(must_change_password), ts, ts),
            )
            self._commit()
            return self.get_staff(cur.lastrowid)

    def update_staff(self, staff_id: int, **fields) -> dict | None:
        allowed = {"full_name", "role", "active", "password_hash", "must_change_password",
                   "failed_attempts", "locked_until", "last_login_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        with self._lock:
            if sets:
                cols = ", ".join(f"{k}=?" for k in sets)
                self._conn.execute(
                    f"UPDATE staff_users SET {cols}, updated_at=? WHERE id=?",
                    (*sets.values(), now_iso(), staff_id),
                )
                self._commit()
            return self.get_staff(staff_id)

    def delete_staff(self, staff_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM staff_sessions WHERE user_id=?", (staff_id,))
            self._conn.execute("DELETE FROM staff_users WHERE id=?", (staff_id,))
            self._commit()

    # ---- staff sessions ----
    def create_session(self, token_hash: str, user_id: int, expires_at: str,
                       client: str = "") -> None:
        with self._lock:
            ts = now_iso()
            self._conn.execute(
                "INSERT INTO staff_sessions (token_hash, user_id, created_at, last_seen_at, "
                "expires_at, client) VALUES (?,?,?,?,?,?)",
                (token_hash, user_id, ts, ts, expires_at, client[:100]),
            )
            self._commit()

    def get_session(self, token_hash: str) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT * FROM staff_sessions WHERE token_hash=?", (token_hash,)
            )

    def touch_session(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE staff_sessions SET last_seen_at=? WHERE token_hash=?",
                (now_iso(), token_hash),
            )
            self._commit()

    def delete_session(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM staff_sessions WHERE token_hash=?", (token_hash,))
            self._commit()

    def delete_sessions_for_user(self, user_id: int, keep_token_hash: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM staff_sessions WHERE user_id=? AND token_hash <> ?",
                (user_id, keep_token_hash or ""),
            )
            self._commit()
            return cur.rowcount

    def purge_expired_sessions(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM staff_sessions WHERE expires_at < ?", (now_iso(),)
            )
            self._commit()
            return cur.rowcount

    def list_audit(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT id, ts, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            )
