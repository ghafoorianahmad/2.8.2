"""Receipt deadline (decision 2026-10-14): no payment gateway, no 12-hour hold.

The customer uploads the payment receipt right after ordering. An order still
waiting for its receipt ``RECEIPT_DEADLINE_MINUTES`` (30) after it was placed is
cancelled **locally** (our SQLite only) and its stock hold ends.

Nothing is ever deleted from the accounting DB («سازه حساب»). Orders are only
written there after the payment is approved, so an order waiting for a receipt
normally has no accounting row; if one ever has (``accounting_order_no`` set),
it is left untouched and the admin is alerted to decide in the accounting
software.
"""
from __future__ import annotations

import asyncio
import logging

from . import sales
from .db_own import CANCEL_RECEIPT_TIMEOUT, OwnDB
from .util import now_iso

logger = logging.getLogger("shopapi.order_timeout")

#: The customer is told (bot) and staff see it (ShopAdmin).
EVENT_CANCELLED = "order_auto_cancelled"
#: The order already exists in the accounting DB: only the admin is alerted.
EVENT_NEEDS_ADMIN = "order_timeout_written"


def cancel_overdue(db: OwnDB, actor: str = "system:receipt_timeout",
                   now: str | None = None) -> list[int]:
    """Cancel overdue orders; return the ids cancelled. Never raises on one bad row."""
    cancelled: list[int] = []
    with db.reservation_guard():
        for order in db.overdue_awaiting_orders(now or now_iso()):
            order_id = int(order["id"])
            if order.get("accounting_order_no"):
                marker = f"timeout_alerted:{order_id}"
                if db.get_state(marker, "") != "1":
                    db.set_state(marker, "1", actor)
                    db.audit(actor, "order_timeout_written",
                             f"order id={order_id} accounting_order_no="
                             f"{order['accounting_order_no']} db={order.get('accounting_db') or '-'}"
                             " (not cancelled: exists in accounting)")
                    db.add_event(EVENT_NEEDS_ADMIN, order_id, actor)
                continue
            if db.cancel_order_locally(order_id, CANCEL_RECEIPT_TIMEOUT):
                db.audit(actor, "order_auto_cancel", f"order id={order_id} reason=receipt_timeout")
                db.add_event(EVENT_CANCELLED, order_id, actor)
                cancelled.append(order_id)
    return cancelled


def tick(db: OwnDB, settings) -> None:
    cancel_overdue(db)
    sales.record_transition(db, settings)


async def order_timeout_loop(settings, db_factory) -> None:
    """Background loop started with the API (never raises)."""
    interval = int(settings.order_timeout_check_seconds)
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(tick, db_factory(), settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - try again next round
            logger.warning("order timeout check failed: %s", type(exc).__name__)
