"""Staff endpoints of v2.6.0: product groups (show in bot / phone group) and the
customers' unavailable item requests."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..accounting_reader import AccountingReader
from ..db_own import OwnDB
from ..schemas import (
    ItemRequestOut,
    ItemRequestStatusIn,
    ProductGroupOut,
    ProductGroupsIn,
)
from ..security import Identity, require_permission
from ..staff import P_CATALOG, P_VIEW

router = APIRouter(prefix="/admin")

CAN_VIEW = Depends(require_permission(P_VIEW))
CAN_MANAGE_CATALOG = Depends(require_permission(P_CATALOG))


def _groups_out(db: OwnDB, reader: AccountingReader) -> list[ProductGroupOut]:
    stored = db.list_group_settings()
    out: list[ProductGroupOut] = []
    seen: set[int] = set()
    for g in reader.list_groups():
        code = int(g["code"])
        seen.add(code)
        row = stored.get(code) or {}
        out.append(ProductGroupOut(code=code, name=str(g.get("name") or "").strip(),
                                   show_in_bot=bool(row.get("show_in_bot")),
                                   is_phone=bool(row.get("is_phone"))))
    for code, row in stored.items():
        if code not in seen and (row["show_in_bot"] or row["is_phone"]):
            out.append(ProductGroupOut(code=code, name="", show_in_bot=bool(row["show_in_bot"]),
                                       is_phone=bool(row["is_phone"]), missing=True))
    return out


@router.get("/product-groups", response_model=list[ProductGroupOut])
def list_product_groups(
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    _: Identity = CAN_VIEW,
) -> list[ProductGroupOut]:
    """Accounting product groups with the two ShopAdmin checkboxes."""
    return _groups_out(db, reader)


@router.put("/product-groups", response_model=list[ProductGroupOut])
def save_product_groups(
    payload: ProductGroupsIn,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    who: Identity = CAN_MANAGE_CATALOG,
) -> list[ProductGroupOut]:
    entries = [(g.code, g.show_in_bot, g.is_phone) for g in payload.groups]
    if len({code for code, _, _ in entries}) != len(entries):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate group")
    db.set_group_settings(entries, who.actor)
    shown = sum(1 for _, s, _ in entries if s)
    phones = sum(1 for _, _, p in entries if p)
    db.audit(who.actor, "product_groups_save",
             f"groups={len(entries)} shown={shown} phone={phones}")
    db.add_event("product_groups_changed", None, who.actor)
    return _groups_out(db, reader)


@router.get("/item-requests", response_model=list[ItemRequestOut])
def list_item_requests(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(new|seen|done)$"),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> list[dict]:
    return db.list_item_requests(status_filter)


@router.get("/item-requests/{request_id}", response_model=ItemRequestOut)
def get_item_request(
    request_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> dict:
    row = db.get_item_request(request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


@router.post("/item-requests/{request_id}/status", response_model=ItemRequestOut)
def set_item_request_status(
    request_id: int,
    payload: ItemRequestStatusIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_VIEW,
) -> dict:
    if db.get_item_request(request_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    row = db.set_item_request_status(request_id, payload.status, who.actor)
    db.audit(who.actor, "item_request_status", f"request id={request_id} status={payload.status}")
    return row
