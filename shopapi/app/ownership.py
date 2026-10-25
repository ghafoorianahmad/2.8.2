"""Ownership, handover and the activity log (v2.8.0).

* A new order / item request is visible to every sales user. The first one who
  acts on it becomes its owner and it disappears for the others.
* A sales user («کاربر فروش») never sees another user's work or name - enforced
  here, on the server; ShopAdmin only hides what this already refuses.
* The manager («مدیر», and the server's own service key used by the bots) sees
  everything, with names.
* The manager, a user with the «ارجاع سفارش» tick, or the current owner may hand
  an order / request over to another user at any stage. Every step is logged
  (``activity_log``); finished orders and archived rows are read-only.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from .db_own import CLOSED_ORDER_STATUSES, OwnDB
from .security import Identity
from .staff import P_ORDERS_ASSIGN, ROLE_ADMIN, ROLE_SUPER_ADMIN

#: Activity actions (ShopAdmin turns them into Persian sentences).
A_CLAIM = "claim"
A_ASSIGN = "assign"
A_HANDOVER = "handover"
A_CUSTOMER_APPROVE = "customer_approve"
A_CUSTOMER_REJECT = "customer_reject"
A_RECEIPT_APPROVE = "receipt_approve"
A_RECEIPT_REJECT = "receipt_reject"
A_SHIP = "ship"
A_CANCEL = "cancel"
A_REPLY = "reply"
A_NOTE = "note"
A_REQUEST_STATUS = "request_status"
A_STOCK_CONFIRM = "stock_confirm"
A_STOCK_UNAVAILABLE = "stock_unavailable"
A_ARCHIVE = "archive"
A_PAYMENT_INFO = "payment_info"       # v2.8.2: «ارسال اطلاعات پرداخت»
A_PRICE_OFFER = "price_offer"         # v2.9.2: price sent to the customer
A_OFFER_ACCEPT = "offer_accept"       # the customer: «تأیید و خرید» (order created)
A_OFFER_DECLINE = "offer_decline"     # the customer: «نمی‌خواهم»

FINISHED_DETAIL = "Order is finished and read-only"
REQUEST_FINISHED_DETAIL = "Request is finished and read-only"
NOT_YOURS_DETAIL = "Another colleague is working on this"


def is_manager(who: Identity) -> bool:
    """«مدیر» (and the in-process service key): sees everyone's work and names."""
    return who.kind == "service" or who.role in (ROLE_SUPER_ADMIN, ROLE_ADMIN)


def staff_id(who: Identity) -> int | None:
    return who.user_id if who.kind == "staff" else None


def viewer_id(who: Identity) -> int | None:
    """The staff id the lists are limited to (None = everything)."""
    return None if is_manager(who) else who.user_id


def can_assign(who: Identity, row: dict) -> bool:
    if is_manager(who) or who.can(P_ORDERS_ASSIGN):
        return True
    return who.user_id is not None and row.get("owner_id") == who.user_id


# ---- visibility ----------------------------------------------------------------------------------
#: v2.8.3: an order nobody has taken is shown to every sales user only while it
#: is open (new, or its receipt waits for a decision). Accepted / written orders
#: without an owner (e.g. approved in the Bale admin chat, or older ones) are the
#: manager's only.
FREE_ORDER_STATUSES = ("awaiting_payment", "receipt_uploaded")


def visible(who: Identity, row: dict) -> bool:
    """A sales user sees their own rows and new rows nobody has taken yet; the
    manager everything."""
    if is_manager(who):
        return True
    owner = row.get("owner_id")
    if owner is not None:
        return owner == who.user_id
    if "kind" in row and "status" in row and row.get("status") in ("new", "seen", "done"):
        return row.get("status") != "done" and not row.get("archived_at")      # request
    if row.get("archived_at"):
        return False
    return row.get("status") in FREE_ORDER_STATUSES and not row.get("shipped_at")


def customer_visible(db: OwnDB, who: Identity, user: dict | None) -> bool:
    """v2.8.2: a sales user sees new (pending) customers and the customers of the
    orders / requests they may see."""
    if user is None:
        return False
    if is_manager(who):
        return True
    if user.get("status") == "pending":
        return True
    return who.user_id is not None and int(user["id"]) in db.customer_ids_for_staff(who.user_id)


def filter_customers(db: OwnDB, who: Identity, users: list[dict]) -> list[dict]:
    if is_manager(who):
        return users
    mine = db.customer_ids_for_staff(who.user_id) if who.user_id is not None else set()
    return [u for u in users if u.get("status") == "pending" or int(u["id"]) in mine]


#: Event kinds about one order / request / customer / message (``ref_id``).
_ORDER_EVENTS_EXTRA = {"payment_approved", "payment_rejected", "receipt_uploaded",
                       "order_assigned"}
_REQUEST_EVENTS = {"item_request", "request_assigned"}
_MESSAGE_EVENTS = {"item_request_message", "item_request_message_result"}
#: Kinds only for those who may see that part of the app.
_SECTION_EVENTS = {"password_request": "passwords.view", "pricelist_imported": "pricelist.view",
                   "pricelist_held": "pricelist.view", "pricelist_failed": "pricelist.view",
                   "proxies_all_dead": "pricelist.view", "model_review": "models.view",
                   "price_inquiry": "pricelist.view", "security_alert": "server.view",
                   "accounting_duplicate_order": "server.view", "archive_done": "archive.view",
                   "product_groups_changed": "groups.view",
                   # v2.9.0: Telegram reader problems are for whoever runs the server
                   "telegram_login_required": "server.view",
                   "telegram_unreachable": "server.view",
                   "telegram_pricelist_error": "server.view",
                   # v2.9.1: price-channel posts, price guard, joined channels
                   "pricelist_corrected": "pricelist.view", "price_held": "pricelist.view",
                   "price_correction_unmatched": "pricelist.view",
                   "telegram_channel_new": "server.view"}


def event_visible(db: OwnDB, who: Identity, event: dict) -> bool:
    """v2.8.2: the notification feed of a sales user only tells about what they
    may see (their own work, new work, new customers)."""
    if is_manager(who):
        return True
    kind = str(event.get("kind") or "")
    ref = event.get("ref_id")
    if kind in _SECTION_EVENTS:
        return who.can(_SECTION_EVENTS[kind])
    if ref is None:
        return True
    ref = int(ref)
    if kind in _MESSAGE_EVENTS:
        message = db.get_item_request_message(ref)
        row = db.get_item_request(int(message["request_id"])) if message else None
        return row is not None and visible(who, row)
    if kind in _REQUEST_EVENTS:
        row = db.get_item_request(ref)
        return row is not None and visible(who, row)
    if kind.startswith("customer_"):
        return customer_visible(db, who, db.get_user_by_id(ref))
    if kind in _ORDER_EVENTS_EXTRA or "order" in kind:
        row = db.get_order(ref)
        return row is not None and visible(who, row)
    return True


def ensure_visible(who: Identity, row: dict | None, what: str = "Order") -> dict:
    """A row of another sales user does not exist for this one (404, not 403:
    not even its existence leaks)."""
    if row is None or not visible(who, row):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return row


def order_finished(order: dict) -> bool:
    return bool(order.get("archived_at")) or order.get("status") in CLOSED_ORDER_STATUSES \
        or bool(order.get("shipped_at"))


def request_finished(row: dict) -> bool:
    return bool(row.get("archived_at")) or row.get("status") == "done"


def ensure_order_editable(order: dict) -> None:
    if order_finished(order):
        raise HTTPException(status.HTTP_409_CONFLICT, FINISHED_DETAIL)


def ensure_request_editable(row: dict) -> None:
    if request_finished(row):
        raise HTTPException(status.HTTP_409_CONFLICT, REQUEST_FINISHED_DETAIL)


def take(db: OwnDB, who: Identity, target_type: str, row: dict) -> None:
    """Before an action: a free row becomes this user's (logged once); a row of
    another user is refused for a sales user (403). The manager may act on any
    row without taking it over."""
    sid = staff_id(who)
    owner = row.get("owner_id")
    if sid is None:
        return
    if owner is None:
        if db.claim(target_type, int(row["id"]), sid):
            row["owner_id"] = sid
            db.log_activity(staff_id=sid, actor=who.actor, action=A_CLAIM,
                            target_type=target_type, target_id=int(row["id"]),
                            customer_id=row.get("user_id"))
            return
        fresh = (db.get_order(int(row["id"])) if target_type == "order"
                 else db.get_item_request(int(row["id"])))
        owner = (fresh or {}).get("owner_id")
    if owner != sid and not is_manager(who):
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_YOURS_DETAIL)


def log(db: OwnDB, who: Identity, action: str, target_type: str, row: dict,
        detail: str = "", to_staff_id: int | None = None) -> None:
    db.log_activity(staff_id=staff_id(who), actor=who.actor, action=action,
                    target_type=target_type, target_id=int(row["id"]),
                    customer_id=row.get("user_id"), to_staff_id=to_staff_id, detail=detail)


# ---- output (names only for the manager) ------------------------------------------------------
def owner_fields(db: OwnDB, who: Identity, order: dict, target_type: str = "order") -> dict:
    """Ownership fields of an order / request for this viewer."""
    owner = order.get("owner_id")
    me = who.user_id if who.kind == "staff" else None
    out = {"owned_by_me": owner is not None and owner == me, "owned": owner is not None,
           "finished": order_finished(order) if target_type == "order"
           else request_finished(order),
           "archived": bool(order.get("archived_at"))}
    if is_manager(who):
        out["owner_id"] = owner
        out["owner_name"] = db.staff_names([owner]).get(owner) if owner else None
    else:
        out["owner_id"] = owner if owner == me else None
        out["owner_name"] = None
    return out


def scrub_request(who: Identity, row: dict) -> dict:
    """Staff names in an item request (handled_by / note_by) only for the manager."""
    if is_manager(who):
        return row
    return {**row, "handled_by": "", "note_by": ""}


def _from_staff(entry: dict) -> int | None:
    """The previous owner of an «ارجاع» (``detail`` = ``from=<id>[ bulk]``)."""
    if entry.get("action") not in (A_ASSIGN, A_HANDOVER):
        return None
    head = str(entry.get("detail") or "").split(" ", 1)[0]
    value = head[5:] if head.startswith("from=") else ""
    return int(value) if value.isdigit() else None


def timeline(db: OwnDB, who: Identity, entries: list[dict]) -> list[dict]:
    """Activity entries for the order / request dialog. A sales user sees what
    was done but never who did it (only «شما» for their own steps)."""
    manager = is_manager(who)
    names = db.staff_names([e.get("staff_id") for e in entries]
                           + [e.get("to_staff_id") for e in entries]
                           + [_from_staff(e) for e in entries]) if manager else {}
    out = []
    for e in entries:
        item = {"id": e["id"], "ts": e["ts"], "action": e["action"],
                "target_type": e["target_type"], "target_id": e["target_id"],
                "detail": e.get("detail") or "",
                "is_me": who.user_id is not None and e.get("staff_id") == who.user_id,
                "to_me": who.user_id is not None and e.get("to_staff_id") == who.user_id,
                "system": e.get("staff_id") is None}
        if manager:
            item["actor_name"] = names.get(e.get("staff_id")) or e.get("actor") or ""
            item["to_name"] = names.get(e.get("to_staff_id")) if e.get("to_staff_id") else None
            # v2.8.3: whose work the manager moved («از … به …»)
            item["from_name"] = names.get(_from_staff(e)) if _from_staff(e) else None
            item["staff_id"] = e.get("staff_id")
            item["customer_id"] = e.get("customer_id")
            item["customer_name"] = e.get("customer_name")
        else:
            item["actor_name"] = None
            item["to_name"] = None
        out.append(item)
    return out


def assign(db: OwnDB, who: Identity, target_type: str, row: dict, to_staff_id: int,
           detail_extra: str = "") -> None:
    """Hand a row over (manager / «ارجاع سفارش» / its owner). The new owner must
    be an active staff member."""
    if not visible(who, row):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_assign(who, row):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted to reassign")
    target = db.get_staff(int(to_staff_id))
    if target is None or not target["active"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown colleague")
    previous = row.get("owner_id")
    db.set_owner(target_type, int(row["id"]), int(to_staff_id))
    own_handover = previous is not None and previous == who.user_id and not is_manager(who)
    detail = f"from={previous or '-'}" + (f" {detail_extra}" if detail_extra else "")
    log(db, who, A_HANDOVER if own_handover else A_ASSIGN, target_type, row,
        detail=detail, to_staff_id=int(to_staff_id))
    db.audit(who.actor, f"{target_type}_assign",
             f"{target_type} id={row['id']} from={previous or '-'} to={to_staff_id}")
    db.add_event(f"{target_type}_assigned", int(row["id"]), who.actor)
