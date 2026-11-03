"""v2.18.0: the bot quotes an item we do not stock from today's channel list (and corrections),
at the list's own price (``price_rial``, the shop's usual policy). In the bot only: prices never
reach the site or the mini app. The order itself still goes to staff: there is no item code.
"""
from __future__ import annotations

from .db_own import OwnDB
from .util import now_iso

STATE_KEY = "auto_quote_enabled"
REPORT_LIMIT = 200


def enabled(db: OwnDB) -> bool:
    return db.get_state(STATE_KEY, "1") != "0"


def set_enabled(db: OwnDB, on: bool, actor: str) -> None:
    db.set_state(STATE_KEY, "1" if on else "0", actor)


def record(db: OwnDB, platform: str, chat_id: str, query: str, row: dict,
           list_id: int | None) -> None:
    with db._lock:
        db._conn.execute(
            "INSERT INTO auto_quotes (platform, chat_id, query, row_key, description, color, "
            "price_rial, list_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (platform, str(chat_id), query[:200], row["row_key"],
             str(row.get("description") or ""), str(row.get("color") or ""),
             row.get("price_rial"), list_id, now_iso()))
        db._commit()


def report(db: OwnDB, limit: int = REPORT_LIMIT) -> list[dict]:
    """The latest quotes, newest first. Who asked stays out: the query and the row are enough."""
    with db._lock:
        return db._fetchall(
            "SELECT id, query, description, color, price_rial, created_at FROM auto_quotes "
            "ORDER BY id DESC LIMIT ?", (int(limit),))
