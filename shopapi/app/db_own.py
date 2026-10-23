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

-- v2.9.1: the learned «روال − نقد» difference of each model (PDF units), updated
-- with every imported list; used to price a correction («اصلاحیه») that gives
-- only the cash price.
CREATE TABLE IF NOT EXISTS price_raval_diffs (
    model_key TEXT PRIMARY KEY,
    section TEXT NOT NULL DEFAULT '',
    diff INTEGER NOT NULL,
    naghd INTEGER,
    list_id INTEGER,
    updated_at TEXT NOT NULL
);

-- v2.9.1: text posts of the price channel (corrections, «فروش بسته», …) and what
-- was done with them.
CREATE TABLE IF NOT EXISTS price_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER,
    kind TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    text TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- v2.6.2: rows whose automatic mapping staff undid: never matched automatically again.
CREATE TABLE IF NOT EXISTS price_auto_rejects (
    row_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT ''
);

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

CREATE TABLE IF NOT EXISTS password_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','used','expired')),
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pwreq_staff ON password_requests(staff_id);

-- v2.6.0: accounting product groups (Gkala) chosen in ShopAdmin. Only groups with
-- show_in_bot = 1 reach customers; is_phone = 1 = phones (priced and sold only
-- from the current valid distributor price list). No row = hidden.
CREATE TABLE IF NOT EXISTS product_groups (
    group_code INTEGER PRIMARY KEY,
    show_in_bot INTEGER NOT NULL DEFAULT 0,
    is_phone INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

-- v2.6.0: «درخواست کالای ناموجود» from the bot. No payment and nothing is
-- written to the accounting DB; staff see the list in ShopAdmin.
CREATE TABLE IF NOT EXISTS item_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kala_code INTEGER,
    product_name TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','seen','done')),
    created_at TEXT NOT NULL,
    handled_at TEXT,
    handled_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_item_requests_user ON item_requests(user_id);

-- v2.6.1: staff replies to an item request, delivered by the bot the customer
-- used (shopbots follows the events feed). status: pending -> sent | failed.
CREATE TABLE IF NOT EXISTS item_request_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES item_requests(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ireq_messages_request ON item_request_messages(request_id);

-- v2.8.0: who did what (admin-only «گزارش فعالیت» and the order timeline).
-- target_type: 'order' | 'request' | 'customer'. Never a token or a full phone.
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    staff_id INTEGER,
    actor TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    customer_id INTEGER,
    to_staff_id INTEGER,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activity_target ON activity_log(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_activity_staff ON activity_log(staff_id);
CREATE INDEX IF NOT EXISTS idx_activity_customer ON activity_log(customer_id);
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
    # v2.5.0: the accounting database the order belongs to (ACCOUNTING_DATABASE
    # when created; replaced by the one it was really written to). Invoices are
    # only ever looked up in this database.
    ("orders", "accounting_db", "TEXT"),
    ("orders", "cancel_reason", "TEXT"),        # 'receipt_timeout' | ...
    # v2.6.1: «قیمت با استعلام» per product group (inherited by subgroups)
    ("product_groups", "price_on_inquiry", "INTEGER NOT NULL DEFAULT 0"),
    # v2.6.1: item request kind ('unavailable' | 'inquiry') and the staff note
    ("item_requests", "kind", "TEXT NOT NULL DEFAULT 'unavailable'"),
    ("item_requests", "admin_note", "TEXT NOT NULL DEFAULT ''"),
    ("item_requests", "note_at", "TEXT"),
    ("item_requests", "note_by", "TEXT NOT NULL DEFAULT ''"),
    # v2.6.2: automatic price-list mapping (1 = decided by the matcher, to review)
    ("price_mappings", "auto", "INTEGER NOT NULL DEFAULT 0"),
    ("price_mappings", "auto_reason", "TEXT NOT NULL DEFAULT ''"),
    # v2.6.2: the phone color and part/region code the customer chose
    ("order_items", "color", "TEXT"),
    ("order_items", "part", "TEXT"),
    # v2.7.0: per-user permission ticks on top of the role (comma lists)
    ("staff_users", "perm_grant", "TEXT NOT NULL DEFAULT ''"),
    ("staff_users", "perm_revoke", "TEXT NOT NULL DEFAULT ''"),
    # v2.7.0: optional courier given when an order is marked as sent
    ("orders", "courier_name", "TEXT"),
    ("orders", "courier_phone", "TEXT"),
    # v2.8.0: ownership (the staff member who works on it), weekly archive, and
    # the purchase request an order was created from
    ("orders", "owner_id", "INTEGER"),
    ("orders", "owner_at", "TEXT"),
    ("orders", "archived_at", "TEXT"),
    ("orders", "request_id", "INTEGER"),
    ("item_requests", "owner_id", "INTEGER"),
    ("item_requests", "owner_at", "TEXT"),
    ("item_requests", "archived_at", "TEXT"),
    ("item_requests", "accounting_db", "TEXT"),
    # v2.8.0: «درخواست خرید» (kind 'purchase'): the price-list row and what was asked
    ("item_requests", "row_key", "TEXT"),
    ("item_requests", "mapping_id", "INTEGER"),
    ("item_requests", "color", "TEXT NOT NULL DEFAULT ''"),
    ("item_requests", "part", "TEXT NOT NULL DEFAULT ''"),
    ("item_requests", "price_rial", "INTEGER"),
    ("item_requests", "qty", "REAL NOT NULL DEFAULT 1"),
    ("item_requests", "outcome", "TEXT NOT NULL DEFAULT ''"),   # '' | confirmed | unavailable
    ("item_requests", "order_id", "INTEGER"),
    # v2.8.2: payment details typed by staff for each order (JSON) and when sent
    ("orders", "payment_info", "TEXT"),
    ("orders", "payment_info_at", "TEXT"),
    # v2.9.1: a row's price may come from a correction («اصلاحیه») or be held for
    # approval (price guard). naghd / raval / price_rial are always what is sold;
    # orig_* = the PDF values, pending_* = a new price waiting for a manager.
    ("price_list_rows", "price_flag", "TEXT NOT NULL DEFAULT ''"),  # '' | correction | held
    ("price_list_rows", "flag_note", "TEXT NOT NULL DEFAULT ''"),
    ("price_list_rows", "raval_estimated", "INTEGER NOT NULL DEFAULT 0"),
    ("price_list_rows", "orig_naghd", "INTEGER"),
    ("price_list_rows", "orig_raval", "INTEGER"),
    ("price_list_rows", "orig_price_rial", "INTEGER"),
    ("price_list_rows", "pending_naghd", "INTEGER"),
    ("price_list_rows", "pending_raval", "INTEGER"),
    ("price_list_rows", "pending_price_rial", "INTEGER"),
    ("price_list_rows", "pending_estimated", "INTEGER NOT NULL DEFAULT 0"),
    ("price_list_rows", "pending_source", "TEXT NOT NULL DEFAULT ''"),     # list | correction
)

#: Item request kinds (v2.6.1).
ITEM_REQUEST_KINDS = ("unavailable", "inquiry", "purchase")

#: v2.8.0: finished orders (read-only for everyone; archived on Thursday night).
#: An order is also finished once it was marked as sent (``shipped_at``).
CLOSED_ORDER_STATUSES = ("rejected", "cancelled", "expired")

#: cancel_reason of an order whose receipt did not arrive in time.
CANCEL_RECEIPT_TIMEOUT = "receipt_timeout"
#: cancel_reason of an order the customer cancelled in the bot (v2.6.2).
CANCEL_BY_CUSTOMER = "customer"

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
        # v2.7.0: two roles only («مدیر» / «کاربر فروش»); older roles are mapped.
        from .staff import LEGACY_ROLE_MAP

        for old, new in LEGACY_ROLE_MAP.items():
            self._conn.execute("UPDATE staff_users SET role=? WHERE role=?", (new, old))
        # v2.8.2: per-user ticks of the old permission names -> the same rights as
        # section ticks («دیدن» / «تغییر»); idempotent (new names are left alone).
        from .staff import migrate_ticks

        for row in self._conn.execute(
                "SELECT id, role, perm_grant, perm_revoke FROM staff_users").fetchall():
            moved = migrate_ticks(row["role"], row["perm_grant"] or "", row["perm_revoke"] or "")
            if moved is not None:
                self._conn.execute("UPDATE staff_users SET perm_grant=?, perm_revoke=? WHERE id=?",
                                   (moved[0], moved[1], row["id"]))
        # v2.8.3: the daily-work sections are always on (no tick): their old ticks go.
        from .staff import strip_always

        for row in self._conn.execute(
                "SELECT id, perm_grant, perm_revoke FROM staff_users").fetchall():
            grant, revoke = strip_always(row["perm_grant"]), strip_always(row["perm_revoke"])
            if grant is not None or revoke is not None:
                self._conn.execute(
                    "UPDATE staff_users SET perm_grant=?, perm_revoke=? WHERE id=?",
                    (row["perm_grant"] if grant is None else grant,
                     row["perm_revoke"] if revoke is None else revoke, row["id"]))

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
        reserve_until: str | None,
        items: list[tuple[int, str, float, float]],
        accounting_db: str | None = None,
        *,
        request_id: int | None = None,
        owner_id: int | None = None,
    ) -> dict:
        """items: (kala_code, name, qty, unit_price[, variant_id, variant]).
        ``reserve_until`` = the receipt deadline (the stock is held until then).
        v2.8.0: an order made from a purchase request keeps the request and its owner."""
        with self._lock:
            ts = now_iso()
            self._conn.execute(
                "INSERT INTO orders (user_id, status, price_level, total, reserve_until, "
                "accounting_db, created_at, updated_at, request_id, owner_id, owner_at) "
                "VALUES (?,'awaiting_payment',?,?,?,?,?,?,?,?,?)",
                (user_id, price_level, total, reserve_until, accounting_db, ts, ts,
                 request_id, owner_id, ts if owner_id is not None else None),
            )
            row = self._conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            order_id = row["id"]
            for item in items:
                kala_code, name, qty, unit_price = item[:4]
                variant_id = item[4] if len(item) > 4 else None
                variant = item[5] if len(item) > 5 else None
                color = item[6] if len(item) > 6 else None
                part = item[7] if len(item) > 7 else None
                self._conn.execute(
                    "INSERT INTO order_items (order_id, kala_code, name, qty, unit_price, "
                    "variant_id, variant, color, part) VALUES (?,?,?,?,?,?,?,?,?)",
                    (order_id, kala_code, name, qty, unit_price, variant_id, variant,
                     color, part),
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
                "u.name AS user_name, u.phone AS user_phone, "
                "EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.id "
                "AND p.file_name IS NOT NULL) AS has_receipt "
                "FROM orders o JOIN users u ON u.id = o.user_id WHERE o.id=?",
                (order_id,),
            )
            if order is None:
                return None
            if order.get("payment_info"):
                import json

                try:
                    order["payment_info"] = json.loads(order["payment_info"])
                except ValueError:
                    order["payment_info"] = None
            order["customer_pending"] = order.get("user_status") != "approved"
            order["items"] = self._fetchall(
                "SELECT kala_code, name, qty, unit_price, variant_id, variant, color, part "
                "FROM order_items WHERE order_id=? ORDER BY id",
                (order_id,),
            )
            return order

    def get_order_items(self, order_id: int) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT kala_code, name, qty, unit_price, variant_id, variant, color, part "
                "FROM order_items WHERE order_id=? ORDER BY id",
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
        self, order_id: int, status_value: str, accounting_order_no: int | None = None,
        accounting_db: str | None = None,
    ) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET status=?, "
                "accounting_order_no=COALESCE(?, accounting_order_no), "
                "accounting_db=COALESCE(?, accounting_db), updated_at=? WHERE id=?",
                (status_value, accounting_order_no, accounting_db, now_iso(), order_id),
            )
            self._commit()
            return self.get_order(order_id)

    def list_payments(self, order_id: int) -> list[dict]:
        with self._lock:
            return self._fetchall("SELECT id, status FROM payments WHERE order_id=?",
                                  (order_id,))

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
    def orders_awaiting_invoice(self, accounting_db: str, limit: int = 200) -> list[dict]:
        """Orders written to ``accounting_db`` whose invoice is not complete yet.
        Orders of another database (or of an unknown one) are never checked
        against this one: the same Codlp there is a different order."""
        with self._lock:
            return self._fetchall(
                "SELECT id, accounting_order_no, invoice_state, accounting_db FROM orders "
                "WHERE status='written' AND accounting_order_no IS NOT NULL "
                "AND accounting_db IS NOT NULL AND lower(trim(accounting_db)) = lower(trim(?)) "
                "AND COALESCE(invoice_state,'') <> 'full' AND shipped_at IS NULL "
                "ORDER BY id LIMIT ?",
                (accounting_db, limit),
            )

    def set_invoice_state(self, order_id: int, state: str, invoiced_qty: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET invoice_state=?, invoiced_qty=?, invoiced_at=?, updated_at=? "
                "WHERE id=?",
                (state, invoiced_qty, now_iso(), now_iso(), order_id),
            )
            self._commit()

    def set_shipped(self, order_id: int, courier_name: str | None = None,
                    courier_phone: str | None = None) -> dict:
        with self._lock:
            self._conn.execute(
                "UPDATE orders SET shipped_at=?, updated_at=?, courier_name=?, courier_phone=? "
                "WHERE id=?",
                (now_iso(), now_iso(), courier_name or None, courier_phone or None, order_id),
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

    def overdue_awaiting_orders(self, now: str | None = None) -> list[dict]:
        """Orders still waiting for a receipt after their deadline."""
        with self._lock:
            return self._fetchall(
                "SELECT id, accounting_order_no, accounting_db FROM orders "
                "WHERE status='awaiting_payment' AND reserve_until IS NOT NULL "
                "AND reserve_until <= ? ORDER BY id",
                (now or now_iso(),),
            )

    def set_payment_info(self, order_id: int, info: dict, reserve_until: str) -> dict | None:
        """v2.8.2: the payment details staff sent for this order; the receipt
        deadline starts now (an order without them never times out)."""
        import json

        with self._lock:
            self._conn.execute(
                "UPDATE orders SET payment_info=?, payment_info_at=?, reserve_until=?, "
                "updated_at=? WHERE id=? AND status='awaiting_payment'",
                (json.dumps(info, ensure_ascii=False), now_iso(), reserve_until, now_iso(),
                 order_id))
            self._commit()
        return self.get_order(order_id)

    def cancel_order_any(self, order_id: int, reason: str, statuses: tuple[str, ...]) -> bool:
        """v2.7.0: staff cancel (awaiting payment or with a receipt). Local only."""
        with self._lock:
            marks = ",".join("?" for _ in statuses)
            cur = self._conn.execute(
                "UPDATE orders SET status='cancelled', cancel_reason=?, updated_at=? "
                f"WHERE id=? AND status IN ({marks})",
                (reason, now_iso(), order_id, *statuses),
            )
            self._commit()
            return cur.rowcount == 1

    def cancel_order_locally(self, order_id: int, reason: str) -> bool:
        """Cancel an order that still waits for its receipt. Only our SQLite row
        changes; nothing is ever deleted (here or in the accounting DB)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE orders SET status='cancelled', cancel_reason=?, updated_at=? "
                "WHERE id=? AND status='awaiting_payment'",
                (reason, now_iso(), order_id),
            )
            self._commit()
            return cur.rowcount == 1

    def expire_awaiting_orders(self) -> int:
        """Cancel every order past its receipt deadline (see order_timeout)."""
        from .order_timeout import cancel_overdue

        return len(cancel_overdue(self, "system:expire"))

    # ---- product groups (v2.6.0) ----
    def list_group_settings(self) -> dict[int, dict]:
        with self._lock:
            return {
                int(r["group_code"]): r
                for r in self._fetchall("SELECT * FROM product_groups ORDER BY group_code")
            }

    def set_group_settings(self, entries: list[tuple], actor: str) -> None:
        """entries: (group_code, show_in_bot, is_phone[, price_on_inquiry]); other
        groups keep theirs."""
        with self._lock:
            ts = now_iso()
            for entry in entries:
                code, shown, phone = entry[:3]
                inquiry = entry[3] if len(entry) > 3 else False
                self._conn.execute(
                    "INSERT INTO product_groups (group_code, show_in_bot, is_phone, "
                    "price_on_inquiry, updated_at, updated_by) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(group_code) DO UPDATE SET "
                    "show_in_bot=excluded.show_in_bot, is_phone=excluded.is_phone, "
                    "price_on_inquiry=excluded.price_on_inquiry, "
                    "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                    (int(code), int(bool(shown)), int(bool(phone)), int(bool(inquiry)), ts, actor),
                )
            self._commit()

    # ---- unavailable item requests (v2.6.0) ----
    _ITEM_REQUEST_SELECT = (
        "SELECT r.*, u.name AS customer_name, u.person_code, u.platform, "
        "u.phone AS customer_phone, "
        "(SELECT COUNT(*) FROM item_request_messages m WHERE m.request_id = r.id) "
        "AS messages_count FROM item_requests r JOIN users u ON u.id = r.user_id "
    )

    def add_item_request(self, user_id: int, kala_code: int | None, product_name: str,
                         text: str, kind: str = "unavailable", *,
                         accounting_db: str | None = None, row_key: str | None = None,
                         mapping_id: int | None = None, color: str = "", part: str = "",
                         price_rial: int | None = None, qty: float = 1) -> dict:
        if kind not in ITEM_REQUEST_KINDS:
            raise ValueError(kind)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO item_requests (user_id, kala_code, product_name, text, kind, "
                "created_at, accounting_db, row_key, mapping_id, color, part, price_rial, qty) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, kala_code, product_name, text, kind, now_iso(), accounting_db,
                 row_key, mapping_id, color or "", part or "", price_rial, qty),
            )
            self._commit()
            return self.get_item_request(cur.lastrowid)

    def get_item_request(self, request_id: int) -> dict | None:
        with self._lock:
            return self._fetchone(self._ITEM_REQUEST_SELECT + "WHERE r.id=?", (request_id,))

    def list_item_requests(self, status_filter: str | None = None, limit: int = 500,
                           kind: str | None = None) -> list[dict]:
        with self._lock:
            clauses, params = [], []
            if status_filter:
                clauses.append("r.status=?")
                params.append(status_filter)
            if kind:
                clauses.append("r.kind=?")
                params.append(kind)
            where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
            return self._fetchall(
                self._ITEM_REQUEST_SELECT + where + "ORDER BY r.id DESC LIMIT ?",
                tuple(params) + (limit,),
            )

    def set_item_request_note(self, request_id: int, note: str, actor: str) -> dict | None:
        with self._lock:
            self._conn.execute(
                "UPDATE item_requests SET admin_note=?, note_at=?, note_by=? WHERE id=?",
                (note, now_iso(), actor, request_id),
            )
            self._commit()
            return self.get_item_request(request_id)

    # ---- staff replies to item requests (v2.6.1) ----
    def add_item_request_message(self, request_id: int, text: str, actor: str) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO item_request_messages (request_id, text, created_at, created_by) "
                "VALUES (?,?,?,?)",
                (request_id, text, now_iso(), actor),
            )
            self._commit()
            return self.get_item_request_message(cur.lastrowid)

    def get_item_request_message(self, message_id: int) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT m.*, r.product_name, r.text AS request_text, r.kind, "
                "u.platform, u.chat_id FROM item_request_messages m "
                "JOIN item_requests r ON r.id = m.request_id "
                "JOIN users u ON u.id = r.user_id WHERE m.id=?",
                (message_id,),
            )

    def list_item_request_messages(self, request_id: int) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT * FROM item_request_messages WHERE request_id=? ORDER BY id",
                (request_id,),
            )

    def set_item_request_message_result(self, message_id: int, ok: bool,
                                        error: str) -> dict | None:
        """Only a pending message changes (a late duplicate report is ignored)."""
        with self._lock:
            self._conn.execute(
                "UPDATE item_request_messages SET status=?, error=?, sent_at=? "
                "WHERE id=? AND status='pending'",
                ("sent" if ok else "failed", "" if ok else error, now_iso(), message_id),
            )
            self._commit()
            return self.get_item_request_message(message_id)

    def count_item_requests_since(self, user_id: int, since: str) -> int:
        with self._lock:
            row = self._fetchone(
                "SELECT COUNT(*) AS n FROM item_requests WHERE user_id=? AND created_at>=?",
                (user_id, since),
            )
            return int(row["n"])

    def set_item_request_status(self, request_id: int, status_value: str, actor: str) -> dict | None:
        with self._lock:
            self._conn.execute(
                "UPDATE item_requests SET status=?, handled_at=?, handled_by=? WHERE id=?",
                (status_value, now_iso(), actor, request_id),
            )
            self._commit()
            return self.get_item_request(request_id)

    def update_item_request(self, request_id: int, **fields) -> dict | None:
        """v2.8.0: purchase-request outcome / mapping (known columns only)."""
        allowed = {"status", "handled_at", "handled_by", "outcome", "order_id", "kala_code",
                   "mapping_id", "price_rial"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        with self._lock:
            if sets:
                cols = ", ".join(f"{k}=?" for k in sets)
                self._conn.execute(f"UPDATE item_requests SET {cols} WHERE id=?",
                                   (*sets.values(), request_id))
                self._commit()
            return self.get_item_request(request_id)

    # ---- ownership (v2.8.0) ----
    _OWNED_TABLES = {"order": "orders", "request": "item_requests"}

    def claim(self, target_type: str, target_id: int, staff_id: int) -> bool:
        """The first staff member who acts becomes the owner. True = this one owns
        it now (it was free, or already theirs)."""
        table = self._OWNED_TABLES[target_type]
        with self._lock:
            self._conn.execute(
                f"UPDATE {table} SET owner_id=?, owner_at=? WHERE id=? AND owner_id IS NULL",
                (staff_id, now_iso(), target_id))
            self._commit()
            row = self._fetchone(f"SELECT owner_id FROM {table} WHERE id=?", (target_id,))
            return row is not None and row["owner_id"] == staff_id

    def customer_ids_for_staff(self, staff_id: int) -> set[int]:
        """v2.8.2: customers a sales user may see: those of their own orders /
        requests and of new ones nobody has taken yet."""
        with self._lock:
            rows = self._fetchall(
                "SELECT user_id FROM orders WHERE owner_id=? OR (owner_id IS NULL AND "
                "archived_at IS NULL AND status IN ('awaiting_payment','receipt_uploaded') "
                "AND shipped_at IS NULL) "
                "UNION SELECT user_id FROM item_requests WHERE owner_id=? OR "
                "(owner_id IS NULL AND archived_at IS NULL AND status <> 'done')",
                (staff_id, staff_id))
        return {int(r["user_id"]) for r in rows if r["user_id"] is not None}

    def set_owner(self, target_type: str, target_id: int, staff_id: int | None) -> None:
        table = self._OWNED_TABLES[target_type]
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET owner_id=?, owner_at=? WHERE id=?",
                               (staff_id, now_iso(), target_id))
            self._commit()

    def open_owned(self, staff_id: int) -> dict[str, list[dict]]:
        """v2.8.3: the unfinished orders / requests of one staff member (for
        «انتقال همهٔ کارهای باز»)."""
        marks = ",".join("?" for _ in CLOSED_ORDER_STATUSES)
        with self._lock:
            orders = self._fetchall(
                "SELECT id, user_id, owner_id FROM orders WHERE owner_id=? AND archived_at IS NULL "
                f"AND shipped_at IS NULL AND status NOT IN ({marks}) ORDER BY id",
                (staff_id, *CLOSED_ORDER_STATUSES))
            requests = self._fetchall(
                "SELECT id, user_id, owner_id FROM item_requests WHERE owner_id=? "
                "AND archived_at IS NULL AND status <> 'done' ORDER BY id", (staff_id,))
        return {"order": orders, "request": requests}

    def staff_names(self, ids) -> dict[int, str]:
        wanted = sorted({int(i) for i in ids if i is not None})
        if not wanted:
            return {}
        with self._lock:
            marks = ",".join("?" for _ in wanted)
            rows = self._fetchall(
                f"SELECT id, username, full_name FROM staff_users WHERE id IN ({marks})",
                tuple(wanted))
        return {int(r["id"]): (str(r["full_name"] or "").strip() or r["username"]) for r in rows}

    def query_orders(self, *, status: str | None = None, viewer_id: int | None = None,
                     mine_only: bool = False, archived: bool = False,
                     accounting_db: str | None = None, q: str | None = None,
                     limit: int = 1000) -> list[dict]:
        """Orders for ShopAdmin (v2.8.0). ``viewer_id`` = a sales user: only free
        orders and their own (``mine_only``: their own only). Archived orders only
        with ``archived``."""
        clauses = ["o.archived_at IS NOT NULL" if archived else "o.archived_at IS NULL"]
        params: list = []
        if status:
            clauses.append("o.status=?")
            params.append(status)
        if viewer_id is not None:
            if mine_only or archived:
                clauses.append("o.owner_id=?")
            else:
                # v2.8.3: their own + OPEN orders nobody has taken yet (finished or
                # accepted ones without an owner are the manager's only)
                clauses.append("(o.owner_id=? OR (o.owner_id IS NULL AND o.status IN "
                               "('awaiting_payment','receipt_uploaded') "
                               "AND o.shipped_at IS NULL))")
            params.append(viewer_id)
        if accounting_db:
            clauses.append("lower(trim(COALESCE(o.accounting_db,''))) = lower(trim(?))")
            params.append(accounting_db)
        if q and q.strip():
            needle = f"%{q.strip()}%"
            clauses.append("(CAST(o.id AS TEXT)=? OR CAST(o.accounting_order_no AS TEXT)=? "
                           "OR u.name LIKE ? OR u.phone LIKE ?)")
            params += [q.strip(), q.strip(), needle, needle]
        with self._lock:
            ids = [r["id"] for r in self._fetchall(
                "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id WHERE "
                + " AND ".join(clauses) + " ORDER BY o.id DESC LIMIT ?",
                tuple(params) + (limit,))]
            return [self.get_order(i) for i in ids]

    def query_item_requests(self, *, status: str | None = None, kind: str | None = None,
                            viewer_id: int | None = None, mine_only: bool = False,
                            archived: bool = False, accounting_db: str | None = None,
                            q: str | None = None, limit: int = 500) -> list[dict]:
        clauses = ["r.archived_at IS NOT NULL" if archived else "r.archived_at IS NULL"]
        params: list = []
        if status:
            clauses.append("r.status=?")
            params.append(status)
        if kind:
            clauses.append("r.kind=?")
            params.append(kind)
        if viewer_id is not None:
            if mine_only or archived:
                clauses.append("r.owner_id=?")
            else:
                # v2.8.2: their own + open requests nobody has taken yet
                clauses.append("(r.owner_id=? OR (r.owner_id IS NULL AND r.status <> 'done'))")
            params.append(viewer_id)
        if accounting_db:
            clauses.append("lower(trim(COALESCE(r.accounting_db,''))) = lower(trim(?))")
            params.append(accounting_db)
        if q and q.strip():
            needle = f"%{q.strip()}%"
            clauses.append("(CAST(r.id AS TEXT)=? OR r.product_name LIKE ? OR r.text LIKE ? "
                           "OR u.name LIKE ?)")
            params += [q.strip(), needle, needle, needle]
        with self._lock:
            return self._fetchall(
                self._ITEM_REQUEST_SELECT + "WHERE " + " AND ".join(clauses)
                + " ORDER BY r.id DESC LIMIT ?", tuple(params) + (limit,))

    # ---- weekly archive (v2.8.0) ----
    def archive_closed(self, cutoff: str) -> dict[str, int]:
        """Move finished orders / requests (last change before ``cutoff``) to the
        archive. Nothing is deleted; archived rows are read-only."""
        ts = now_iso()
        marks = ",".join("?" for _ in CLOSED_ORDER_STATUSES)
        with self._lock:
            orders = self._conn.execute(
                "UPDATE orders SET archived_at=? WHERE archived_at IS NULL AND updated_at<=? "
                f"AND (status IN ({marks}) OR shipped_at IS NOT NULL)",
                (ts, cutoff, *CLOSED_ORDER_STATUSES)).rowcount
            requests = self._conn.execute(
                "UPDATE item_requests SET archived_at=? WHERE archived_at IS NULL "
                "AND status='done' AND COALESCE(handled_at, created_at)<=?",
                (ts, cutoff)).rowcount
            self._commit()
        return {"orders": int(orders), "requests": int(requests)}

    def archive_abandoned(self, cutoff: str) -> dict[str, int]:
        """v2.8.3 (nightly): orders nobody took that the customer cancelled or that
        lapsed (no receipt in time / expired), and the requests of such orders
        nobody took, go to the archive. Nothing is deleted."""
        ts = now_iso()
        abandoned = ("owner_id IS NULL AND archived_at IS NULL AND updated_at<=? AND "
                     "(status='expired' OR (status='cancelled' AND cancel_reason IN (?, ?)))")
        params = (cutoff, CANCEL_BY_CUSTOMER, CANCEL_RECEIPT_TIMEOUT)
        with self._lock:
            requests = self._conn.execute(
                "UPDATE item_requests SET archived_at=? WHERE archived_at IS NULL AND "
                "owner_id IS NULL AND order_id IN (SELECT id FROM orders WHERE "
                + abandoned + ")", (ts, *params)).rowcount
            orders = self._conn.execute(
                "UPDATE orders SET archived_at=? WHERE " + abandoned,
                (ts, *params)).rowcount
            self._commit()
        return {"orders": int(orders), "requests": int(requests)}

    # ---- activity log (v2.8.0) ----
    def log_activity(self, *, staff_id: int | None, actor: str, action: str, target_type: str,
                     target_id: int | None, customer_id: int | None = None,
                     to_staff_id: int | None = None, detail: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO activity_log (ts, staff_id, actor, action, target_type, target_id, "
                "customer_id, to_staff_id, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                (now_iso(), staff_id, actor, action, target_type, target_id, customer_id,
                 to_staff_id, detail[:300]))
            self._commit()
            return cur.lastrowid

    def list_activity(self, *, staff_id: int | None = None, customer_id: int | None = None,
                      date_from: str | None = None, date_to: str | None = None,
                      targets: list[tuple[str, int]] | None = None,
                      own_only: bool = False, limit: int = 500) -> list[dict]:
        """``own_only`` (v2.8.3): only what ``staff_id`` did themselves (not what a
        colleague handed to them)."""
        clauses, params = [], []
        if staff_id is not None and own_only:
            clauses.append("a.staff_id=?")
            params.append(staff_id)
        elif staff_id is not None:
            clauses.append("(a.staff_id=? OR a.to_staff_id=?)")
            params += [staff_id, staff_id]
        if customer_id is not None:
            clauses.append("a.customer_id=?")
            params.append(customer_id)
        if date_from:
            clauses.append("a.ts>=?")
            params.append(date_from)
        if date_to:
            clauses.append("a.ts<?")
            params.append(date_to)
        if targets is not None:
            if not targets:
                return []
            clauses.append("(" + " OR ".join("(a.target_type=? AND a.target_id=?)"
                                             for _ in targets) + ")")
            for kind, ident in targets:
                params += [kind, ident]
        where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
        order = "ASC" if targets is not None else "DESC"
        with self._lock:
            return self._fetchall(
                "SELECT a.*, u.name AS customer_name FROM activity_log a "
                "LEFT JOIN users u ON u.id = a.customer_id " + where
                + f"ORDER BY a.id {order} LIMIT ?", tuple(params) + (limit,))

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
                   "failed_attempts", "locked_until", "last_login_at", "perm_grant",
                   "perm_revoke"}
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

    # ---- forgot-password requests (the token is stored hashed, like sessions) ----
    def create_password_request(self, staff_id: int, token_hash: str, expires_at: str) -> dict:
        with self._lock:
            # one open request per account: a new one replaces the old
            self._conn.execute(
                "UPDATE password_requests SET status='expired' "
                "WHERE staff_id=? AND status IN ('pending','approved')", (staff_id,))
            cur = self._conn.execute(
                "INSERT INTO password_requests (staff_id, token_hash, created_at, expires_at) "
                "VALUES (?,?,?,?)", (staff_id, token_hash, now_iso(), expires_at))
            self._commit()
            return self.get_password_request(cur.lastrowid)

    def get_password_request(self, request_id: int) -> dict | None:
        with self._lock:
            return self._fetchone(
                "SELECT r.*, u.username, u.full_name, u.role FROM password_requests r "
                "JOIN staff_users u ON u.id = r.staff_id WHERE r.id=?", (request_id,))

    def list_pending_password_requests(self) -> list[dict]:
        with self._lock:
            return self._fetchall(
                "SELECT r.id, r.staff_id, r.status, r.created_at, r.expires_at, "
                "u.username, u.full_name, u.role FROM password_requests r "
                "JOIN staff_users u ON u.id = r.staff_id "
                "WHERE r.status='pending' AND r.expires_at > ? ORDER BY r.id",
                (now_iso(),))

    def set_password_request_status(self, request_id: int, status: str,
                                    decided_by: str = "", expires_at: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE password_requests SET status=?, decided_at=?, decided_by=?, "
                "expires_at=COALESCE(?, expires_at) WHERE id=?",
                (status, now_iso(), decided_by, expires_at, request_id))
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
