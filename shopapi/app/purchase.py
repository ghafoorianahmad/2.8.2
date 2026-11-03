"""«درخواست خرید» (v2.8.0): a phone of the current price list that cannot be
ordered now - its row is not mapped to a «سازه حساب» product, or that product
has no stock - is requested instead of ordered.

* The bot shows the list price and a «درخواست خرید - استعلام قیمت» button
  (v2.9.2: one button; also a row whose price waits for a manager, without a
  price); the request lands in ShopAdmin «درخواست کالا» (kind ``purchase``).
* «تأیید موجودی» (list price) or a price typed by staff: v2.9.2 the customer
  gets the price with «تأیید و خرید» / «نمی‌خواهم»; on «تأیید و خرید» a normal
  order is created at that price (payment details from staff, receipt deadline,
  sales windows). Every step is in the request's history.
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
from .pricelist import channels as channel_lists
from .pricelist.importer import active_list_fresh
from .pricelist.matching import part_label
from .pricelist.repo import PriceListRepo
from .security import Identity
from .util import now_iso, now_utc, round_half_up

KIND = "purchase"
#: v2.9.2: a price can be offered for these (the customer confirms in the bot)
OFFER_KINDS = ("purchase", "inquiry", "unavailable")
EVENT_ORDER_CREATED = "purchase_order_created"
EVENT_OFFER_DECLINED = "purchase_offer_declined"
OUTCOME_OFFERED = "offered"
OUTCOME_CONFIRMED = "confirmed"
OUTCOME_DECLINED = "declined"
PURPOSE_OFFER = "offer"
OFFER_GONE_DETAIL = "The offer is no longer open"
#: The offer as it shows in the request's message history (the bot builds its own text).
OFFER_TEXT = "قیمت پیشنهادی: {price} ریال (جمع {total} ریال) — منتظر «تأیید و خرید» مشتری"
#: v2.9.3: one item (the usual case): no «جمع»
OFFER_TEXT_ONE = "قیمت پیشنهادی: {price} ریال — منتظر «تأیید و خرید» مشتری"


def clean_note(note: str | None) -> str:
    """Staff's message: the lines kept, extra spaces and empty lines dropped."""
    lines = (" ".join(line.split()) for line in str(note or "").splitlines())
    return "\n".join(line for line in lines if line)[:1000]


def offer_text(price: int, qty: float, note: str = "") -> str:
    """The line in ShopAdmin's message history for a price offer (+ staff's note)."""
    if qty > 1:
        text = OFFER_TEXT.format(price=f"{price:,}", total=f"{round_half_up(qty * price):,}")
    else:
        text = OFFER_TEXT_ONE.format(price=f"{price:,}")
    return f"{text}\nپیام همراه: {note}" if note else text
#: What the customer is told when staff mark the request «ناموجود».
UNAVAILABLE_TEXT = ("با پوزش، «{product}» در حال حاضر موجود نیست. به‌محض موجود شدن "
                    "می‌توانید دوباره درخواست بدهید. از صبر و همراهی شما سپاسگزاریم.")
SALES_CLOSED_DETAIL = "Sales are closed"


def variant_text(color: str, part: str) -> str:
    return " — ".join(p for p in (str(color or "").strip(), str(part or "").strip()) if p)


def active_rows(db: OwnDB, settings: Settings) -> tuple[dict | None, list[dict]]:
    """The active list (only while it is valid) and its rows with mappings.
    v2.9.2: a row whose new price waits for a manager (price guard) has no price
    here (``price_held``): never sold at the old price, only requested."""
    # v2.14.0: another channel's list chosen as the basis for a while (only requests)
    other = channel_lists.basis_rows(db, settings)
    if other is not None:
        return other
    repo = PriceListRepo(db)
    active = repo.active_list()
    if active is None or not active_list_fresh(active, settings):
        return active, []
    return active, [sellable_row(r) for r in repo.rows(active["id"])]


def sellable_row(row: dict) -> dict:
    if row.get("pending_price_rial") is None:
        return {**row, "price_held": False}
    return {**row, "price_held": True, "price_rial": None, "naghd": None, "raval": None}


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
        price_rial=int(row["price_rial"]) if row.get("price_rial") else None, qty=qty,
        # v2.14.0: staff see which list (and channel) the price came from
        price_list_id=(PriceListRepo(db).active_list() or {}).get("id"))
    db.audit(actor, "purchase_request_create", f"request id={created['id']}")
    db.add_event("item_request", created["id"], actor)
    return created


# ---- staff ---------------------------------------------------------------------------------------
def _product_and_price(db: OwnDB, reader: AccountingReader, settings: Settings, who: Identity,
                       request: dict, kala_code: int | None,
                       price_rial: int | None) -> tuple[int, dict | None, dict, int]:
    """(code, mapping, product, price) of an offer: the «سازه حساب» product (the
    row is mapped now if needed) and the price (staff's, else the list price -
    never a price that waits for a manager)."""
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
    if not price and request.get("row_key"):
        # the list price read now (None while a new price waits for a manager)
        current = row_by_key(db, settings, request["row_key"])
        price = int((current or {}).get("price_rial") or 0)
    if not price and not request.get("row_key"):
        price = int(request.get("price_rial") or 0)
    if price <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the price")
    return int(code), mapping, product, price


def offer_price(db: OwnDB, reader: AccountingReader, settings: Settings, who: Identity,
                request: dict, kala_code: int | None, price_rial: int | None,
                note: str = "") -> dict:
    """v2.9.2 «تأیید موجودی» (list price) or a price typed by staff: the customer
    gets it in the bot with «تأیید و خرید» / «نمی‌خواهم»; nothing is ordered yet.
    Offering again replaces the earlier price. Returns the request.
    v2.9.3: ``note`` (what staff typed in «پیام به مشتری») goes in the same message."""
    if request.get("kind") not in OFFER_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a purchase request")
    ownership.ensure_request_editable(request)
    ownership.take(db, who, "request", request)
    user = db.get_user_by_id(int(request["user_id"]))
    if user is None or user["status"] == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer cannot order")
    if not request.get("platform"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer has no messenger")
    code, mapping, product, price = _product_and_price(db, reader, settings, who, request,
                                                       kala_code, price_rial)
    qty = float(request.get("qty") or 1)
    updates = dict(status="seen", handled_at=now_iso(), handled_by=who.actor,
                   outcome=OUTCOME_OFFERED, kala_code=code, offer_price_rial=price,
                   offered_at=now_iso())
    if mapping:
        updates["mapping_id"] = mapping.get("id")
    if not str(request.get("product_name") or "").strip():
        updates["product_name"] = str(product.get("name") or "")
    row = db.update_item_request(int(request["id"]), **updates)
    note = clean_note(note)
    text = offer_text(price, qty, note)
    message = db.add_item_request_message(int(request["id"]), text, who.actor,
                                          purpose=PURPOSE_OFFER, note=note)
    ownership.log(db, who, ownership.A_PRICE_OFFER, "request", request, detail=f"price={price}")
    db.audit(who.actor, "purchase_offer", f"request id={request['id']} price={price}")
    db.add_event("item_request_message", message["id"], who.actor)
    return row


def answer_offer(db: OwnDB, settings: Settings, who: Identity, request: dict,
                 accept: bool) -> tuple[dict, dict | None]:
    """The customer's answer in the bot. «تأیید و خرید» -> a normal order at the
    offered price (payment details from staff next, the usual receipt deadline;
    phones only while sales are open). Returns (request, order or None)."""
    if request.get("outcome") != OUTCOME_OFFERED or request.get("status") == "done" \
            or not request.get("offer_price_rial") or not request.get("kala_code"):
        raise HTTPException(status.HTTP_409_CONFLICT, OFFER_GONE_DETAIL)
    if not accept:
        row = db.update_item_request(int(request["id"]), status="done", handled_at=now_iso(),
                                     handled_by=who.actor, outcome=OUTCOME_DECLINED)
        ownership.log(db, who, ownership.A_OFFER_DECLINE, "request", request)
        db.audit(who.actor, "purchase_offer_declined", f"request id={request['id']}")
        db.add_event(EVENT_OFFER_DECLINED, int(request["id"]), who.actor)
        return row, None
    state = sales.compute(db, settings)
    if not state.open:
        # the same sales windows as an order from the bot (phones only)
        raise HTTPException(status.HTTP_409_CONFLICT, f"{SALES_CLOSED_DETAIL}: {state.reason}")
    user = db.get_user_by_id(int(request["user_id"]))
    if user is None or user["status"] == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer cannot order")
    code = int(request["kala_code"])
    price = int(request["offer_price_rial"])
    qty = float(request.get("qty") or 1)
    variant = variant_text(request.get("color") or "", request.get("part") or "")
    base = str(request.get("product_name") or "").strip() or str(code)
    name = f"{base} — {variant}" if variant else base
    # v2.8.2: the receipt deadline starts with «ارسال اطلاعات پرداخت»
    with db.reservation_guard():
        order = db.create_order(
            int(user["id"]), settings.price_level_bot, round_half_up(qty * price), None,
            [(code, name, qty, float(price), request.get("mapping_id"), variant or None,
              request.get("color") or None, request.get("part") or None)],
            accounting_db=settings.database_name(), request_id=int(request["id"]),
            owner_id=request.get("owner_id"), ship_address=str(user.get("address") or ""))
    row = db.update_item_request(int(request["id"]), status="done", handled_at=now_iso(),
                                 handled_by=who.actor, outcome=OUTCOME_CONFIRMED,
                                 order_id=order["id"])
    ownership.log(db, who, ownership.A_OFFER_ACCEPT, "request", request,
                  detail=f"order={order['id']} price={price}")
    db.audit(who.actor, "purchase_offer_accepted",
             f"request id={request['id']} order id={order['id']}")
    db.add_event("order_created", order["id"], who.actor)
    db.add_event(EVENT_ORDER_CREATED, order["id"], who.actor)
    return row, order


def mark_unavailable(db: OwnDB, who: Identity, request: dict) -> dict:
    if request.get("kind") not in OFFER_KINDS:
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
