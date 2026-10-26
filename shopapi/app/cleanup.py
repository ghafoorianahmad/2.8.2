"""v2.9.4 «پاک‌سازی داده‌های آزمایشی» (server settings, owner only, on the server).

Before the shop goes live, the orders, requests and customers made while testing
are removed from the shop's OWN databases, so the real work starts clean:

* cleared (``shopapi.db``): orders and their items, payments and receipts, purchase
  / item requests and their messages, inquiries, idempotency keys, customers
  (and so their bot links), notifications (events), the activity log (which also
  holds the archive marks), forgotten-password requests, and every staff account
  that is not an owner («مدیر کل»), with its sessions;
* cleared (``shopbots.db``): conversations, carts, announced notices, «خبرم کن»
  watches and receipt references; receipt image files in ``receipts``;
* kept: the owners, every setting (``.env``, ``shop_state``), product groups,
  price lists and their mappings, site models, proxies and the Telegram session.

The accounting database («سازه حساب») is never opened here: this module only
touches SQLite files in the server's data folder. A fresh verified backup is
required first (the setup takes it), and the owner must type the confirmation.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIRM_TEXT = "پاک‌سازی"
#: the backup must be at most this old (the setup takes one right before)
BACKUP_MAX_AGE = timedelta(minutes=30)

#: children first (foreign keys)
OWN_TABLES = ("item_request_messages", "item_requests", "idempotency_keys", "payments",
              "order_items", "orders", "inquiries", "events", "activity_log", "users")
BOT_TABLES = ("conversations", "carts", "admin_notices", "sales_watch", "receipts")
#: never cleared (asserted by the tests)
KEPT_TABLES = ("shop_state", "price_lists", "price_list_rows", "price_mappings",
               "price_raval_diffs", "price_notes", "price_auto_rejects", "proxies", "proxy_days",
               "catalog_models", "catalog_model_items", "product_groups", "audit_log")
OWNER_ROLE = "super_admin"

LABELS_FA = {
    "orders": "سفارش", "order_items": "قلم سفارش", "payments": "پرداخت/رسید",
    "item_requests": "درخواست خرید و کالا", "item_request_messages": "پیام درخواست",
    "inquiries": "استعلام", "idempotency_keys": "کلید تکرار سفارش", "events": "اعلان",
    "activity_log": "گزارش فعالیت", "users": "مشتری (با پیوند ربات)",
    "staff": "کاربر کارمند (غیرمدیر کل)", "password_requests": "درخواست فراموشی گذرواژه",
    "conversations": "گفت‌وگوی ربات", "carts": "سبد خرید ربات",
    "admin_notices": "اعلان ربات", "sales_watch": "«خبرم کن»", "receipts": "رسید در ربات",
    "receipt_files": "فایل تصویر رسید",
}


class CleanupError(Exception):
    pass


def _parse(raw) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def backup_is_fresh(status: dict, now: datetime | None = None) -> bool:
    """A local backup verified within :data:`BACKUP_MAX_AGE` (the off-server copy
    may still have failed: the local zip is what a restore needs)."""
    if not status or not status.get("file"):
        return False
    verify = status.get("verify") if isinstance(status.get("verify"), dict) else {}
    at = _parse(status.get("at"))
    now = now or datetime.now(timezone.utc)
    return bool(verify.get("ok")) and at is not None and now - at <= BACKUP_MAX_AGE


def _count(conn: sqlite3.Connection, table: str, where: str = "", args: tuple = ()) -> int:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (table,)).fetchone()
    if not exists:
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}" {where}', args).fetchone()[0])


def _receipt_files(receipts_dir: Path | None) -> list[Path]:
    if receipts_dir is None or not Path(receipts_dir).is_dir():
        return []
    return [p for p in Path(receipts_dir).iterdir() if p.is_file()]


def preview(db, *, bots_path: Path | None, receipts_dir: Path | None) -> dict:
    """What a cleanup would remove (counts only) and which accounts stay."""
    counts: dict[str, int] = {}
    with db._lock:  # noqa: SLF001 - the shared connection of OwnDB
        conn = db._conn  # noqa: SLF001
        for table in OWN_TABLES:
            counts[table] = _count(conn, table)
        counts["staff"] = _count(conn, "staff_users", "WHERE role <> ?", (OWNER_ROLE,))
        counts["password_requests"] = _count(conn, "password_requests")
        owners = [r[0] for r in conn.execute(
            "SELECT username FROM staff_users WHERE role = ? ORDER BY id", (OWNER_ROLE,))]
        removed_staff = [r[0] for r in conn.execute(
            "SELECT username FROM staff_users WHERE role <> ? ORDER BY id", (OWNER_ROLE,))]
    if bots_path is not None and Path(bots_path).is_file():
        bots = sqlite3.connect(str(bots_path), timeout=30)
        try:
            for table in BOT_TABLES:
                counts[table] = _count(bots, table)
        finally:
            bots.close()
    counts["receipt_files"] = len(_receipt_files(receipts_dir))
    return {"counts": counts, "owners": owners, "staff_removed": removed_staff,
            "labels": LABELS_FA}


def clear_test_data(db, *, bots_path: Path | None, receipts_dir: Path | None,
                    confirm: str, backup_status: dict, actor: str = "service") -> dict:
    """Clear the test data (see the module text); returns the counts removed."""
    if str(confirm or "").strip() != CONFIRM_TEXT:
        raise CleanupError("confirmation text does not match")
    if not backup_is_fresh(backup_status):
        raise CleanupError("take a backup first")
    before = preview(db, bots_path=bots_path, receipts_dir=receipts_dir)
    with db._lock:  # noqa: SLF001
        conn = db._conn  # noqa: SLF001
        conn.commit()
        try:
            for table in OWN_TABLES:
                if _count(conn, table) or table in ("events", "activity_log"):
                    conn.execute(f'DELETE FROM "{table}"')
            others = [r[0] for r in conn.execute(
                "SELECT id FROM staff_users WHERE role <> ?", (OWNER_ROLE,))]
            for staff_id in others:
                conn.execute("DELETE FROM password_requests WHERE staff_id=?", (staff_id,))
                conn.execute("DELETE FROM staff_sessions WHERE user_id=?", (staff_id,))
                conn.execute("DELETE FROM staff_users WHERE id=?", (staff_id,))
            conn.execute("DELETE FROM password_requests")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if bots_path is not None and Path(bots_path).is_file():
        bots = sqlite3.connect(str(bots_path), timeout=30)
        try:
            with bots:
                for table in BOT_TABLES:
                    if _count(bots, table):
                        bots.execute(f'DELETE FROM "{table}"')
        finally:
            bots.close()
    removed_files = 0
    for path in _receipt_files(receipts_dir):
        try:
            path.unlink()
            removed_files += 1
        except OSError:
            pass
    counts = dict(before["counts"])
    counts["receipt_files"] = removed_files
    db.audit(actor, "cleanup_test_data",
             ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if v))
    return {"ok": True, "counts": counts, "owners": before["owners"],
            "staff_removed": before["staff_removed"], "labels": LABELS_FA}
