"""Admin endpoints (admin API key required)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..accounting_reader import AccountingReader
from ..accounting_writer import AccountingWriter
from ..config import Settings
from ..db_own import OwnDB
from ..schemas import ApproveUserIn, OrderOut, PersonMatch, RejectIn, UserOut
from ..security import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/system-info")
def system_info(settings: Settings = Depends(deps.get_settings)) -> dict:
    """Read-only operational flags for admin clients (e.g. the desktop console).

    Exposes whether real accounting writes are enabled so a client can warn its
    operator instead of silently reporting a dry run as a real booking.
    Contains no secrets and performs no writes.
    """
    return {
        "accounting_write_enabled": settings.accounting_write_enabled,
        "write_allowed_on_host": settings.write_allowed(),
        "price_level_bot": settings.price_level_bot,
        "price_level_site": settings.price_level_site,
        "reserve_hours": settings.reserve_hours,
        "max_order_qty": settings.max_order_qty,
        "allow_shared_person_code": settings.allow_shared_person_code,
        "bank_account_text": settings.bank_account_text or None,
    }


@router.get("/users", response_model=list[UserOut])
def list_users(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: OwnDB = Depends(deps.get_db),
) -> list[UserOut]:
    return [UserOut(**u) for u in db.list_users(status_filter)]


@router.get("/persons/match", response_model=PersonMatch)
def match_person(
    mobile: str = Query(...),
    reader: AccountingReader = Depends(deps.get_reader),
) -> PersonMatch:
    match = reader.find_person_by_mobile(mobile)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching person")
    return PersonMatch(**match)


@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(
    user_id: int,
    payload: ApproveUserIn,
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> UserOut:
    with db.reservation_guard():
        user = db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        if not reader.person_code_exists(payload.person_code):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"person_code {payload.person_code} not found",
            )
        if not settings.allow_shared_person_code:
            other = db.get_user_by_person_code(payload.person_code)
            if other is not None and other["id"] != user_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"person_code {payload.person_code} is already linked to another user",
                )
        user = db.set_user_approved(user_id, payload.person_code)
    db.audit("admin", "user_approve", f"user id={user_id} person_code={payload.person_code}")
    return UserOut(**user)


@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_user(
    user_id: int,
    payload: Optional[RejectIn] = None,
    db: OwnDB = Depends(deps.get_db),
) -> UserOut:
    user = db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user = db.set_user_status(user_id, "rejected")
    reason = (payload.reason if payload and payload.reason else "")[:200]
    db.audit("admin", "user_reject", f"user id={user_id} reason={reason}")
    return UserOut(**user)


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    status_filter: str = Query("receipt_uploaded", alias="status"),
    db: OwnDB = Depends(deps.get_db),
) -> list[OrderOut]:
    return [OrderOut(**o) for o in db.list_orders(status_filter)]


@router.post("/orders/{order_id}/approve-payment", response_model=OrderOut)
def approve_payment(
    order_id: int,
    reader: AccountingReader = Depends(deps.get_reader),
    writer: AccountingWriter = Depends(deps.get_writer),
    db: OwnDB = Depends(deps.get_db),
) -> OrderOut:
    # Serialize the re-check + write so concurrent approvals cannot write the
    # same order twice or oversell.
    with db.reservation_guard():
        order = db.get_order(order_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if order["status"] != "receipt_uploaded":
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Order in status {order['status']}; cannot approve"
            )

        items = db.get_order_items(order_id)
        merged: dict[int, float] = {}
        for it in items:
            merged[it["kala_code"]] = merged.get(it["kala_code"], 0.0) + it["qty"]

        # Re-check availability excluding this order's own reservation.
        our_res_excl = db.pending_reservations(exclude_order_id=order_id)
        detail = reader.get_products_for_order(
            list(merged.keys()), order["price_level"], our_res_excl
        )
        for kala_code, qty in merged.items():
            prod = detail.get(kala_code)
            if prod is None or prod["available_qty"] < qty:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"Insufficient stock for product {kala_code}"
                )

        write_items = [(it["kala_code"], it["qty"], it["unit_price"]) for it in items]
        result = writer.write_order(order_id, order["user_person_code"], write_items)

        # The order is only "written" when a row really exists in the accounting DB:
        # either we committed it now, or an identical header was already there
        # (idempotent replay). A dry-run is rolled back and must NOT be reported
        # as written, otherwise the order could never be retried.
        if result.committed or result.idempotent:
            order = db.set_order_status(order_id, "written", result.accounting_order_no)
            db.set_payment_decided(order_id, "approved")
            db.audit(
                "admin",
                "approve_payment",
                f"order id={order_id} accounting_order_no={result.accounting_order_no} "
                f"committed={result.committed} idempotent={result.idempotent}",
            )
        else:
            db.audit(
                "admin",
                "approve_payment_dry_run",
                f"order id={order_id} would_be_codlp={result.accounting_order_no}",
            )
            order = db.get_order(order_id)
        return OrderOut(**order)


@router.post("/orders/{order_id}/reject-payment", response_model=OrderOut)
def reject_payment(
    order_id: int,
    payload: Optional[RejectIn] = None,
    db: OwnDB = Depends(deps.get_db),
) -> OrderOut:
    order = db.get_order(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order["status"] != "receipt_uploaded":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Order in status {order['status']}; cannot reject"
        )
    db.set_payment_decided(order_id, "rejected")
    order = db.set_order_status(order_id, "rejected")
    reason = (payload.reason if payload and payload.reason else "")[:200]
    db.audit("admin", "reject_payment", f"order id={order_id} reason={reason}")
    return OrderOut(**order)


@router.post("/orders/expire")
def expire_orders(db: OwnDB = Depends(deps.get_db)) -> dict:
    expired = db.expire_awaiting_orders()
    db.audit("admin", "expire_orders", f"expired={expired}")
    return {"expired": expired}
