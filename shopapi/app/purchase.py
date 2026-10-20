"""«درخواست خرید» (v2.8.0): a phone of the current price list that cannot be
ordered now - its row is not mapped to a «سازه حساب» product, or that product
has no stock - is requested instead of ordered.

* The bot shows the list price and a «درخواست خرید» button; the request lands
  in ShopAdmin «درخواست کالا» (kind ``purchase``) with color, part and price.
* «تأیید موجودی»: staff map the row if needed, may change the price, and a
  normal order is created (receipt flow, 30-minute deadline, sales windows);
  the bot messages the customer to pay.
* «ناموجود»: the customer gets a polite message.
Nothing is written to «سازه حساب» here; the order is written only after its
receipt is approved, as every other order.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status

from . import groups as group_config
from . import ownership, sales
from .accounting_reader import AccountingReader
from .config import Settings
from .db_own import OwnDB
from .pricelist.importer import active_list_fresh
from .pricelist.matching import part_label
from .pricelist.repo import PriceListRepo
from .security import Identity
from .util import now_iso, now_utc, round_half_up

KIND = "purchase"
EVENT_ORDER_CREATED = "purchase_order_created"
#: What the customer is told when staff mark the request «ناموجود».
UNAVAILABLE_TEXT = ("با پوزش، «{product}» در حال حاضر موجود نیست. به‌محض موجود شدن "
                    "می‌توانید دوباره درخواست بدهید. از صبر و همراهی شما سپاسگزاریم.")
SALES_CLOSED_DETAIL = "Sales are closed"


def variant_text(color: str, part: str) -> str:
    return " — ".join(p for p in (str(color or "").strip(), str(part or "").strip()) if p)


def active_rows(db: OwnDB, settings: Settings) -> tuple[dict | None, list[dict]]:
    """The active list (only while it is valid) and its rows with mappings."""
    repo = PriceListRepo(db)
    active = repo.active_list()
    if active is None or not active_list_fresh(active, settings):
        return active, []
    return active, repo.rows(active["id"])


def row_by_key(db: OwnDB, settings: Settings, row_key: str) -> dict | None:
    _active, rows = active_rows(db, settings)
    return next((r for r in rows if r["row_key"] == row_key), None)


def orderable_codes(db: OwnDB, reader: AccountingReader, settings: Settings, level: int,
                    codes: list[int]) -> dict[int, dict]:
    """Mapped products a customer can order now: a visible phone-group product with
    stock in «سازه حساب» (our open orders reserved)."""
    if not codes:
        return {}
    cfg = group_config.load(db, reader)
    detail = reader.get_products_for_order(sorted(set(codes)), level, db.pending_reservations())
    out = {}
    for code, prod in detail.items():
        if not cfg.visible(prod.get("group")):
            continue
        if float(prod.get("available_qty") or 0) > 0:
            out[int(code)] = prod
    return out


def request_from_row(db: OwnDB, settings: Settings, row: dict, user: dict, qty: int,
                     actor: str) -> dict:
    color = (row.get("color_label") or row.get("color") or "").strip()
    part = part_label(row.get("description") or "", row.get("kind") or "")
    name = " ".join(f"{row.get('section') or ''} {row.get('description') or ''}".split())
    mapping_id = row.get("mapping_id") if row.get("action") == "map" else None
    created = db.add_item_request(
        user["id"], row.get("kala_code") if mapping_id else None, name,
        "", KIND, accounting_db=settings.database_name(), row_key=row["row_key"],
        mapping_id=mapping_id, color=color, part=part,
        price_rial=int(row["price_rial"]) if row.get("price_rial") else None, qty=qty)
    db.audit(actor, "purchase_request_create", f"request id={created['id']}")
    db.add_event("item_request", created["id"], actor)
    return created


# ---- staff ---------------------------------------------------------------------------------------
def confirm_stock(db: OwnDB, reader: AccountingReader, settings: Settings, who: Identity,
                  request: dict, kala_code: int | None, price_rial: int | None) -> dict:
    """«تأیید موجودی» -> a normal order awaiting payment. Returns the order."""
    if request.get("kind") != KIND:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a purchase request")
    ownership.ensure_request_editable(request)
    ownership.take(db, who, "request", request)
    state = sales.compute(db, settings)
    if not state.open:
        # the same sales windows as an order from the bot (phones only)
        raise HTTPException(status.HTTP_409_CONFLICT, f"{SALES_CLOSED_DETAIL}: {state.reason}")
    user = db.get_user_by_id(int(request["user_id"]))
    if user is None or user["status"] == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer cannot order")

    repo = PriceListRepo(db)
    mapping = repo.mapping_for_key(request["row_key"]) if request.get("row_key") else None
    code = kala_code or (mapping or {}).get("kala_code") or request.get("kala_code")
    if code is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the product")
    product = reader.get_products_for_order([int(code)], settings.price_level_bot, {}).get(int(code))
    if product is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Product not found in accounting (or inactive)")
    if request.get("row_key") and (mapping is None or mapping.get("action") != "map"
                                   or int(mapping.get("kala_code") or 0) != int(code)):
        # map the row now (a staff decision: also used for later lists)
        row = row_by_key(db, settings, request["row_key"]) or {}
        mapping = repo.upsert_mapping(
            row_key=request["row_key"], action="map", kala_code=int(code), color_label="",
            section=row.get("section") or "", description=row.get("description") or "",
            kind=row.get("kind") or "", color=row.get("color") or request.get("color") or "",
            actor=who.actor)
        db.audit(who.actor, "price_mapping_map", f"mapping id={mapping['id']} kala={code} "
                 f"(purchase request {request['id']})")
    price = int(price_rial or 0)
    if not price:
        current = row_by_key(db, settings, request["row_key"]) if request.get("row_key") else None
        price = int((current or {}).get("price_rial") or request.get("price_rial") or 0)
    if price <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the price")
    qty = float(request.get("qty") or 1)
    variant = variant_text(request.get("color") or "", request.get("part") or "")
    name = f"{product['name']} — {variant}" if variant else str(product["name"])
    # v2.8.2: the receipt deadline starts with «ارسال اطلاعات پرداخت»
    reserve_until = None
    with db.reservation_guard():
        order = db.create_order(
            int(user["id"]), settings.price_level_bot, round_half_up(qty * price), reserve_until,
            [(int(code), name, qty, float(price), (mapping or {}).get("id"), variant or None,
              request.get("color") or None, request.get("part") or None)],
            accounting_db=settings.database_name(), request_id=int(request["id"]),
            owner_id=ownership.staff_id(who) or request.get("owner_id"))
    db.update_item_request(int(request["id"]), status="done", handled_at=now_iso(),
                           handled_by=who.actor, outcome="confirmed", order_id=order["id"],
                           kala_code=int(code), mapping_id=(mapping or {}).get("id"),
                           price_rial=price)
    ownership.log(db, who, ownership.A_STOCK_CONFIRM, "request", request,
                  detail=f"order={order['id']} price={price}")
    db.audit(who.actor, "purchase_confirm", f"request id={request['id']} order id={order['id']}")
    db.add_event("order_created", order["id"], who.actor)
    db.add_event(EVENT_ORDER_CREATED, order["id"], who.actor)
    return order


def mark_unavailable(db: OwnDB, who: Identity, request: dict) -> dict:
    if request.get("kind") != KIND:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a purchase request")
    ownership.ensure_request_editable(request)
    ownership.take(db, who, "request", request)
    row = db.update_item_request(int(request["id"]), status="done", handled_at=now_iso(),
                                 handled_by=who.actor, outcome="unavailable")
    product = variant_text(request.get("product_name") or "", request.get("color") or "")
    if request.get("platform"):
        message = db.add_item_request_message(
            int(request["id"]), UNAVAILABLE_TEXT.format(product=product or "این کالا"), who.actor)
        db.add_event("item_request_message", message["id"], who.actor)
    ownership.log(db, who, ownership.A_STOCK_UNAVAILABLE, "request", request)
    db.audit(who.actor, "purchase_unavailable", f"request id={request['id']}")
    return row
