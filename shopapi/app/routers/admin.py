"""Admin endpoints.

Callers: signed-in staff (bearer session; role checked per endpoint) or the
server-local service key used by the bots. Every action is audited with the
acting account's username.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from .. import archive, deps, ownership, receipts, sales, tracking
from ..accounting_reader import AccountingReader
from ..accounting_writer import (
    AccountingConfigError,
    AccountingLockTimeout,
    AccountingWriteRefused,
    AccountingWriter,
    DuplicateOrderNumber,
)
from ..config import Settings
from ..db_own import OwnDB
from ..schemas import ShipIn
from ..schemas import (
    ApproveUserIn,
    AssignIn,
    OrderOut,
    PersonMatch,
    RejectIn,
    SalesActionIn,
    ShopStateIn,
    ShopStateOut,
    UserOut,
)
from ..security import Identity, require_permission, require_signed_in
from ..staff import (
    P_CUSTOMERS_DECIDE,
    P_CUSTOMERS_VIEW,
    P_EVENTS,
    P_ORDERS_CANCEL,
    P_ORDERS_EXPIRE,
    P_ORDERS_ASSIGN,
    P_ORDERS_SHIP,
    P_ORDERS_VIEW,
    P_PAYMENTS_DECIDE,
    P_SHOP_STATE,
    P_VIEW,
)
from .public import shop_state

router = APIRouter(prefix="/admin")

CAN_VIEW = Depends(require_permission(P_VIEW))
CAN_DECIDE_CUSTOMERS = Depends(require_permission(P_CUSTOMERS_DECIDE))
CAN_DECIDE_PAYMENTS = Depends(require_permission(P_PAYMENTS_DECIDE))
CAN_EXPIRE = Depends(require_permission(P_ORDERS_EXPIRE))
CAN_SHIP = Depends(require_permission(P_ORDERS_SHIP))
CAN_SET_SHOP_STATE = Depends(require_permission(P_SHOP_STATE))
# v2.7.0: what a «کاربر فروش» needs, apart from the rest of the admin view
CAN_VIEW_ORDERS = Depends(require_permission(P_ORDERS_VIEW))
CAN_VIEW_CUSTOMERS = Depends(require_permission(P_CUSTOMERS_VIEW))
CAN_VIEW_EVENTS = Depends(require_permission(P_EVENTS))
CAN_CANCEL = Depends(require_permission(P_ORDERS_CANCEL))
SIGNED_IN = Depends(require_signed_in)

#: Event: our Codlp exists more than once in KalaOrder (alert the admin; nothing deleted).
EVENT_DUPLICATE_ORDER_NO = "accounting_duplicate_order"

#: Orders that may be marked as shipped (paid and accepted).
SHIPPABLE_STATUSES = ("approved", "written")


@router.get("/system-info")
def system_info(
    settings: Settings = Depends(deps.get_settings),
    _: Identity = SIGNED_IN,
) -> dict:
    """Read-only operational flags for admin clients (e.g. the desktop console).

    Exposes whether real accounting writes are enabled so a client can warn its
    operator instead of silently reporting a dry run as a real booking.
    Contains no secrets and performs no writes.
    """
    return {
        "accounting_write_enabled": settings.write_allowed(),
        "test_mode": settings.is_test_db(),
        "write_allowed_on_host": settings.write_allowed(),
        "accounting_database": settings.database_name(),
        "database_allowlisted": settings.database_allowlisted() or settings.is_test_db(),
        "status_code_configured": settings.status_code_problem() is None,
        "price_level_bot": settings.price_level_bot,
        "price_level_site": settings.price_level_site,
        "receipt_deadline_minutes": settings.receipt_deadline_minutes,
        "max_order_qty": settings.max_order_qty,
        "allow_shared_person_code": settings.allow_shared_person_code,
        "bank_account_text": settings.bank_account_text or None,
    }


@router.get("/users", response_model=list[UserOut])
def list_users(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW_CUSTOMERS,
) -> list[UserOut]:
    return [UserOut(**u) for u in db.list_users(status_filter)]


@router.get("/persons/match", response_model=PersonMatch)
def match_person(
    mobile: str = Query(...),
    reader: AccountingReader = Depends(deps.get_reader),
    _: Identity = CAN_DECIDE_CUSTOMERS,
) -> PersonMatch:
    match = reader.find_person_by_mobile(mobile)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching person")
    return PersonMatch(**match)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW_CUSTOMERS,
) -> UserOut:
    user = db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return UserOut(**user)


def _create_person(writer: AccountingWriter, user: dict, payload: ApproveUserIn) -> int:
    """Recipe §5.1 for a customer without a person code. Returns the code."""
    first = (payload.first_name or "").strip()
    last = (payload.last_name or "").strip()
    if not last:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "last_name is required to create a person (or give person_code)",
        )
    try:
        result = writer.create_person(first, last, user["phone"])
    except AccountingLockTimeout:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accounting is busy; try again") from None
    except AccountingWriteRefused:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Accounting writes are disabled; the person was not created") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    if result.existing:
        if result.ambiguous:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This mobile belongs to several persons; choose person_code",
            )
        return int(result.person_code)
    if not result.committed:
        # Dry-run (ACCOUNTING_WRITE_ENABLED=false): rolled back, nothing to link.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Accounting writes are disabled; the person was not created",
        )
    return int(result.person_code)


@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(
    user_id: int,
    payload: ApproveUserIn,
    reader: AccountingReader = Depends(deps.get_reader),
    writer: AccountingWriter = Depends(deps.get_writer),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_DECIDE_CUSTOMERS,
) -> UserOut:
    user = db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    created = False
    if payload.person_code is None:
        person_code = _create_person(writer, user, payload)
        created = True
        name = f"{(payload.first_name or '').strip()} {(payload.last_name or '').strip()}".strip()
        db.update_user_contact(user_id, name=name)
    else:
        person_code = payload.person_code
    with db.reservation_guard():
        user = db.get_user_by_id(user_id)
        if not created and not reader.person_code_exists(person_code):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"person_code {person_code} not found",
            )
        if not settings.allow_shared_person_code:
            other = db.get_user_by_person_code(person_code)
            if other is not None and other["id"] != user_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"person_code {person_code} is already linked to another user",
                )
        user = db.set_user_approved(user_id, person_code)
    db.audit(
        who.actor, "user_approve",
        f"user id={user_id} person_code={person_code} created={created}",
    )
    db.add_event("customer_approved", user_id, who.actor)
    db.log_activity(staff_id=ownership.staff_id(who), actor=who.actor,
                    action=ownership.A_CUSTOMER_APPROVE, target_type="customer",
                    target_id=user_id, customer_id=user_id)
    return UserOut(**user)


@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_user(
    user_id: int,
    payload: Optional[RejectIn] = None,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_DECIDE_CUSTOMERS,
) -> UserOut:
    user = db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user = db.set_user_status(user_id, "rejected")
    reason = (payload.reason if payload and payload.reason else "")[:200]
    db.audit(who.actor, "user_reject", f"user id={user_id} reason={reason}")
    db.add_event("customer_rejected", user_id, who.actor)
    db.log_activity(staff_id=ownership.staff_id(who), actor=who.actor,
                    action=ownership.A_CUSTOMER_REJECT, target_type="customer",
                    target_id=user_id, customer_id=user_id)
    return UserOut(**user)


def order_out(db: OwnDB, who: Identity, order: dict, **extra) -> OrderOut:
    """An order for ShopAdmin with the ownership fields for this viewer (v2.8.0)."""
    fields = {**order, **ownership.owner_fields(db, who, order), **extra}
    return OrderOut(**fields)


def _person_names(reader: AccountingReader, orders: list[dict]) -> dict:
    try:
        return reader.person_names(o.get("user_person_code") for o in orders)
    except Exception:  # noqa: BLE001 - the list works without names (ShopAdmin shows the code)
        return {}


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    status_filter: str = Query("receipt_uploaded", alias="status"),
    mine: bool = Query(False),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    who: Identity = CAN_VIEW_ORDERS,
) -> list[OrderOut]:
    """v2.8.0: a sales user sees free orders and their own (``mine``: own only);
    another user's order is never listed. Archived orders: /admin/archive/orders."""
    orders = db.query_orders(status=status_filter or None, viewer_id=ownership.viewer_id(who),
                             mine_only=mine)
    if mine and ownership.is_manager(who) and who.user_id is not None:
        orders = [o for o in orders if o.get("owner_id") == who.user_id]
    # v2.6.0: the linked person's name from the accounting DB (one query).
    names = _person_names(reader, orders)
    return [order_out(db, who, o, person_name=names.get(o.get("user_person_code")))
            for o in orders]


def _visible_order(db: OwnDB, who: Identity, order_id: int) -> dict:
    return ownership.ensure_visible(who, db.get_order(order_id), "Order")


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order_admin(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    who: Identity = CAN_VIEW_ORDERS,
) -> OrderOut:
    order = _visible_order(db, who, order_id)
    names = _person_names(reader, [order])
    return order_out(db, who, order, person_name=names.get(order.get("user_person_code")))


@router.get("/orders/{order_id}/timeline")
def order_timeline(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW_ORDERS,
) -> list[dict]:
    """What was done on the order (and on the purchase request it came from).
    Names only for the manager; a sales user sees «شما» / nothing."""
    order = _visible_order(db, who, order_id)
    targets = [("order", order_id)]
    if order.get("request_id"):
        targets.append(("request", int(order["request_id"])))
    return ownership.timeline(db, who, db.list_activity(targets=targets, limit=500))


@router.post("/orders/{order_id}/claim", response_model=OrderOut)
def claim_order(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW_ORDERS,
) -> OrderOut:
    """«برمی‌دارم»: a free order becomes this user's (the others no longer see it)."""
    order = _visible_order(db, who, order_id)
    ownership.ensure_order_editable(order)
    ownership.take(db, who, "order", order)
    return order_out(db, who, db.get_order(order_id))


@router.post("/orders/{order_id}/assign", response_model=OrderOut)
def assign_order(
    order_id: int,
    payload: AssignIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW_ORDERS,
) -> OrderOut:
    """Hand the order over at any stage until it is finished (manager, «ارجاع سفارش»,
    or the owner). The new owner sees what was already done and continues."""
    order = _visible_order(db, who, order_id)
    ownership.ensure_order_editable(order)
    ownership.assign(db, who, "order", order, payload.staff_id)
    return order_out(db, who, db.get_order(order_id))


@router.get("/assignees")
def list_assignees(
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW_ORDERS,
) -> list[dict]:
    """Colleagues an order / request can be handed to (active, may see orders).
    Only id and display name; never a role, username or their work."""
    from ..staff import P_ORDERS_VIEW as _view, effective_permissions

    out = []
    for row in db.list_staff():
        if not row["active"] or row["id"] == who.user_id:
            continue
        perms = effective_permissions(row["role"], row.get("perm_grant"), row.get("perm_revoke"))
        if _view in perms:
            out.append({"id": row["id"],
                        "name": str(row["full_name"] or "").strip() or row["username"]})
    return out


@router.get("/activity")
def list_activity(
    staff_id: Optional[int] = Query(None, gt=0),
    customer_id: Optional[int] = Query(None, gt=0),
    date_from: Optional[str] = Query(None, max_length=40),
    date_to: Optional[str] = Query(None, max_length=40),
    limit: int = Query(500, ge=1, le=5000),
    db: OwnDB = Depends(deps.get_db),
    who: Identity = SIGNED_IN,
) -> list[dict]:
    """«گزارش فعالیت» (manager only): who did what, on which order / customer /
    request, and when. Dates are ISO (UTC) bounds: from <= ts < to."""
    if not ownership.is_manager(who):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers only")
    rows = db.list_activity(staff_id=staff_id, customer_id=customer_id, date_from=date_from,
                            date_to=date_to, limit=limit)
    return ownership.timeline(db, who, rows)


@router.get("/archive/orders", response_model=list[OrderOut])
def archived_orders(
    q: Optional[str] = Query(None, max_length=100),
    accounting_db: Optional[str] = Query(None, max_length=128),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_VIEW_ORDERS,
) -> list[OrderOut]:
    """«بایگانی» (read-only). A sales user: their own orders of the current fiscal
    year (the connected DB_NAME) only; the manager: everything, every year, search."""
    if ownership.is_manager(who):
        orders = db.query_orders(archived=True, accounting_db=accounting_db or None, q=q)
    else:
        orders = db.query_orders(archived=True, viewer_id=who.user_id,
                                 accounting_db=settings.database_name(), q=q)
    names = _person_names(reader, orders)
    return [order_out(db, who, o, person_name=names.get(o.get("user_person_code")))
            for o in orders]


@router.post("/archive/run")
def run_archive(
    db: OwnDB = Depends(deps.get_db),
    who: Identity = SIGNED_IN,
) -> dict:
    """Archive finished orders / requests now (manager; the weekly job does the same)."""
    if not ownership.is_manager(who):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers only")
    return archive.archive_now(db, who.actor)


@router.post("/orders/{order_id}/approve-payment", response_model=OrderOut)
def approve_payment(
    order_id: int,
    reader: AccountingReader = Depends(deps.get_reader),
    writer: AccountingWriter = Depends(deps.get_writer),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_DECIDE_PAYMENTS,
) -> OrderOut:
    # Serialize the re-check + write so concurrent approvals cannot write the
    # same order twice or oversell.
    with db.reservation_guard():
        order = _visible_order(db, who, order_id)
        if order["status"] != "receipt_uploaded":
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Order in status {order['status']}; cannot approve"
            )
        ownership.take(db, who, "order", order)
        if order["user_status"] != "approved" or order["user_person_code"] is None:
            # Orders of customers awaiting approval are written only after approval.
            raise HTTPException(status.HTTP_409_CONFLICT, "Customer is not approved yet")

        items = db.get_order_items(order_id)
        merged: dict[int, float] = {}
        for it in items:
            if it.get("variant_id") is not None:
                continue   # phone colors: availability came from the price list
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

        # v2.6.2: a phone line carries its color and part in the line description
        write_items = [(it["kala_code"], it["qty"], it["unit_price"])
                       + ((it["variant"],) if it.get("variant") else ()) for it in items]
        try:
            result = writer.write_order(order_id, order["user_person_code"], write_items)
        except AccountingLockTimeout:
            raise HTTPException(status.HTTP_409_CONFLICT, "Accounting is busy; try again") from None
        except AccountingConfigError as exc:
            db.audit(who.actor, "approve_payment_refused", f"order id={order_id} config: {exc}")
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Order status code is not configured") from None
        except DuplicateOrderNumber as exc:
            # Rolled back: nothing was written. Tell the admin; retry is safe.
            db.audit(who.actor, "approve_payment_duplicate",
                     f"order id={order_id} codlp={exc.codlp} rows={exc.count} (rolled back)")
            db.add_event(EVENT_DUPLICATE_ORDER_NO, order_id, who.actor)
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Duplicate accounting order number; nothing was written") from None

        # The order is only "written" when a row really exists in the accounting DB:
        # either we committed it now, or an identical header was already there
        # (idempotent replay). A dry-run is rolled back and must NOT be reported
        # as written, otherwise the order could never be retried.
        if result.committed or result.idempotent:
            order = db.set_order_status(order_id, "written", result.accounting_order_no,
                                        accounting_db=result.database or settings.database_name())
            db.set_payment_decided(order_id, "approved")
            db.audit(
                who.actor,
                "approve_payment",
                f"order id={order_id} accounting_order_no={result.accounting_order_no} "
                f"db={result.database or settings.database_name()} "
                f"committed={result.committed} idempotent={result.idempotent}",
            )
            db.add_event("payment_approved", order_id, who.actor)
            ownership.log(db, who, ownership.A_RECEIPT_APPROVE, "order", order)
            if result.duplicate_after_commit:
                # Another program wrote the same Codlp next to ours. Never delete
                # anything in the accounting DB: only alert the admin.
                db.audit("system:writer", "accounting_duplicate_order",
                         f"order id={order_id} codlp={result.accounting_order_no} "
                         f"rows={result.codlp_rows_after_commit}")
                db.add_event(EVENT_DUPLICATE_ORDER_NO, order_id, "system:writer")
        else:
            db.audit(
                who.actor,
                "approve_payment_dry_run",
                f"order id={order_id} would_be_codlp={result.accounting_order_no}",
            )
            order = db.get_order(order_id)
        return order_out(db, who, order)


@router.post("/orders/{order_id}/reject-payment", response_model=OrderOut)
def reject_payment(
    order_id: int,
    payload: Optional[RejectIn] = None,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_DECIDE_PAYMENTS,
) -> OrderOut:
    order = _visible_order(db, who, order_id)
    if order["status"] != "receipt_uploaded":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Order in status {order['status']}; cannot reject"
        )
    ownership.take(db, who, "order", order)
    db.set_payment_decided(order_id, "rejected")
    order = db.set_order_status(order_id, "rejected")
    reason = (payload.reason if payload and payload.reason else "")[:200]
    db.audit(who.actor, "reject_payment", f"order id={order_id} reason={reason}")
    db.add_event("payment_rejected", order_id, who.actor)
    ownership.log(db, who, ownership.A_RECEIPT_REJECT, "order", order, detail=reason)
    return order_out(db, who, order)


@router.post("/orders/expire")
def expire_orders(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_EXPIRE) -> dict:
    expired = db.expire_awaiting_orders()
    db.audit(who.actor, "expire_orders", f"expired={expired}")
    return {"expired": expired}


@router.get("/events")
def list_events(
    after: Optional[int] = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW_EVENTS,
) -> dict:
    """Notification feed for staff clients.

    Without ``after`` only the current position is returned, so a client that
    just started does not replay the whole history as fresh notifications.
    """
    if after is None:
        return {"last_id": db.last_event_id(), "items": []}
    items = db.list_events(after, limit)
    # A position beyond the newest event (e.g. the server database was
    # replaced) resyncs the client instead of silencing it forever.
    last_id = items[-1]["id"] if items else min(after, db.last_event_id())
    return {"last_id": last_id, "items": items}


@router.get("/orders/{order_id}/receipt")
def get_receipt_image(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_VIEW_ORDERS,
):
    """The newest receipt image of an order (JPEG/PNG)."""
    _visible_order(db, who, order_id)
    row = db.latest_receipt_file(order_id)
    folder = settings.receipts_path()
    path = receipts.resolve(folder, row["file_name"]) if row and folder else None
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No receipt image")
    return FileResponse(path, media_type=row["content_type"] or "application/octet-stream")


def courier_phone(raw: str) -> str:
    """Digits only (Persian / Arabic digits too); '' when nothing was typed."""
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    value = "".join(ch for ch in str(raw or "").translate(trans) if ch.isdigit() or ch == "+")
    if value and not (7 <= len(value.lstrip("+")) <= 15):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid courier phone")
    return value


@router.post("/orders/{order_id}/ship", response_model=OrderOut)
def ship_order(
    order_id: int,
    payload: ShipIn | None = None,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_SHIP,
) -> OrderOut:
    """«ارسال شد». v2.7.0: an optional courier name and phone go into the
    customer's message; without them the usual message only."""
    payload = payload or ShipIn()
    name = " ".join(payload.courier_name.split())
    phone = courier_phone(payload.courier_phone)
    order = _visible_order(db, who, order_id)
    if order["status"] not in SHIPPABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Order in status {order['status']}; cannot ship"
        )
    if order.get("shipped_at"):
        return order_out(db, who, order)
    ownership.ensure_order_editable(order)
    ownership.take(db, who, "order", order)
    order = db.set_shipped(order_id, name or None, phone or None)
    db.audit(who.actor, "order_ship", f"order id={order_id} courier={'yes' if name or phone else 'no'}")
    db.add_event(tracking.EVENT_SHIPPED, order_id, who.actor)
    ownership.log(db, who, ownership.A_SHIP, "order", order,
                  detail="courier" if name or phone else "")
    return order_out(db, who, order)


#: v2.7.0: orders staff may cancel (never one already paid and confirmed).
STAFF_CANCELLABLE = ("awaiting_payment", "receipt_uploaded")


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_CANCEL,
) -> OrderOut:
    """Staff cancel an order that is not confirmed yet. Local only: «سازه حساب»
    is never touched; an order already written there raises a ShopAdmin warning."""
    with db.reservation_guard():
        order = _visible_order(db, who, order_id)
        if order["status"] not in STAFF_CANCELLABLE:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Order in status {order['status']}; cannot be cancelled")
        ownership.take(db, who, "order", order)
        db.cancel_order_any(order_id, "staff", STAFF_CANCELLABLE)
    db.audit(who.actor, "order_staff_cancel", f"order id={order_id}")
    db.add_event("order_cancelled_by_staff", order_id, who.actor)
    ownership.log(db, who, ownership.A_CANCEL, "order", order)
    if order.get("accounting_order_no"):
        db.add_event("order_cancel_written", order_id, who.actor)
    return order_out(db, who, db.get_order(order_id))


@router.post("/orders/sync-invoices")
def sync_invoices(
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_EXPIRE,
) -> dict:
    """Check written orders for invoices now (also runs in the background)."""
    return {"changed": tracking.sync_invoices(db, reader, settings.database_name(), who.actor)}


@router.get("/shop/state", response_model=ShopStateOut)
def get_shop_state(
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: Identity = CAN_VIEW,
) -> ShopStateOut:
    return shop_state(db, settings)


@router.put("/shop/state", response_model=ShopStateOut)
def set_shop_state(
    payload: ShopStateIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_SET_SHOP_STATE,
) -> ShopStateOut:
    """Old switch (kept for older clients): closed -> «بستن فروش», else «باز کردن فروش»."""
    sales.set_override(db, settings, "close" if payload.closed else "open", who.actor)
    return shop_state(db, settings)


@router.post("/sales/action", response_model=ShopStateOut)
def sales_action(
    payload: SalesActionIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_SET_SHOP_STATE,
) -> ShopStateOut:
    """ShopAdmin buttons: «تعطیلی امروز» (holiday, closed until the next morning),
    «بستن فروش» (close now), «باز کردن فروش» (open until the next transition:
    a new list or the next closing time). Stored on the server and audited."""
    sales.set_override(db, settings, payload.action, who.actor)
    return shop_state(db, settings)
