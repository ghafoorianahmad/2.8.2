"""Order tracking after the accounting write: invoiced (R5) and shipped.

``sync_invoices`` compares our written orders with the accounting software's
invoices (``Facto.ordercode``) and records each change once as an event, which
the bots turn into a customer message. Shipping is set by staff in ShopAdmin.
"""
from __future__ import annotations

import asyncio
import logging

from .db_own import OwnDB

logger = logging.getLogger("shopapi.tracking")

STATE_PARTIAL = "partial"
STATE_FULL = "full"
EVENT_PARTIAL = "order_partially_invoiced"
EVENT_FULL = "order_invoiced"
EVENT_SHIPPED = "order_shipped"


def invoice_state(ordered: float, invoiced: float) -> str | None:
    if invoiced <= 0 or ordered <= 0:
        return None
    return STATE_FULL if invoiced >= ordered else STATE_PARTIAL


def sync_invoices(db: OwnDB, reader, actor: str = "system:tracking") -> int:
    """Record invoice progress for written orders. Returns the number of changes."""
    pending = db.orders_awaiting_invoice()
    if not pending:
        return 0
    by_codlp = {int(o["accounting_order_no"]): o for o in pending}
    progress = reader.invoice_progress(list(by_codlp))
    changed = 0
    for codlp, order in by_codlp.items():
        info = progress.get(codlp)
        if info is None:
            # Deleted in accounting (= cancelled there); staff will see it in ShopAdmin.
            continue
        state = invoice_state(info["ordered"], info["invoiced"])
        if state is None or state == order.get("invoice_state"):
            continue
        db.set_invoice_state(order["id"], state, info["invoiced"])
        db.audit(actor, "order_invoice_state", f"order id={order['id']} state={state}")
        db.add_event(EVENT_FULL if state == STATE_FULL else EVENT_PARTIAL, order["id"], actor)
        changed += 1
    return changed


async def invoice_sync_loop(settings, db_factory, reader_factory) -> None:
    """Background loop started with the API (never raises)."""
    interval = int(settings.invoice_sync_seconds)
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(sync_invoices, db_factory(), reader_factory())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # accounting down etc.: try again next round
            logger.warning("invoice sync failed: %s", type(exc).__name__)
