"""Admin endpoints.

Callers: signed-in staff (bearer session; role checked per endpoint) or the
server-local service key used by the bots. Every action is audited with the
acting account's username.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from .. import archive, customer_details, deps, ownership, receipts, sales, tracking
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
from ..util import now_utc
from ..schemas import ShipIn
from ..schemas import (
    ApprovePaymentIn,
    ApproveUserIn,
    AssignIn,
    OrderCancelIn,
    OrderOut,
    PaymentInfoIn,
    PersonMatch,
    RejectIn,
    SalesActionIn,
    ShopStateIn,
    ShopStateOut,
    UserOut,
)
from ..security import Identity, require_any, require_permission, require_signed_in
from ..staff import (
    P_ACCOUNTING_WRITE,
    P_ACTIVITY,
    P_ARCHIVE,
    P_CUSTOMERS_DECIDE,
    P_CUSTOMERS_VIEW,
    P_DASHBOARD,
    P_ORDERS_CANCEL,
    P_ORDERS_EDIT,
    P_ORDERS_EXPIRE,
    P_ORDERS_ASSIGN,
    P_ORDERS_SHIP,
    P_ORDERS_VIEW,
    P_PAYMENTS_DECIDE,
    P_REPORTS,
    P_SALES_VIEW,
    P_SHOP_STATE,
)
from .public import same_database, shop_state

router = APIRouter(prefix="/admin")

# v2.8.2: the phone-sales state is shown on the dashboard and the «فروش گوشی» buttons
CAN_VIEW = Depends(require_any(P_DASHBOARD, P_SALES_VIEW))
CAN_EDIT_ORDERS = Depends(require_permission(P_ORDERS_EDIT))
CAN_ARCHIVE = Depends(require_permission(P_ARCHIVE))
CAN_ACTIVITY = Depends(require_permission(P_ACTIVITY))
CAN_DECIDE_CUSTOMERS = Depends(require_permission(P_CUSTOMERS_DECIDE))
CAN_DECIDE_PAYMENTS = Depends(require_permission(P_PAYMENTS_DECIDE))
CAN_EXPIRE = Depends(require_permission(P_ORDERS_EXPIRE))
CAN_SHIP = Depends(require_permission(P_ORDERS_SHIP))
CAN_SET_SHOP_STATE = Depends(require_permission(P_SHOP_STATE))
# v2.7.0: what a «کاربر فروش» needs, apart from the rest of the admin view
CAN_VIEW_ORDERS = Depends(require_permission(P_ORDERS_VIEW))
CAN_VIEW_CUSTOMERS = Depends(require_permission(P_CUSTOMERS_VIEW))
#: v2.17.0: the lists behind «گزارش‌ها» / «گزارش فعالیت» (each with its own tick)
CAN_LIST_ORDERS = Depends(require_any(P_ORDERS_VIEW, P_REPORTS))
CAN_LIST_CUSTOMERS = Depends(require_any(P_CUSTOMERS_VIEW, P_REPORTS, P_ACTIVITY))
# v2.8.2: every staff member gets the feed, filtered to what they may see
CAN_VIEW_EVENTS = Depends(require_signed_in)
CAN_WRITE_ACCOUNTING = Depends(require_permission(P_ACCOUNTING_WRITE))
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
        **settings.write_info(),
        "write_allowed_on_host": settings.write_allowed(),
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
    who: Identity = CAN_LIST_CUSTOMERS,
) -> list[UserOut]:
    """v2.8.2: a sales user sees new customers and those of their own work."""
    return [UserOut(**u) for u in ownership.filter_customers(db, who, db.list_users(status_filter))]


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
    who: Identity = CAN_VIEW_CUSTOMERS,
) -> UserOut:
    user = db.get_user_by_id(user_id)
    if not ownership.customer_visible(db, who, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return UserOut(**user)


def _create_person(writer: AccountingWriter, user: dict, payload: ApproveUserIn) -> int:
    """Recipe §5.1 for a customer without a person code. Returns the code."""
    first = (payload.first_name or "").strip() or str(user.get("first_name") or "")
    last = (payload.last_name or "").strip() or str(user.get("last_name") or "")
    if not last:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "last_name is required to create a person (or give person_code)",
        )
    try:
        # v2.17.0: all a new customer told the bot goes into the new person at once
        result = writer.create_person(first, last, user["phone"],
                                      address=str(user.get("address") or ""),
                                      national_code=str(user.get("national_code") or ""))
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
    if not ownership.customer_visible(db, who, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    created = False
    if payload.person_code is None:
        person_code = _create_person(writer, user, payload)
        created = True
        names = {"first_name": (payload.first_name or "").strip(),
                 "last_name": (payload.last_name or "").strip()}
        names = {key: value for key, value in names.items() if value}
        if names:
            db.update_user_details(user_id, **names)
        row = db.get_user_by_id(user_id)
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        if name:
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
    if not created:
        # v2.17.0: an existing person only gets its empty fields filled
        customer_details.sync(db, writer, user)
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
    if not ownership.customer_visible(db, who, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user = db.set_user_status(user_id, "rejected")
    reason = (payload.reason if payload and payload.reason else "")[:200]
    db.audit(who.actor, "user_reject", f"user id={user_id} reason={reason}")
    db.add_event("customer_rejected", user_id, who.actor)
    db.log_activity(staff_id=ownership.staff_id(who), actor=who.actor,
                    action=ownership.A_CUSTOMER_REJECT, target_type="customer",
                    target_id=user_id, customer_id=user_id)
    return UserOut(**user)


def _stages(reader: AccountingReader, settings: Settings, orders: list[dict]) -> dict[int, dict]:
    """v2.17.0: {our order id: stage fields} for the orders written to the connected
    database. The accounting database being down only leaves the stage empty."""
    written = {int(o["accounting_order_no"]): int(o["id"]) for o in orders
               if o.get("accounting_order_no") and o.get("status") == "written"
               and same_database(o.get("accounting_db"), settings)}
    if not written:
        return {}
    try:
        found = reader.order_stages(list(written))
    except Exception:  # noqa: BLE001 - the list works without the stage
        return {}
    out = {}
    for codlp, order_id in written.items():
        info = found.get(codlp)
        out[order_id] = {
            "sazeh_stage": tracking.order_stage(info, settings.accounting_status_code,
                                                settings.accounting_handover_code),
            "sazeh_status": (info or {}).get("status"),
        }
    return out


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
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_LIST_ORDERS,
) -> list[OrderOut]:
    """v2.8.0: a sales user sees free orders and their own (``mine``: own only);
    another user's order is never listed. Archived orders: /admin/archive/orders."""
    orders = db.query_orders(status=status_filter or None, viewer_id=ownership.viewer_id(who),
                             mine_only=mine)
    if mine and ownership.is_manager(who) and who.user_id is not None:
        orders = [o for o in orders if o.get("owner_id") == who.user_id]
    # v2.6.0: the linked person's name from the accounting DB (one query).
    names = _person_names(reader, orders)
    stages = _stages(reader, settings, orders)
    return [order_out(db, who, o, person_name=names.get(o.get("user_person_code")),
                      **stages.get(int(o["id"]), {}))
            for o in orders]


@router.get("/orders/payment-info-due", response_model=list[OrderOut])
def payment_info_due(
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW_ORDERS,
) -> list[OrderOut]:
    """v2.8.3: orders still waiting for «ارسال اطلاعات پرداخت» that THIS user must
    be reminded of: their own, or (nobody's yet) every user who may handle orders
    and the manager. An order of a colleague is never listed."""
    me = who.user_id if who.kind == "staff" else None
    out = []
    for order in db.query_orders(status="awaiting_payment", viewer_id=ownership.viewer_id(who)):
        if order.get("payment_info_at") or order.get("payment_info"):
            continue
        owner = order.get("owner_id")
        if owner is not None and owner != me:
            continue
        out.append(order_out(db, who, order))
    return out


def _visible_order(db: OwnDB, who: Identity, order_id: int) -> dict:
    return ownership.ensure_visible(who, db.get_order(order_id), "Order")


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order_admin(
    order_id: int,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_VIEW_ORDERS,
) -> OrderOut:
    order = _visible_order(db, who, order_id)
    names = _person_names(reader, [order])
    return order_out(db, who, order, person_name=names.get(order.get("user_person_code")),
                     **_stages(reader, settings, [order]).get(order_id, {}))


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
    who: Identity = CAN_ACTIVITY,
) -> list[dict]:
    """«گزارش فعالیت» («گزارش فعالیت — دیدن»): who did what, on which order /
    customer / request, and when. Dates are ISO (UTC) bounds: from <= ts < to.
    v2.8.3: a user who is not a manager gets only their OWN actions (no colleague
    rows, whatever ``staff_id`` asks)."""
    if not ownership.is_manager(who):
        if who.user_id is None:
            return []
        rows = db.list_activity(staff_id=who.user_id, own_only=True, customer_id=customer_id,
                                date_from=date_from, date_to=date_to, limit=limit)
    else:
        rows = db.list_activity(staff_id=staff_id, customer_id=customer_id,
                                date_from=date_from, date_to=date_to, limit=limit)
    return ownership.timeline(db, who, rows)


@router.post("/staff/{from_staff_id}/transfer-open")
def transfer_open_work(
    from_staff_id: int,
    payload: AssignIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = SIGNED_IN,
) -> dict:
    """v2.8.3 (manager): «انتقال همهٔ کارهای باز» of user X to user Y. Every moved
    order / request is logged on its history and in «گزارش فعالیت»."""
    if not ownership.is_manager(who):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers only")
    if db.get_staff(int(from_staff_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff account not found")
    if int(payload.staff_id) == int(from_staff_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Same colleague")
    target = db.get_staff(int(payload.staff_id))
    if target is None or not target["active"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown colleague")
    moved = {"orders": 0, "requests": 0}
    for target_type, rows in db.open_owned(int(from_staff_id)).items():
        for row in rows:
            ownership.assign(db, who, target_type, row, int(payload.staff_id),
                             detail_extra="bulk")
            moved["orders" if target_type == "order" else "requests"] += 1
    db.audit(who.actor, "staff_transfer_open",
             f"from={from_staff_id} to={payload.staff_id} orders={moved['orders']} "
             f"requests={moved['requests']}")
    return moved


@router.get("/archive/orders", response_model=list[OrderOut])
def archived_orders(
    q: Optional[str] = Query(None, max_length=100),
    accounting_db: Optional[str] = Query(None, max_length=128),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_ARCHIVE,
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
    payload: Optional[ApprovePaymentIn] = None,
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

        if settings.status_code_problem():
            # v2.17.0: without a valid status code nothing is ever written («بدون
            # وضعیت» in «سازه حساب»). The payment decision stands; staff are warned and
            # write the order later with «ثبت در حسابداری».
            _record_payer(db, order, payload)
            return order_out(db, who, _accept_without_writing(db, who, order_id))
        try:
            written = _write_to_accounting(db, writer, settings, who, order, order_id)
        except AccountingConfigError as exc:
            db.audit(who.actor, "approve_payment_refused", f"order id={order_id} config: {exc}")
            _record_payer(db, order, payload)
            return order_out(db, who, _accept_without_writing(db, who, order_id))
        if written is None:
            db.audit(who.actor, "approve_payment_dry_run",
                     f"order id={order_id} (rolled back, nothing written)")
            return order_out(db, who, db.get_order(order_id))
        db.set_payment_decided(order_id, "approved")
        db.add_event("payment_approved", order_id, who.actor)
        ownership.log(db, who, ownership.A_RECEIPT_APPROVE, "order", written)
        _record_payer(db, order, payload)
        return order_out(db, who, db.get_order(order_id))


def _record_payer(db: OwnDB, order: dict, payload: Optional[ApprovePaymentIn]) -> None:
    """v2.17.0: the first receipt's name check: asked once per customer. A different
    payer stays in our own data; the customer's name and «سازه حساب» are never touched."""
    if payload is None or not payload.payer_checked:
        return
    fields: dict = {"payer_asked": 1}
    name = " ".join(payload.payer_name.split())
    if payload.record_payer and name:
        fields["payer_name"] = name
        db.set_order_payer(int(order["id"]), name)
    db.update_user_details(int(order["user_id"]), **fields)


def _accept_without_writing(db: OwnDB, who: Identity, order_id: int) -> dict:
    """v2.17.0: the receipt is accepted; the order waits for «ثبت در حسابداری»."""
    order = db.set_order_status(order_id, "approved")
    order = db.set_accounting_pending(order_id, True)
    db.set_payment_decided(order_id, "approved")
    db.audit(who.actor, "approve_payment_not_written",
             f"order id={order_id} (no valid order status code)")
    db.add_event("payment_approved", order_id, who.actor)
    ownership.log(db, who, ownership.A_RECEIPT_APPROVE, "order", order)
    return order


def _write_to_accounting(db: OwnDB, writer: AccountingWriter, settings: Settings, who: Identity,
                         order: dict, order_id: int) -> dict | None:
    """Write one order to «سازه حساب». The fresh order once a row really exists there
    (committed now, or an identical header was already there: an idempotent replay);
    None for a dry run, which is rolled back and must NOT be reported as written,
    otherwise the order could never be retried."""
    # v2.6.2: a phone line carries its color and part in the line description
    write_items = [(it["kala_code"], it["qty"], it["unit_price"])
                   + ((it["variant"],) if it.get("variant") else ())
                   for it in db.get_order_items(order_id)]
    try:
        result = writer.write_order(order_id, order["user_person_code"], write_items)
    except AccountingLockTimeout:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accounting is busy; try again") from None
    except DuplicateOrderNumber as exc:
        # Rolled back: nothing was written. Tell the admin; retry is safe.
        db.audit(who.actor, "approve_payment_duplicate",
                 f"order id={order_id} codlp={exc.codlp} rows={exc.count} (rolled back)")
        db.add_event(EVENT_DUPLICATE_ORDER_NO, order_id, who.actor)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Duplicate accounting order number; nothing was written") from None
    if not (result.committed or result.idempotent):
        return None
    written = db.set_order_status(order_id, "written", result.accounting_order_no,
                                  accounting_db=result.database or settings.database_name())
    written = db.set_accounting_pending(order_id, False)
    db.audit(
        who.actor,
        "approve_payment",
        f"order id={order_id} accounting_order_no={result.accounting_order_no} "
        f"db={result.database or settings.database_name()} "
        f"committed={result.committed} idempotent={result.idempotent}",
    )
    if result.duplicate_after_commit:
        # Another program wrote the same Codlp next to ours. Never delete
        # anything in the accounting DB: only alert the admin.
        db.audit("system:writer", "accounting_duplicate_order",
                 f"order id={order_id} codlp={result.accounting_order_no} "
                 f"rows={result.codlp_rows_after_commit}")
        db.add_event(EVENT_DUPLICATE_ORDER_NO, order_id, "system:writer")
    return written


@router.post("/orders/{order_id}/write-accounting", response_model=OrderOut)
def write_accounting_later(
    order_id: int,
    writer: AccountingWriter = Depends(deps.get_writer),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_WRITE_ACCOUNTING,
) -> OrderOut:
    """v2.17.0 «ثبت در حسابداری»: an order whose receipt was accepted while no valid
    status code was set. Also after it was sent: «سازه حساب» still needs it."""
    with db.reservation_guard():
        order = _visible_order(db, who, order_id)
        if not order.get("accounting_pending") or order["status"] != "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, "Order does not wait for accounting")
        if settings.status_code_problem():
            raise HTTPException(status.HTTP_409_CONFLICT, "Order status code is not configured")
        if order["user_status"] != "approved" or order["user_person_code"] is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Customer is not approved yet")
        try:
            written = _write_to_accounting(db, writer, settings, who, order, order_id)
        except AccountingConfigError:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Order status code is not configured") from None
        if written is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Accounting writes are disabled")
        ownership.log(db, who, ownership.A_WRITE_LATER, "order", written)
        return order_out(db, who, written)


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
    who: Identity = CAN_VIEW_EVENTS,
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
    # v2.8.2: a sales user hears only about what they may see
    items = [e for e in items if ownership.event_visible(db, who, e)]
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


#: v2.8.2: the customer is told where to pay; the event lets the bot send it.
EVENT_PAYMENT_INFO = "order_payment_info"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def clean_payment_info(payload: PaymentInfoIn) -> dict:
    """Only the filled fields, normalised; a card is 16 digits, a Sheba IR + 24."""
    def text(value: str) -> str:
        return " ".join(str(value or "").split())

    info: dict = {}
    card = "".join(ch for ch in text(payload.card_number).translate(_DIGITS) if ch.isdigit())
    if text(payload.card_number):
        if len(card) != 16:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "card_number must be a 16-digit card number")
        info["card_number"] = "-".join(card[i:i + 4] for i in range(0, 16, 4))
    account = text(payload.account_number).translate(_DIGITS)
    if account:
        if not all(ch.isdigit() or ch in "-./ " for ch in account):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "account_number must be digits")
        info["account_number"] = account
    sheba = text(payload.sheba).translate(_DIGITS).replace(" ", "").replace("-", "").upper()
    if sheba:
        if not sheba.startswith("IR"):
            sheba = "IR" + sheba
        if len(sheba) != 26 or not sheba[2:].isdigit():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "sheba must be a sheba number (IR and 24 digits)")
        info["sheba"] = sheba
    for key in ("holder", "bank", "note"):
        value = text(getattr(payload, key))
        if value:
            info[key] = value
    if not any(k in info for k in ("card_number", "account_number", "sheba")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Enter a card, account or sheba number")
    return info


@router.post("/orders/{order_id}/payment-info", response_model=OrderOut)
def send_payment_info(
    order_id: int,
    payload: PaymentInfoIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_EDIT_ORDERS,
) -> OrderOut:
    """v2.8.2: «ارسال اطلاعات پرداخت»: what staff typed for this order goes to the
    customer through the bot (only the filled fields). The receipt deadline starts
    now. Sending again replaces the details (and restarts the deadline)."""
    info = clean_payment_info(payload)
    order = _visible_order(db, who, order_id)
    ownership.ensure_order_editable(order)
    if order["status"] != "awaiting_payment":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Order in status {order['status']}; payment details not needed")
    ownership.take(db, who, "order", order)
    reserve_until = (now_utc() + timedelta(minutes=settings.receipt_deadline_minutes)
                     ).isoformat(timespec="seconds")
    order = db.set_payment_info(order_id, info, reserve_until)
    db.audit(who.actor, "order_payment_info", f"order id={order_id} fields={sorted(info)}")
    db.add_event(EVENT_PAYMENT_INFO, order_id, who.actor)
    ownership.log(db, who, ownership.A_PAYMENT_INFO, "order", order)
    return order_out(db, who, order)


#: v2.7.0: orders staff may cancel (never one already paid and confirmed).
STAFF_CANCELLABLE = ("awaiting_payment", "receipt_uploaded")


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    payload: OrderCancelIn | None = None,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_CANCEL,
) -> OrderOut:
    """Staff cancel an order that is not confirmed yet. Local only: «سازه حساب»
    is never touched; an order already written there raises a ShopAdmin warning.
    v2.9.3: the bot tells the customer (``order_cancelled_by_staff``, with the
    optional short reason) and its old buttons for the order stop working."""
    note = " ".join(str((payload or OrderCancelIn()).reason or "").split())[:200]
    with db.reservation_guard():
        order = _visible_order(db, who, order_id)
        if order["status"] not in STAFF_CANCELLABLE:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Order in status {order['status']}; cannot be cancelled")
        ownership.take(db, who, "order", order)
        db.cancel_order_any(order_id, "staff", STAFF_CANCELLABLE, note)
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


def staff_shop_state(db: OwnDB, settings: Settings, who: Identity) -> ShopStateOut:
    """v2.8.3: who opened / closed phone sales is a name only for the manager; a
    sales user reads «شما» for their own change, nothing for a colleague's."""
    state = shop_state(db, settings)
    if ownership.is_manager(who) or not state.override_by:
        return state
    mine = state.override_by == who.actor
    return state.model_copy(update={"override_by": "شما" if mine else ""})


@router.get("/shop/state", response_model=ShopStateOut)
def get_shop_state(
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_VIEW,
) -> ShopStateOut:
    return staff_shop_state(db, settings, who)


@router.put("/shop/state", response_model=ShopStateOut)
def set_shop_state(
    payload: ShopStateIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_SET_SHOP_STATE,
) -> ShopStateOut:
    """Old switch (kept for older clients): closed -> «بستن فروش», else «باز کردن فروش»."""
    sales.set_override(db, settings, "close" if payload.closed else "open", who.actor)
    return staff_shop_state(db, settings, who)


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
    return staff_shop_state(db, settings, who)
