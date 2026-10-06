"""Customer-facing endpoints (bot / site channels)."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..schemas import (
    GroupOut,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    ProductPage,
    ReceiptIn,
    UserOut,
    UserRegister,
)
from ..security import get_api_identity
from ..util import now_utc, round_half_up

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/groups", response_model=list[GroupOut])
def groups(
    reader: AccountingReader = Depends(deps.get_reader),
    _: str = Depends(get_api_identity),
) -> list[GroupOut]:
    return [GroupOut(**g) for g in reader.list_groups()]


@router.get("/products", response_model=ProductPage)
def products(
    q: Optional[str] = Query(None),
    group: Optional[int] = Query(None),
    in_stock: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = Depends(get_api_identity),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> dict:
    level = settings.price_level_for(role)
    our_res = db.pending_reservations()
    return reader.list_products(
        q=q,
        group=group,
        in_stock=in_stock,
        page=page,
        page_size=page_size,
        level=level,
        our_reservations=our_res,
    )


@router.post("/users/register", response_model=UserOut)
def register(
    payload: UserRegister,
    db: OwnDB = Depends(deps.get_db),
    role: str = Depends(get_api_identity),
) -> UserOut:
    row = db.register_user(payload.platform, payload.chat_id, payload.name, payload.phone)
    db.audit(role, "register", f"user id={row['id']}")
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


def _merge_items(items) -> dict[int, float]:
    merged: dict[int, float] = {}
    for it in items:
        merged[it.kala_code] = merged.get(it.kala_code, 0.0) + it.qty
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
    if user["status"] != "approved" or user["person_code"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not approved")

    merged = _merge_items(payload.items)
    level = settings.price_level_for(role)

    # Serialize availability-check + reservation: without this lock two
    # concurrent orders can both pass the check and oversell the same stock.
    with db.reservation_guard():
        our_res = db.pending_reservations()
        detail = reader.get_products_for_order(list(merged.keys()), level, our_res)

        items_out: list[OrderItemOut] = []
        for kala_code, qty in merged.items():
            if qty > settings.max_order_qty:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Quantity for product {kala_code} exceeds the maximum of "
                    f"{settings.max_order_qty}",
                )
            prod = detail.get(kala_code)
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
        reserve_until = (
            now_utc() + timedelta(hours=settings.reserve_hours)
        ).isoformat(timespec="seconds")

        order = db.create_order(
            user["id"],
            level,
            total,
            reserve_until,
            [(it.kala_code, it.name, it.qty, it.unit_price) for it in items_out],
        )
    db.audit(role, "order_create", f"order id={order['id']}")
    return OrderOut(**order, payment_instructions=settings.bank_account_text or None)


@router.post("/orders/{order_id}/receipt", response_model=OrderOut)
def upload_receipt(
    order_id: int,
    payload: ReceiptIn,
    platform: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
) -> OrderOut:
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
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if order["status"] != "awaiting_payment":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Order in status {order['status']}; receipt not expected",
            )
        db.add_payment(order_id, payload.receipt_ref, "submitted")
        order = db.set_order_status(order_id, "receipt_uploaded")
    db.audit(role, "receipt_upload", f"order id={order_id}")
    return OrderOut(**order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    platform: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    role: str = Depends(get_api_identity),
    db: OwnDB = Depends(deps.get_db),
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
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return OrderOut(**order)


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
