"""Staff endpoints of v2.6.0: product groups (show in bot / phone group) and the
customers' unavailable item requests.

v2.6.1: the group tree with inherited flags and «قیمت با استعلام»; item requests
of kind ``inquiry``, a staff note, and staff replies to the customer (stored
here, delivered by the bot the customer used; nothing reaches «سازه حساب»)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import customer_details, deps, faq, ownership, purchase
from .. import groups as group_config
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..schemas import (
    AssignIn,
    OrderOut,
    StockConfirmIn,
    ItemRequestMessageDelivery,
    ItemRequestMessageIn,
    ItemRequestMessageOut,
    ItemRequestMessageResultIn,
    ItemRequestNoteIn,
    ItemRequestOut,
    ItemRequestStatusIn,
    OfferAnswerIn,
    ProductGroupOut,
    ProductGroupsIn,
)
from ..security import Identity, require_any, require_permission
from ..staff import (P_ARCHIVE, P_GROUPS_EDIT, P_GROUPS_VIEW, P_REQUESTS_EDIT,
                     P_REQUESTS_VIEW)

router = APIRouter(prefix="/admin")
logger = logging.getLogger("shopapi.shop_catalog")

# v2.8.3: «گروه‌های کالا — دیدن» only (the dashboard reads its warnings from /shop/state)
CAN_VIEW = Depends(require_any(P_GROUPS_VIEW))
#: «درخواست کالا»: «دیدن» for the lists, «تغییر» for every action
#: v2.17.0: «رسیدگی شد» before anything was sent to the customer (ShopAdmin asks first).
MESSAGE_FIRST_DETAIL = "Send the customer a message first"
CAN_SEE_REQUESTS = Depends(require_permission(P_REQUESTS_VIEW))
CAN_REQUESTS = Depends(require_permission(P_REQUESTS_EDIT))
CAN_ARCHIVE = Depends(require_permission(P_ARCHIVE))
CAN_MANAGE_CATALOG = Depends(require_permission(P_GROUPS_EDIT))


def _groups_out(db: OwnDB, reader: AccountingReader) -> list[ProductGroupOut]:
    stored = db.list_group_settings()
    rows = reader.list_groups()
    cfg = group_config.load(db)
    cfg.parents = group_config.parent_map(rows)
    out: list[ProductGroupOut] = []
    seen: set[int] = set()
    for g in rows:
        code = int(g["code"])
        seen.add(code)
        row = stored.get(code) or {}
        out.append(ProductGroupOut(
            code=code, name=str(g.get("name") or "").strip(),
            show_in_bot=bool(row.get("show_in_bot")),
            is_phone=bool(row.get("is_phone")),
            price_on_inquiry=bool(row.get("price_on_inquiry")),
            parent=cfg.parents.get(code),
            effective_show_in_bot=cfg.visible(code),
            effective_is_phone=cfg.is_phone(code),
            effective_price_on_inquiry=cfg.on_inquiry(code),
        ))
    for code, row in stored.items():
        if code not in seen and (row["show_in_bot"] or row["is_phone"]
                                 or row.get("price_on_inquiry")):
            out.append(ProductGroupOut(
                code=code, name="", show_in_bot=bool(row["show_in_bot"]),
                is_phone=bool(row["is_phone"]),
                price_on_inquiry=bool(row.get("price_on_inquiry")), missing=True))
    return out


@router.get("/product-groups", response_model=list[ProductGroupOut])
def list_product_groups(
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    _: Identity = CAN_VIEW,
) -> list[ProductGroupOut]:
    """Accounting product groups (with their parent) and the ShopAdmin checkboxes."""
    return _groups_out(db, reader)


@router.put("/product-groups", response_model=list[ProductGroupOut])
def save_product_groups(
    payload: ProductGroupsIn,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    who: Identity = CAN_MANAGE_CATALOG,
) -> list[ProductGroupOut]:
    entries = [(g.code, g.show_in_bot, g.is_phone, g.price_on_inquiry) for g in payload.groups]
    if len({e[0] for e in entries}) != len(entries):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate group")
    db.set_group_settings(entries, who.actor)
    shown = sum(1 for e in entries if e[1])
    phones = sum(1 for e in entries if e[2])
    inquiry = sum(1 for e in entries if e[3])
    db.audit(who.actor, "product_groups_save",
             f"groups={len(entries)} shown={shown} phone={phones} inquiry={inquiry}")
    db.add_event("product_groups_changed", None, who.actor)
    return _groups_out(db, reader)


KIND_PATTERN = "^(unavailable|inquiry|purchase)$"


def request_out(db: OwnDB, who: Identity, row: dict) -> dict:
    """v2.8.0: ownership fields; staff names only for the manager."""
    return {**ownership.scrub_request(who, row),
            **ownership.owner_fields(db, who, row, "request")}


def with_person_names(reader: AccountingReader, rows: list[dict]) -> list[dict]:
    """v2.18.0: the linked person's name in «سازه حساب» (a list without it still works)."""
    try:
        names = reader.person_names(r.get("person_code") for r in rows)
    except Exception:  # noqa: BLE001 - permission denied, accounting down
        return rows
    return [{**r, "person_name": names.get(r.get("person_code"))} for r in rows]


@router.get("/item-requests", response_model=list[ItemRequestOut])
def list_item_requests(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(new|seen|done)$"),
    kind: Optional[str] = Query(None, pattern=KIND_PATTERN),
    mine: bool = Query(False),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    who: Identity = CAN_SEE_REQUESTS,
) -> list[dict]:
    """v2.8.0: a sales user sees free requests and their own (``mine``: own only)."""
    rows = db.query_item_requests(status=status_filter, kind=kind,
                                  viewer_id=ownership.viewer_id(who), mine_only=mine)
    if mine and ownership.is_manager(who) and who.user_id is not None:
        rows = [r for r in rows if r.get("owner_id") == who.user_id]
    return with_person_names(reader, [request_out(db, who, r) for r in rows])


@router.get("/archive/item-requests", response_model=list[ItemRequestOut])
def archived_item_requests(
    q: Optional[str] = Query(None, max_length=100),
    accounting_db: Optional[str] = Query(None, max_length=128),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_ARCHIVE,
) -> list[dict]:
    """«بایگانی» of requests (read-only): own + current fiscal year for a sales user."""
    if ownership.is_manager(who):
        rows = db.query_item_requests(archived=True, accounting_db=accounting_db or None, q=q)
    else:
        rows = db.query_item_requests(archived=True, viewer_id=who.user_id,
                                      accounting_db=settings.database_name(), q=q)
    return [request_out(db, who, r) for r in rows]


def _request_or_404(db: OwnDB, request_id: int, who: Identity | None = None) -> dict:
    row = db.get_item_request(request_id)
    if row is None or (who is not None and not ownership.visible(who, row)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


def _editable(db: OwnDB, who: Identity, request_id: int) -> dict:
    """A visible, unfinished request, taken by this user (first action = owner)."""
    row = _request_or_404(db, request_id, who)
    ownership.ensure_request_editable(row)
    ownership.take(db, who, "request", row)
    return row


@router.get("/item-requests/{request_id}", response_model=ItemRequestOut)
def get_item_request(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_SEE_REQUESTS,
) -> dict:
    return request_out(db, who, _request_or_404(db, request_id, who))


@router.get("/item-requests/{request_id}/timeline")
def item_request_timeline(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_SEE_REQUESTS,
) -> list[dict]:
    row = _request_or_404(db, request_id, who)
    targets = [("request", request_id)]
    if row.get("order_id"):
        targets.append(("order", int(row["order_id"])))
    return ownership.timeline(db, who, db.list_activity(targets=targets, limit=500))


@router.post("/item-requests/{request_id}/assign", response_model=ItemRequestOut)
def assign_item_request(
    request_id: int,
    payload: AssignIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    row = _request_or_404(db, request_id, who)
    ownership.ensure_request_editable(row)
    ownership.assign(db, who, "request", row, payload.staff_id)
    return request_out(db, who, db.get_item_request(request_id))


@router.post("/item-requests/{request_id}/status", response_model=ItemRequestOut)
def set_item_request_status(
    request_id: int,
    payload: ItemRequestStatusIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    current = _editable(db, who, request_id)
    if current.get("kind") == purchase.KIND and payload.status == "done":
        # a purchase request ends with the customer's answer to a price or «ناموجود»
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Answer the purchase request: confirm stock or unavailable")
    if payload.status == "done" and not db.request_has_message(request_id):
        # v2.17.0: no request is closed silently: the customer always hears from us
        raise HTTPException(status.HTTP_409_CONFLICT, MESSAGE_FIRST_DETAIL)
    row = db.set_item_request_status(request_id, payload.status, who.actor)
    db.audit(who.actor, "item_request_status", f"request id={request_id} status={payload.status}")
    ownership.log(db, who, ownership.A_REQUEST_STATUS, "request", current,
                  detail=payload.status)
    return request_out(db, who, row)


@router.put("/item-requests/{request_id}/note", response_model=ItemRequestOut)
def set_item_request_note(
    request_id: int,
    payload: ItemRequestNoteIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """The staff's own note (never shown to the customer)."""
    current = _editable(db, who, request_id)
    row = db.set_item_request_note(request_id, payload.note.strip(), who.actor)
    db.audit(who.actor, "item_request_note", f"request id={request_id}")
    ownership.log(db, who, ownership.A_NOTE, "request", current)
    return request_out(db, who, row)


@router.post("/item-requests/{request_id}/offer", response_model=ItemRequestOut)
@router.post("/item-requests/{request_id}/confirm-stock", response_model=ItemRequestOut)
def offer_purchase_price(
    request_id: int,
    payload: StockConfirmIn | None = None,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """v2.9.2 «تأیید موجودی» (list price) or a price typed by staff: the customer
    gets it in the bot with «تأیید و خرید»; the order is created only then."""
    if who.kind != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can offer a price")
    payload = payload or StockConfirmIn()
    row = _request_or_404(db, request_id, who)
    return request_out(db, who, purchase.offer_price(db, reader, settings, who, row,
                                                     payload.kala_code, payload.price_rial,
                                                     payload.note))


@router.post("/item-requests/{request_id}/customer-answer")
def purchase_offer_answer(
    request_id: int,
    payload: OfferAnswerIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """The bot (service key only) passes on the customer's «تأیید و خرید» /
    «نمی‌خواهم». Returns the request and, when accepted, the new order."""
    if who.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    row = _request_or_404(db, request_id)
    if payload.price_rial and int(row.get("offer_price_rial") or 0) != payload.price_rial:
        raise HTTPException(status.HTTP_409_CONFLICT, purchase.OFFER_GONE_DETAIL)
    request, order = purchase.answer_offer(db, settings, who, row, payload.accept)
    return {"request": request_out(db, who, request),
            "order": OrderOut(**customer_details.public_order(
                {**order, **ownership.owner_fields(db, who, order)})).model_dump()
            if order else None}


@router.post("/item-requests/{request_id}/unavailable", response_model=ItemRequestOut)
def purchase_unavailable(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """«ناموجود»: the request is closed and the customer gets a polite message."""
    row = _request_or_404(db, request_id, who)
    return request_out(db, who, purchase.mark_unavailable(db, who, row))


@router.get("/item-requests/{request_id}/messages", response_model=list[ItemRequestMessageOut])
def list_item_request_messages(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_SEE_REQUESTS,
) -> list[dict]:
    _request_or_404(db, request_id, who)
    rows = db.list_item_request_messages(request_id)
    if not ownership.is_manager(who):
        rows = [{**r, "created_by": ""} for r in rows]
    return rows


@router.post("/item-requests/{request_id}/messages", response_model=ItemRequestMessageOut,
             status_code=status.HTTP_201_CREATED)
def send_item_request_message(
    request_id: int,
    payload: ItemRequestMessageIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """A reply to the customer. Stored as ``pending``; the bot of the customer's
    platform delivers it (events feed) and reports ``sent`` / ``failed``."""
    if who.kind != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can message customers")
    row = _editable(db, who, request_id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is empty")
    if not row.get("platform"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer has no messenger")
    message = db.add_item_request_message(request_id, text, who.actor)
    db.audit(who.actor, "item_request_message", f"request id={request_id} message id={message['id']}")
    db.add_event("item_request_message", message["id"], who.actor)
    ownership.log(db, who, ownership.A_REPLY, "request", row)
    # v2.18.1: what a colleague answered may teach the bot, once a manager approves it
    try:
        faq.suggest(db, str(row.get("text") or ""), text, request_id, who.actor)
    except Exception as exc:  # noqa: BLE001 - never stops the reply itself
        logger.warning("faq suggestion not saved: %s", type(exc).__name__)
    return message


@router.get("/item-request-messages/{message_id}", response_model=ItemRequestMessageDelivery)
def get_item_request_message(
    message_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_SEE_REQUESTS,
) -> dict:
    """For the bot (service key): the reply and where to deliver it."""
    if who.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    row = db.get_item_request_message(message_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return row


@router.post("/item-request-messages/{message_id}/result",
             response_model=ItemRequestMessageOut)
def item_request_message_result(
    message_id: int,
    payload: ItemRequestMessageResultIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """The bot reports delivery; only the service key may (staff cannot fake it)."""
    if who.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    if db.get_item_request_message(message_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    row = db.set_item_request_message_result(message_id, payload.ok, payload.error.strip())
    db.audit(who.actor, "item_request_message_result",
             f"message id={message_id} ok={payload.ok}")
    db.add_event("item_request_message_result", message_id, who.actor)
    return row
