"""Staff endpoints of v2.6.0: product groups (show in bot / phone group) and the
customers' unavailable item requests.

v2.6.1: the group tree with inherited flags and «قیمت با استعلام»; item requests
of kind ``inquiry``, a staff note, and staff replies to the customer (stored
here, delivered by the bot the customer used; nothing reaches «سازه حساب»)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from .. import groups as group_config
from ..accounting_reader import AccountingReader
from ..db_own import OwnDB
from ..schemas import (
    ItemRequestMessageDelivery,
    ItemRequestMessageIn,
    ItemRequestMessageOut,
    ItemRequestMessageResultIn,
    ItemRequestNoteIn,
    ItemRequestOut,
    ItemRequestStatusIn,
    ProductGroupOut,
    ProductGroupsIn,
)
from ..security import Identity, require_permission
from ..staff import P_CATALOG, P_REQUESTS, P_VIEW

router = APIRouter(prefix="/admin")

CAN_VIEW = Depends(require_permission(P_VIEW))
#: v2.7.0: item requests are a sales-user task (view, reply, mark handled)
CAN_REQUESTS = Depends(require_permission(P_REQUESTS))
CAN_MANAGE_CATALOG = Depends(require_permission(P_CATALOG))


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


@router.get("/item-requests", response_model=list[ItemRequestOut])
def list_item_requests(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(new|seen|done)$"),
    kind: Optional[str] = Query(None, pattern="^(unavailable|inquiry)$"),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_REQUESTS,
) -> list[dict]:
    return db.list_item_requests(status_filter, kind=kind)


def _request_or_404(db: OwnDB, request_id: int) -> dict:
    row = db.get_item_request(request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


@router.get("/item-requests/{request_id}", response_model=ItemRequestOut)
def get_item_request(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_REQUESTS,
) -> dict:
    return _request_or_404(db, request_id)


@router.post("/item-requests/{request_id}/status", response_model=ItemRequestOut)
def set_item_request_status(
    request_id: int,
    payload: ItemRequestStatusIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    _request_or_404(db, request_id)
    row = db.set_item_request_status(request_id, payload.status, who.actor)
    db.audit(who.actor, "item_request_status", f"request id={request_id} status={payload.status}")
    return row


@router.put("/item-requests/{request_id}/note", response_model=ItemRequestOut)
def set_item_request_note(
    request_id: int,
    payload: ItemRequestNoteIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
) -> dict:
    """The staff's own note (never shown to the customer)."""
    _request_or_404(db, request_id)
    row = db.set_item_request_note(request_id, payload.note.strip(), who.actor)
    db.audit(who.actor, "item_request_note", f"request id={request_id}")
    return row


@router.get("/item-requests/{request_id}/messages", response_model=list[ItemRequestMessageOut])
def list_item_request_messages(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_REQUESTS,
) -> list[dict]:
    _request_or_404(db, request_id)
    return db.list_item_request_messages(request_id)


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
    row = _request_or_404(db, request_id)
    if who.kind != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can message customers")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is empty")
    if not row.get("platform"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer has no messenger")
    message = db.add_item_request_message(request_id, text, who.actor)
    db.audit(who.actor, "item_request_message", f"request id={request_id} message id={message['id']}")
    db.add_event("item_request_message", message["id"], who.actor)
    return message


@router.get("/item-request-messages/{message_id}", response_model=ItemRequestMessageDelivery)
def get_item_request_message(
    message_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_REQUESTS,
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
