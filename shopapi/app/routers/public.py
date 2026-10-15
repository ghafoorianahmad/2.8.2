"""Customer-facing endpoints (bot / site channels)."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from .. import deps, groups as group_config, order_timeout, receipts, sales, security_watch
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..pricelist import catalog as phone_catalog
from ..pricelist.repo import PriceListRepo
from ..schemas import (
    GroupOut,
    InquiryIn,
    InquiryOut,
    ItemRequestIn,
    ItemRequestOut,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    ProductOut,
    ProductPage,
    ReceiptIn,
    RequestSearchItem,
    SecurityReportIn,
    ShopStateOut,
    StatementFullOut,
    StatementOut,
    UserOut,
    UserRegister,
)
from ..security import get_api_identity, get_catalog_channel
from ..statement import build_full_statement, build_statement
from ..text import mobile_key
from ..util import now_utc, round_half_up

router = APIRouter()
logger = logging.getLogger("shopapi.public")

IDEMPOTENCY_HOURS = 24
#: shopapi detail when an order is refused because sales are closed (bot maps it).
#: Only orders with phones (price-list items) are refused; the detail is unchanged.
SALES_CLOSED_DETAIL = "Sales are closed"
RECEIPT_TOO_LATE_DETAIL = "Receipt deadline passed; order cancelled"
#: v2.6.0: no valid payment card configured -> no checkout (never a placeholder card).
PAYMENT_NOT_CONFIGURED_DETAIL = "Payment details are not configured"
#: v2.6.0: unavailable item requests per customer and day (spam guard).
ITEM_REQUESTS_PER_DAY = 10
#: v2.6.1: why a cart item is refused at the final submit (the bot maps these;
#: the product code follows "Product ").
NOT_FOR_SALE_DETAIL = "is not available for sale"
ON_INQUIRY_DETAIL = "is price on inquiry"
NOT_IN_PRICE_LIST_DETAIL = "is not in the current price list"


def variant_text(color: str, part: str) -> str:
    """«Black — ZAA» (color, then part / region); just the color without a part."""
    return " — ".join(p for p in (str(color or "").strip(), str(part or "").strip()) if p)


def _refuse(kala_code: int, reason: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Product {kala_code} {reason}")


def shop_state(db: OwnDB, settings: Settings) -> ShopStateOut:
    state = sales.compute(db, settings)
    cfg = group_config.load(db)
    return ShopStateOut(
        closed=not state.open, sales_open=state.open,
        receipt_deadline_minutes=settings.receipt_deadline_minutes,
        payment_ready=settings.payment_ready(),
        catalog_ready=cfg.configured,
        phone_groups_ready=cfg.phone_configured,
        **{k: v for k, v in state.as_dict().items() if k != "open"},
    )


def customer_view(product: dict, cfg: group_config.GroupConfig,
                  phones: phone_catalog.PhoneCatalog, *, in_stock: bool) -> dict | None:
    """A reader product as a customer may see it, or None (hidden). v2.6.0:

    * only groups chosen «show in bot»;
    * v2.6.1: an item of a «price on inquiry» group without any price (also in
      or out of stock), never orderable;
    * a phone (an item of a phone group) only while it is in the current valid
      price list with an available color, priced only from the list;
    * anything else at its accounting price, with ``in_stock`` only in stock.
    Groups inherit every flag from their ancestors (``groups.py``).
    """
    group = product.get("group")
    if not cfg.visible(group):
        return None
    if cfg.on_inquiry(group):
        return {**product, "unit_price": 0.0, "priced_by": "inquiry", "variants": None,
                "price_on_inquiry": True}
    if cfg.is_phone(group):
        if not phones.sellable(product["code"]):
            return None
        return phones.overlay(product)
    if product.get("unit_price") is None or float(product["unit_price"]) <= 0:
        return None
    if in_stock and float(product.get("available_qty") or 0) <= 0:
        return None
    return {**product, "priced_by": "accounting", "variants": None}


def auto_match(db: OwnDB, reader: AccountingReader, settings: Settings, user: dict) -> dict:
    """Recipe R4: approve a pending customer whose verified mobile belongs to
    exactly one accounting person that no other customer is linked to.
    The accounting DB being down only means "stays pending"."""
    try:
        match = reader.find_person_by_mobile(user["phone"])
    except Exception as exc:  # pyodbc errors, timeouts
        logger.warning("auto-match skipped: %s", type(exc).__name__)
        return user
    if not match or match.get("code") is None:
        return user
    code = int(match["code"])
    with db.reservation_guard():
        other = db.get_user_by_person_code(code)
        if other is not None and other["id"] != user["id"] and not settings.allow_shared_person_code:
            return user
        user = db.set_user_approved(user["id"], code)
    db.audit("system:auto_match", "user_auto_approve", f"user id={user['id']} person_code={code}")
    db.add_event("customer_auto_approved", user["id"], "system:auto_match")
    return user


def same_database(order_db: str | None, settings: Settings) -> bool:
    """The order belongs to the connected accounting database (never a guess:
    an order without a recorded database matches none)."""
    return bool(order_db) and order_db.strip().lower() == settings.database_name().lower()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/groups", response_model=list[GroupOut])
def groups(
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    role: str = Depends(get_catalog_channel),
) -> list[GroupOut]:
    """Customers: only the groups chosen «show in bot» in ShopAdmin (v2.6.0).
    Staff (ShopAdmin's products page) see every group."""
    rows = reader.list_groups()
    cfg = group_config.load(db)
    cfg.parents = group_config.parent_map(rows)
    return [GroupOut(**g) for g in rows
            if role == "staff" or cfg.visible(g.get("code"))]


@router.get("/products", response_model=ProductPage)
def products(
    q: Optional[str] = Query(None),
    group: Optional[int] = Query(None),
    in_stock: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = Depends(get_catalog_channel),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> dict:
    level = settings.price_level_for(role)
    if role == "staff":
        return _staff_products(reader, db, settings, q=q, group=group, in_stock=in_stock,
                               page=page, page_size=page_size, level=level)
    cfg = group_config.load(db, reader)
    if group is not None and not cfg.visible(group):
        return {"total": 0, "page": page, "page_size": page_size, "items": []}
    our_res = db.pending_reservations()
    phones = phone_catalog.load(db, settings)
    # Groups and phones are decided here, so filtering and paging happen after.
    # A group lists its subgroups' items too (v2.6.1 tree).
    everything = reader.list_products(
        q=q, group=None, in_stock=in_stock, page=1, page_size=1_000_000,
        level=level, our_reservations=our_res, include_codes=phones.codes,
        include_groups=cfg.inquiry_groups(),
    )
    items = [view for it in everything["items"]
             if (group is None or int(group) in cfg.chain(it.get("group")))
             and (view := customer_view(it, cfg, phones, in_stock=in_stock)) is not None]
    start = (page - 1) * page_size
    return {"total": len(items), "page": page, "page_size": page_size,
            "items": items[start:start + page_size]}


def _staff_products(reader: AccountingReader, db: OwnDB, settings: Settings, *, q, group,
                    in_stock: bool, page: int, page_size: int, level: int) -> dict:
    """ShopAdmin's products page: every group, list prices where mapped."""
    phones = phone_catalog.load(db, settings)
    everything = reader.list_products(
        q=q, group=group, in_stock=in_stock, page=1, page_size=1_000_000,
        level=level, our_reservations=db.pending_reservations(), include_codes=phones.codes,
    )
    items = [phones.overlay(it) for it in everything["items"]]
    if in_stock:
        items = [it for it in items if it["available_qty"] > 0]
    start = (page - 1) * page_size
    return {"total": len(items), "page": page, "page_size": page_size,
            "items": items[start:start + page_size]}


@router.get("/products/{code}", response_model=ProductOut)
def product(
    code: int,
    role: str = Depends(get_catalog_channel),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> ProductOut:
    """One product (deep link ``kala_<code>``). An accessory also when out of
    stock (the bot offers a request then); a phone only while it is in the
    current valid list; nothing of a hidden group (v2.6.0)."""
    level = settings.price_level_for(role)
    found = reader.get_products_for_order([code], level, db.pending_reservations()).get(code)
    if found is not None:
        found = customer_view({**found, "code": code}, group_config.load(db, reader),
                              phone_catalog.load(db, settings), in_stock=False)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return ProductOut(
        code=code,
        name=found["name"],
        group=found.get("group"),
        unit_price=found["unit_price"] or 0.0,
        available_qty=found["available_qty"],
        image=found.get("image"),
        priced_by=found.get("priced_by", "accounting"),
        variants=found.get("variants"),
        price_on_inquiry=bool(found.get("price_on_inquiry")),
    )


@router.post("/inquiries", response_model=InquiryOut, status_code=status.HTTP_201_CREATED)
def create_inquiry(
    payload: InquiryIn,
    role: str = Depends(get_api_identity),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> InquiryOut:
    """Inquiry for an unavailable item (REQUIREMENTS §4): no order and no price,
    only a note to the shop with the product and the color."""
    user = db.get_user_by_platform(payload.platform, payload.chat_id)
    if user is None or user["status"] == "rejected":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    level = settings.price_level_for(role)
    found = reader.get_products_for_order([payload.kala_code], level, {}).get(payload.kala_code)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    color = ""
    if payload.variant_id is not None:
        variant = phone_catalog.load(db, settings).variant(payload.kala_code, payload.variant_id)
        if variant is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown color")
        color = variant["color"]
    inquiry = PriceListRepo(db).add_inquiry(
        user["id"], payload.kala_code, payload.variant_id, str(found["name"] or ""), color
    )
    db.audit(role, "inquiry_create", f"inquiry id={inquiry['id']}")
    db.add_event("price_inquiry", inquiry["id"], role)
    return InquiryOut(**{**inquiry, "customer_name": None})


@router.get("/shop/state", response_model=ShopStateOut)
def get_shop_state(
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: str = Depends(get_api_identity),
) -> ShopStateOut:
    return shop_state(db, settings)


@router.post("/users/register", response_model=UserOut)
def register(
    payload: UserRegister,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    role: str = Depends(get_api_identity),
) -> UserOut:
    """Register from a verified contact (the bot accepts only Bale's own
    share-contact). A known mobile is approved at once (R4); otherwise the
    customer waits for staff. A pending customer sharing again is re-matched,
    e.g. after the shop entered them in the accounting software."""
    key = mobile_key(payload.phone)
    if key is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a mobile number")
    phone = "0" + key
    existing = db.get_user_by_platform(payload.platform, payload.chat_id)
    if existing is None:
        row = db.register_user(payload.platform, payload.chat_id, payload.name, phone)
        db.audit(role, "register", f"user id={row['id']}")
    elif existing["status"] == "pending":
        row = db.update_user_contact(existing["id"], payload.name, phone)
    else:
        return UserOut(**existing)
    row = auto_match(db, reader, settings, row)
    if existing is None and row["status"] == "pending":
        db.add_event("customer_registered", row["id"], role)
    return UserOut(**row)


@router.get("/users/{platform}/{chat_id}", response_model=UserOut)
def get_user(
    platform: str,
    chat_id: str,
    db: OwnDB = Depends(deps.get_db),
    _: str = Depends(get_api_identity),
) -> UserOut:
    user = db.get_user_by_platform(platform, chat_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return UserOut(**user)


def _merge_items(items) -> dict[tuple[int, int | None], float]:
    """Quantities per (product, color); a color is None for normal products."""
    merged: dict[tuple[int, int | None], float] = {}
    for it in items:
        key = (it.kala_code, it.variant_id)
        merged[key] = merged.get(key, 0.0) + it.qty
    return merged


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    role: str = Depends(get_api_identity),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> OrderOut:
    user = db.get_user_by_platform(payload.platform, payload.chat_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    approved = user["status"] == "approved" and user["person_code"] is not None
    if user["status"] == "rejected" or (not approved and settings.pending_max_order_items <= 0):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not approved")

    idem = (idempotency_key or "").strip() or None
    if idem is not None and not (8 <= len(idem) <= 128 and idem.isprintable()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Idempotency-Key")

    def _out(o: dict) -> OrderOut:
        return OrderOut(
            **o,
            payment_instructions=settings.bank_account_text or None,
            payment_card_number=settings.payment_card_number or None,
            payment_sheba=settings.payment_sheba or None,
            payment_owner=settings.payment_owner or None,
        )

    merged = _merge_items(payload.items)
    level = settings.price_level_for(role)
    phones = phone_catalog.load(db, settings)
    cfg = group_config.load(db, reader)
    # A retry of an order placed just before closing time must still get it back,
    # so the sales check comes after the idempotency lookup (inside the guard).
    sales_state = sales.compute(db, settings)

    # Serialize availability-check + reservation: without this lock two
    # concurrent orders can both pass the check and oversell the same stock.
    with db.reservation_guard():
        if idem is not None:
            seen = db.find_idempotent(idem)
            if seen is not None:
                if seen["user_id"] != user["id"]:
                    raise HTTPException(status.HTTP_409_CONFLICT,
                                        "Idempotency-Key belongs to another customer")
                response.status_code = status.HTTP_200_OK
                return _out(db.get_order(seen["order_id"]))
        if not settings.payment_ready():
            # v2.6.0: the customer could not be told where to pay.
            raise HTTPException(status.HTTP_409_CONFLICT, PAYMENT_NOT_CONFIGURED_DETAIL)
        # Orders past their receipt deadline must not keep holding stock.
        order_timeout.cancel_overdue(db)
        our_res = db.pending_reservations()
        codes = list(dict.fromkeys(code for code, _ in merged))
        detail = reader.get_products_for_order(codes, level, our_res)
        # v2.6.1: a stale cart (the bot keeps it for days) is checked item by item
        # against what a customer may order NOW, before anything else: a hidden
        # group, a «price on inquiry» group, or a phone that is not in the current
        # valid price list (while sales are open). The bot names the item and
        # asks to remove it.
        for code in codes:
            prod = detail.get(code)
            if prod is None or not cfg.visible(prod.get("group")):
                raise _refuse(code, NOT_FOR_SALE_DETAIL)
            if cfg.on_inquiry(prod.get("group")):
                raise _refuse(code, ON_INQUIRY_DETAIL)
            # While phone sales are closed the "sales closed" answer below says
            # more (e.g. no valid list today); it comes first then.
            if sales_state.open and cfg.is_phone(prod.get("group")) \
                    and not phones.sellable(code):
                raise _refuse(code, NOT_IN_PRICE_LIST_DETAIL)
        # v2.6.0: a phone = an item of a phone group (never "has a price-list
        # mapping": without a list nothing was mapped and phones slipped through
        # as accessories while sales were closed). Read from the accounting DB
        # now, so the gate holds even for a stale cart. Subgroups inherit (v2.6.1).
        phone_codes = {code for code in codes
                       if detail.get(code) is not None and cfg.is_phone(detail[code].get("group"))}
        if not sales_state.open and phone_codes:
            # Closed (no fresh list, closing time, Friday, holiday, manual close)
            # blocks ONLY phones; accessories and other items stay orderable.
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{SALES_CLOSED_DETAIL}: {sales_state.reason}")

        items_out: list[OrderItemOut] = []
        for (kala_code, variant_id), qty in merged.items():
            if qty > settings.max_order_qty:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Quantity for product {kala_code} exceeds the maximum of "
                    f"{settings.max_order_qty}",
                )
            prod = detail[kala_code]          # checked above
            if kala_code in phone_codes:
                # Phone: priced per color ONLY from the current valid list, read
                # now (REQUIREMENTS §4), sold on the distributor's availability.
                if variant_id is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"Choose a color for product {kala_code}")
                variant = phones.variant(kala_code, variant_id)
                if variant is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"Unknown color for product {kala_code}")
                if not variant["available"]:
                    raise HTTPException(status.HTTP_409_CONFLICT,
                                        f"Color not available for product {kala_code}")
                # v2.6.2: the color AND the part / region code the customer picked
                chosen = variant_text(variant["color"], variant.get("part") or "")
                items_out.append(
                    OrderItemOut(
                        kala_code=kala_code,
                        name=f"{prod['name']} — {chosen}",
                        qty=qty,
                        unit_price=variant["unit_price"],
                        variant_id=variant_id,
                        variant=chosen,
                        color=variant["color"],
                        part=variant.get("part") or None,
                    )
                )
                continue
            if variant_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Product {kala_code} has no colors")
            if prod.get("unit_price") is None or prod["unit_price"] <= 0:
                raise _refuse(kala_code, NOT_FOR_SALE_DETAIL)
            if prod["available_qty"] < qty:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Insufficient stock for product {kala_code}",
                )
            items_out.append(
                OrderItemOut(
                    kala_code=kala_code,
                    name=prod["name"],
                    qty=qty,
                    unit_price=prod["unit_price"],
                )
            )

        total = sum(round_half_up(it.qty * it.unit_price) for it in items_out)
        if not approved:
            # Customers awaiting approval: capped, counting their other open orders.
            _, open_qty = db.open_order_totals(user["id"])
            # Item count only: prices fluctuate, so there is no amount cap.
            if open_qty + sum(it.qty for it in items_out) > settings.pending_max_order_items:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Order exceeds the limit for customers awaiting approval",
                )
        # The receipt deadline: no receipt by then = cancelled locally.
        reserve_until = (
            now_utc() + timedelta(minutes=settings.receipt_deadline_minutes)
        ).isoformat(timespec="seconds")

        order = db.create_order(
            user["id"],
            level,
            total,
            reserve_until,
            [(it.kala_code, it.name, it.qty, it.unit_price, it.variant_id, it.variant,
              it.color, it.part) for it in items_out],
            accounting_db=settings.database_name(),
        )
        if idem is not None:
            db.save_idempotent(
                idem, user["id"], order["id"],
                (now_utc() + timedelta(hours=IDEMPOTENCY_HOURS)).isoformat(timespec="seconds"),
            )
    db.audit(role, "order_create", f"order id={order['id']}")
    db.add_event("order_created", order["id"], role)
    return _out(order)


@router.post("/orders/{order_id}/receipt", response_model=OrderOut)
def upload_receipt(
    order_id: int,
    payload: ReceiptIn,
    platform: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> OrderOut:
    image = None
    if payload.data_b64:
        try:
            image = receipts.decode(payload.data_b64, settings.receipt_max_bytes)
        except receipts.ReceiptError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Receipt: {exc}") from None
    with db.reservation_guard():
        order = db.get_order(order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if role != "admin":
            # Non-admin callers must prove ownership (same rule as GET /orders/{id}),
            # otherwise any channel key could attach a receipt to another customer's order.
            if not platform or not chat_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
            user = db.get_user_by_platform(platform, chat_id)
            if user is None or user["id"] != order["user_id"]:
                security_watch.report(db, "order_probe", f"{platform}:{chat_id}")
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if order["status"] == "awaiting_payment" and order.get("reserve_until") \
                and order["reserve_until"] <= now_utc().isoformat(timespec="seconds"):
            # Past the deadline but the background check has not run yet.
            order_timeout.cancel_overdue(db)
            raise HTTPException(status.HTTP_409_CONFLICT, RECEIPT_TOO_LATE_DETAIL)
        if order["status"] != "awaiting_payment":
            if order.get("cancel_reason") == "receipt_timeout":
                raise HTTPException(status.HTTP_409_CONFLICT, RECEIPT_TOO_LATE_DETAIL)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Order in status {order['status']}; receipt not expected",
            )
        file_name = content_type = None
        folder = settings.receipts_path()
        if image is not None and folder is not None:
            data, content_type, ext = image
            file_name = receipts.store(folder, order_id, data, ext)
        db.add_payment(order_id, payload.receipt_ref, "submitted", file_name, content_type)
        order = db.set_order_status(order_id, "receipt_uploaded")
    db.audit(role, "receipt_upload", f"order id={order_id}")
    db.add_event("receipt_uploaded", order_id, role)
    return OrderOut(**order)


#: v2.6.2: the customer cancelled their own order (before any receipt).
CANCEL_BY_CUSTOMER = "customer"
EVENT_CUSTOMER_CANCELLED = "order_cancelled_by_customer"
#: ... and it had already been written to «سازه حساب»: only staff are told (ShopAdmin).
EVENT_CUSTOMER_CANCELLED_WRITTEN = "order_cancel_written"
RECEIPT_SENT_DETAIL = "Receipt already sent; the order cannot be cancelled"


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    platform: str = Query(...),
    chat_id: str = Query(...),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
) -> OrderOut:
    """The customer cancels their own order while no receipt was sent (v2.6.2).
    Local only: «سازه حساب» is never touched. An order already written there is
    cancelled here too and staff get a ShopAdmin notice to handle it by hand."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available on this channel")
    with db.reservation_guard():
        order = db.get_order(order_id)
        user = db.get_user_by_platform(platform, chat_id)
        if order is None or user is None or user["id"] != order["user_id"]:
            if order is not None:
                security_watch.report(db, "order_probe", f"{platform}:{chat_id}")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if order["status"] == "receipt_uploaded" or order.get("has_receipt"):
            raise HTTPException(status.HTTP_409_CONFLICT, RECEIPT_SENT_DETAIL)
        if order["status"] != "awaiting_payment" or db.list_payments(order_id):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Order in status {order['status']}; cannot be cancelled")
        if not db.cancel_order_locally(order_id, CANCEL_BY_CUSTOMER):
            raise HTTPException(status.HTTP_409_CONFLICT, "Order cannot be cancelled")
    actor = f"{role}:{platform}"
    db.audit(actor, "order_customer_cancel", f"order id={order_id}")
    db.add_event(EVENT_CUSTOMER_CANCELLED, order_id, actor)
    if order.get("accounting_order_no"):
        db.audit(actor, "order_cancel_written",
                 f"order id={order_id} accounting_order_no={order['accounting_order_no']} "
                 f"db={order.get('accounting_db') or '-'} (not changed in accounting)")
        db.add_event(EVENT_CUSTOMER_CANCELLED_WRITTEN, order_id, actor)
    return OrderOut(**db.get_order(order_id))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    platform: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
) -> OrderOut:
    order = db.get_order(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if role != "admin":
        # Non-admin callers must prove ownership via their platform + chat_id.
        if not platform or not chat_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        user = db.get_user_by_platform(platform, chat_id)
        if user is None or user["id"] != order["user_id"]:
            security_watch.report(db, "order_probe", f"{platform}:{chat_id}")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    numbers: list[str] = []
    if role == "admin" and order.get("accounting_order_no") and order.get("invoice_state") \
            and same_database(order.get("accounting_db"), settings):
        # Invoice numbers only from the database the order was written to.
        try:   # accounting down = no numbers (the card then says only that it was issued)
            numbers = reader.invoice_numbers([int(order["accounting_order_no"])]).get(
                int(order["accounting_order_no"]), [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("invoice numbers unavailable: %s", type(exc).__name__)
    person_name = None
    if role == "admin" and order.get("user_person_code") is not None:
        person_name = reader.person_names([order["user_person_code"]]).get(
            int(order["user_person_code"]))
    return OrderOut(**order, invoice_numbers=numbers, person_name=person_name)


@router.get("/users/{platform}/{chat_id}/orders", response_model=list[OrderOut])
def list_user_orders(
    platform: str,
    chat_id: str,
    db: OwnDB = Depends(deps.get_db),
    _: str = Depends(get_api_identity),
) -> list[OrderOut]:
    user = db.get_user_by_platform(platform, chat_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return [OrderOut(**o) for o in db.list_orders_for_user(user["id"])]


@router.get("/users/{platform}/{chat_id}/statement", response_model=StatementOut)
def statement(
    platform: str,
    chat_id: str,
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(10, ge=1, le=50),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    role: str = Depends(get_api_identity),
) -> dict:
    """Account statement: only for the customer's own verified account (bot channel)."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available on this channel")
    user = db.get_user_by_platform(platform, chat_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user["status"] != "approved" or user["person_code"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not approved")
    data = reader.customer_statement(int(user["person_code"]), settings.statement_max_rows)
    return build_statement(data, page, page_size)


@router.get("/users/{platform}/{chat_id}/statement/full", response_model=StatementFullOut)
def statement_full(
    platform: str,
    chat_id: str,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    role: str = Depends(get_api_identity),
) -> dict:
    """The whole statement for the bot's PDF (v2.6.0): own verified account only."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available on this channel")
    user = db.get_user_by_platform(platform, chat_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user["status"] != "approved" or user["person_code"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not approved")
    code = int(user["person_code"])
    data = reader.customer_statement(code, settings.statement_max_rows)
    name = reader.person_names([code]).get(code) or str(user.get("name") or "")
    return {"person_code": code, "customer_name": name,
            **build_full_statement(data, settings.statement_max_rows)}


def _requesting_user(db: OwnDB, platform: str, chat_id: str) -> dict:
    user = db.get_user_by_platform(platform, chat_id)
    if user is None or user["status"] == "rejected":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/item-requests/search", response_model=list[RequestSearchItem])
def item_request_search(
    q: str = Query(min_length=2, max_length=100),
    role: str = Depends(get_catalog_channel),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> list[RequestSearchItem]:
    """«درخواست کالای ناموجود»: names (no price, no stock) of products of the
    groups shown in the bot that match ``q`` (v2.6.0)."""
    cfg = group_config.load(db, reader)
    found = reader.list_products(q=q, in_stock=False, page=1, page_size=1_000_000,
                                 level=settings.price_level_for(role),
                                 include_groups=cfg.inquiry_groups())
    out = [RequestSearchItem(code=int(p["code"]), name=str(p["name"] or ""))
           for p in found["items"] if cfg.visible(p.get("group"))]
    return out[:8]


@router.post("/item-requests", response_model=ItemRequestOut,
             status_code=status.HTTP_201_CREATED)
def create_item_request(
    payload: ItemRequestIn,
    role: str = Depends(get_api_identity),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> dict:
    """A customer asks for an item that is not available (v2.6.0) or asks the
    price of a «price on inquiry» item (v2.6.1, ``kind=inquiry``): no order, no
    payment and nothing written to the accounting DB - only a note for staff
    (ShopAdmin notification + the «درخواست کالا» list; no admin-chat message)."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available on this channel")
    user = _requesting_user(db, payload.platform, payload.chat_id)
    text = " ".join(payload.text.split())[:300]
    name = ""
    if payload.kind == "inquiry" and payload.kala_code is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the product")
    if payload.kala_code is not None:
        found = reader.get_products_for_order(
            [payload.kala_code], settings.price_level_for(role), {}).get(payload.kala_code)
        cfg = group_config.load(db, reader)
        if found is None or not cfg.visible(found.get("group")):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        if payload.kind == "inquiry" and not cfg.on_inquiry(found.get("group")):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Product is not price on inquiry")
        name = str(found.get("name") or "")
    if not name and len(text) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Describe the item")
    since = (now_utc() - timedelta(days=1)).isoformat(timespec="seconds")
    if db.count_item_requests_since(user["id"], since) >= ITEM_REQUESTS_PER_DAY:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests today")
    row = db.add_item_request(user["id"], payload.kala_code, name, text, payload.kind)
    db.audit(role, "item_request_create", f"request id={row['id']} kind={payload.kind}")
    db.add_event("item_request", row["id"], role)
    return {**row, "customer_name": None, "person_code": None, "customer_phone": None}


@router.post("/security/report", status_code=status.HTTP_204_NO_CONTENT)
def security_report(
    payload: SecurityReportIn,
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
) -> Response:
    """The bot reports a suspicious act; repeated ones alert the owner."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this key")
    if payload.kind not in security_watch.BOT_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown kind")
    security_watch.report(db, payload.kind, f"{payload.platform}:{payload.chat_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
