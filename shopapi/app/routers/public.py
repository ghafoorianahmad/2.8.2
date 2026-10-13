"""Customer-facing endpoints (bot / site channels)."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .. import deps, receipts, security_watch
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..pricelist import catalog as phone_catalog
from ..pricelist.repo import PriceListRepo
from ..schemas import (
    GroupOut,
    InquiryIn,
    InquiryOut,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    ProductOut,
    ProductPage,
    ReceiptIn,
    SecurityReportIn,
    ShopStateOut,
    StatementOut,
    UserOut,
    UserRegister,
)
from ..security import get_api_identity, get_catalog_channel
from ..statement import build_statement
from ..text import mobile_key
from ..util import now_utc, round_half_up

router = APIRouter()
logger = logging.getLogger("shopapi.public")

SHOP_CLOSED_KEY = "shop_closed"


def shop_state(db: OwnDB) -> ShopStateOut:
    return ShopStateOut(closed=db.get_state(SHOP_CLOSED_KEY, "0") == "1")


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


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/groups", response_model=list[GroupOut])
def groups(
    reader: AccountingReader = Depends(deps.get_reader),
    _: str = Depends(get_catalog_channel),
) -> list[GroupOut]:
    return [GroupOut(**g) for g in reader.list_groups()]


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
    our_res = db.pending_reservations()
    phones = phone_catalog.load(db, settings)
    if not phones.codes:
        return reader.list_products(
            q=q, group=group, in_stock=in_stock, page=page, page_size=page_size,
            level=level, our_reservations=our_res,
        )
    # Phones are priced here, so filtering and paging happen after the overlay.
    everything = reader.list_products(
        q=q, group=group, in_stock=in_stock, page=1, page_size=1_000_000,
        level=level, our_reservations=our_res, include_codes=phones.codes,
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
    """One product (deep link ``kala_<code>``), also when out of stock."""
    level = settings.price_level_for(role)
    found = reader.get_products_for_order([code], level, db.pending_reservations()).get(code)
    phones = phone_catalog.load(db, settings)
    if found is not None and phones.has(code):
        # Also when every color is out: the customer may still send an inquiry.
        found = phones.overlay({**found, "code": code})
    elif found is None or not found.get("unit_price") or found["unit_price"] <= 0:
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
    _: str = Depends(get_api_identity),
) -> ShopStateOut:
    return shop_state(db)


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

    merged = _merge_items(payload.items)
    level = settings.price_level_for(role)
    phones = phone_catalog.load(db, settings)

    # Serialize availability-check + reservation: without this lock two
    # concurrent orders can both pass the check and oversell the same stock.
    with db.reservation_guard():
        our_res = db.pending_reservations()
        codes = list(dict.fromkeys(code for code, _ in merged))
        detail = reader.get_products_for_order(codes, level, our_res)

        items_out: list[OrderItemOut] = []
        for (kala_code, variant_id), qty in merged.items():
            if qty > settings.max_order_qty:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Quantity for product {kala_code} exceeds the maximum of "
                    f"{settings.max_order_qty}",
                )
            prod = detail.get(kala_code)
            if phones.has(kala_code):
                # Phone: priced per color from the active list, read now
                # (REQUIREMENTS §4), sold on the distributor's availability.
                if prod is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"Product {kala_code} is not available for sale")
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
                items_out.append(
                    OrderItemOut(
                        kala_code=kala_code,
                        name=f"{prod['name']} — {variant['color']}",
                        qty=qty,
                        unit_price=variant["unit_price"],
                        variant_id=variant_id,
                        variant=variant["color"],
                    )
                )
                continue
            if variant_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Product {kala_code} has no colors")
            if prod is None or prod.get("unit_price") is None or prod["unit_price"] <= 0:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Product {kala_code} is not available for sale")
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
        reserve_until = (
            now_utc() + timedelta(hours=settings.reserve_hours)
        ).isoformat(timespec="seconds")

        order = db.create_order(
            user["id"],
            level,
            total,
            reserve_until,
            [(it.kala_code, it.name, it.qty, it.unit_price, it.variant_id, it.variant)
             for it in items_out],
        )
    db.audit(role, "order_create", f"order id={order['id']}")
    db.add_event("order_created", order["id"], role)
    return OrderOut(
        **order,
        payment_instructions=settings.bank_account_text or None,
        payment_card_number=settings.payment_card_number or None,
        payment_sheba=settings.payment_sheba or None,
        payment_owner=settings.payment_owner or None,
    )


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
        if order["status"] != "awaiting_payment":
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


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    platform: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
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
    if role == "admin" and order.get("accounting_order_no") and order.get("invoice_state"):
        try:   # accounting down = no numbers (the card then says only that it was issued)
            numbers = reader.invoice_numbers([int(order["accounting_order_no"])]).get(
                int(order["accounting_order_no"]), [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("invoice numbers unavailable: %s", type(exc).__name__)
    return OrderOut(**order, invoice_numbers=numbers)


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
