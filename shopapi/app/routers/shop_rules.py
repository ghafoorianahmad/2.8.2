"""v2.17.0: the shop's working rules, each with its own tick in «کاربران سیستم»:
status codes, working hours, staff notifications, automatic invoices (placeholder),
and what the bots need for staff notifications."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import auto_quote, control, deps, faq, ownership, product_aliases, staff_alerts
from . import installments as installment_rules
from ..config import Settings
from ..db_own import OwnDB
from ..security import Identity, get_api_identity, get_identity, require_any, require_permission
from ..staff import (
    P_AUTO_INVOICE_VIEW,
    P_AUTO_QUOTE_EDIT,
    P_AUTO_QUOTE_VIEW,
    P_CLAIM,
    P_DASHBOARD,
    P_FAQ_EDIT,
    P_FAQ_VIEW,
    P_INSTALLMENT_RULES_VIEW,
    P_PRODUCT_ALIAS,
    P_STAFF_ALERTS_EDIT,
    P_STAFF_ALERTS_VIEW,
    P_STATUS_CODES_EDIT,
    P_STATUS_CODES_VIEW,
    P_WORK_HOURS_EDIT,
    P_WORK_HOURS_VIEW,
)

router = APIRouter()

CAN_SEE_RULES = Depends(require_any(P_STATUS_CODES_VIEW, P_WORK_HOURS_VIEW, P_AUTO_INVOICE_VIEW,
                                    P_AUTO_QUOTE_VIEW, P_FAQ_VIEW, P_INSTALLMENT_RULES_VIEW))
CAN_SEE_ALERTS = Depends(require_any(P_STAFF_ALERTS_VIEW, P_DASHBOARD))


class StatusCodesIn(BaseModel):
    order_status: str = Field(max_length=12)
    handover_status: str = Field("", max_length=12)


class ShiftIn(BaseModel):
    start: str = Field(max_length=5)
    end: str = Field(max_length=5)


class WorkHoursIn(BaseModel):
    start: str = Field(default="", max_length=5)
    end: str = Field(default="", max_length=5)
    days: list[int] = Field(default_factory=list, max_length=7)
    #: v2.18.0: several shifts a day (closed at midday); empty = start..end as one shift
    shifts: list[ShiftIn] = Field(default_factory=list, max_length=6)


class AutoQuoteSwitchIn(BaseModel):
    enabled: bool


class FaqIn(BaseModel):
    enabled: bool
    values: dict[str, str] = Field(default_factory=dict)


class AliasIn(BaseModel):
    text: str = Field(min_length=2, max_length=200)
    model: str = Field(min_length=1, max_length=100)


class AlertActionIn(BaseModel):
    action: str


class StaffLinkIn(BaseModel):
    platform: str = Field(max_length=16)
    chat_id: str = Field(max_length=64)
    phone: str = Field(max_length=20)


class ClaimIn(BaseModel):
    platform: str = Field(max_length=16)
    chat_id: str = Field(max_length=64)
    target_type: str = Field(max_length=16)
    target_id: int


def _status_codes(settings: Settings) -> dict:
    return {"order_status": settings.accounting_status_code,
            "handover_status": settings.accounting_handover_code,
            "configured": settings.status_code_problem() is None,
            "editable": control.STATE.env_file is not None}


@router.get("/admin/shop-rules")
def get_rules(settings: Settings = Depends(deps.get_settings),
              db: OwnDB = Depends(deps.get_db), who: Identity = CAN_SEE_RULES) -> dict:
    """Only the parts this account has a tick for."""
    out: dict = {}
    if who.can(P_STATUS_CODES_VIEW):
        out["status_codes"] = _status_codes(settings)
    if who.can(P_WORK_HOURS_VIEW):
        out["work_hours"] = staff_alerts.load_hours(db).as_dict()
    if who.can(P_FAQ_VIEW):
        out["faq"] = {"enabled": faq.enabled(db), "values": faq.values(db),
                      "report": faq.report(db)}
    if who.can(P_AUTO_QUOTE_VIEW):
        out["auto_quote"] = {"enabled": auto_quote.enabled(db), "report": auto_quote.report(db)}
    if who.can(P_INSTALLMENT_RULES_VIEW):
        out["installment"] = installment_rules._settings_out(db)
    if who.can(P_AUTO_INVOICE_VIEW):
        # v2.17.0: a place for it only: staff turn orders into invoices themselves
        out["auto_invoice"] = {"enabled": False, "available": False}
    return out


@router.put("/admin/shop-rules/status-codes")
def put_status_codes(payload: StatusCodesIn, settings: Settings = Depends(deps.get_settings),
                     db: OwnDB = Depends(deps.get_db),
                     who: Identity = Depends(require_permission(P_STATUS_CODES_EDIT))) -> dict:
    """Saved in the server's settings and in force at once (no restart): a waiting
    order can be written right after this."""
    if control.STATE.env_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Settings file not available")
    values = {"ACCOUNTING_STATUS_CODE": payload.order_status.strip(),
              "ACCOUNTING_HANDOVER_STATUS_CODE": payload.handover_status.strip()}
    problems = control.validate_settings(values)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Invalid settings", "fields": problems})
    order_code = int(values["ACCOUNTING_STATUS_CODE"])
    handover = values["ACCOUNTING_HANDOVER_STATUS_CODE"]
    handover_code = int(handover) if handover else None
    if handover_code == order_code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Invalid settings", "fields": {
                                "ACCOUNTING_HANDOVER_STATUS_CODE": "must differ from the order status"}})
    control.write_env_values(values)
    for key, value in values.items():
        os.environ[key] = value
    settings.accounting_status_code = order_code
    settings.accounting_handover_code = handover_code
    db.audit(who.actor, "status_codes", f"order={order_code} handover={handover_code}")
    return _status_codes(settings)


@router.put("/admin/shop-rules/auto-quote")
def put_auto_quote(payload: AutoQuoteSwitchIn, db: OwnDB = Depends(deps.get_db),
                   who: Identity = Depends(require_permission(P_AUTO_QUOTE_EDIT))) -> dict:
    """v2.18.0 «پاسخ خودکار قیمت»: for items we do not stock (list prices, in the bot only)."""
    auto_quote.set_enabled(db, payload.enabled, who.actor)
    db.audit(who.actor, "auto_quote", f"enabled={payload.enabled}")
    return {"enabled": auto_quote.enabled(db), "report": auto_quote.report(db)}


@router.put("/admin/shop-rules/faq")
def put_faq(payload: FaqIn, db: OwnDB = Depends(deps.get_db),
            who: Identity = Depends(require_permission(P_FAQ_EDIT))) -> dict:
    """v2.18.0 «پاسخ‌گوی خودکار»: the switch and the shop's details its answers use."""
    faq.set_enabled(db, payload.enabled, who.actor)
    if payload.values:
        faq.save_values(db, payload.values, who.actor)
    db.audit(who.actor, "faq", f"enabled={payload.enabled}")
    return {"enabled": faq.enabled(db), "values": faq.values(db), "report": faq.report(db)}


@router.get("/admin/product-aliases/models")
def alias_models(_: Identity = Depends(require_permission(P_PRODUCT_ALIAS))) -> list[str]:
    return product_aliases.model_names()


@router.post("/admin/product-aliases")
def teach_alias(payload: AliasIn, db: OwnDB = Depends(deps.get_db),
                who: Identity = Depends(require_permission(P_PRODUCT_ALIAS))) -> dict:
    """v2.18.0: staff say what a customer's words mean; the bot understands them from then on."""
    try:
        learned = product_aliases.learn(db, payload.text, payload.model, who.actor)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "مدل یا متن درست نیست.") from None
    db.audit(who.actor, "product_alias", f"model={payload.model}")
    return learned


@router.put("/admin/shop-rules/work-hours")
def put_work_hours(payload: WorkHoursIn, db: OwnDB = Depends(deps.get_db),
                   who: Identity = Depends(require_permission(P_WORK_HOURS_EDIT))) -> dict:
    shifts = [(shift.start, shift.end) for shift in payload.shifts]
    problem = staff_alerts.hours_problem(payload.start, payload.end, payload.days, shifts)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    hours = staff_alerts.save_hours(db, payload.start, payload.end, payload.days, who.actor,
                                    shifts)
    db.audit(who.actor, "work_hours",
             f"{[f'{a}-{b}' for a, b in hours.shifts]} days={list(hours.days)}")
    return hours.as_dict()


# ---- staff notifications: on / off ---------------------------------------------------------------
@router.get("/admin/staff-alerts/state")
def alert_state(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_SEE_ALERTS) -> dict:
    current = staff_alerts.state(db).as_dict()
    if not ownership.is_manager(who):
        current["override_by"] = ""
    return {**current, "work_hours": staff_alerts.load_hours(db).as_dict()}


@router.post("/admin/staff-alerts/action")
def alert_action(payload: AlertActionIn, db: OwnDB = Depends(deps.get_db),
                 who: Identity = Depends(require_permission(P_STAFF_ALERTS_EDIT))) -> dict:
    if payload.action not in staff_alerts.ACTIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown action")
    current = staff_alerts.apply_action(db, payload.action, who.actor)
    db.audit(who.actor, "staff_alerts", f"action={payload.action} until={current.until}")
    return {**current.as_dict(), "work_hours": staff_alerts.load_hours(db).as_dict()}


# ---- the bots ------------------------------------------------------------------------------------
def _service_only(identity: Identity = Depends(get_identity)) -> Identity:
    if identity.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    return identity


@router.get("/admin/staff-alerts/due")
def alerts_due(platform: str = Query(..., max_length=16), db: OwnDB = Depends(deps.get_db),
               _: Identity = Depends(_service_only)) -> dict:
    return {"items": staff_alerts.due(db, platform)}


@router.post("/staff-links")
def link_staff(payload: StaffLinkIn, db: OwnDB = Depends(deps.get_db),
               role: str = Depends(get_api_identity)) -> dict:
    """The bot passes on a verified contact (the customer's own, same rule as /users/
    register). A staff member's number links their chat; nothing else happens."""
    if role not in ("bot", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available on this channel")
    linked = staff_alerts.link(db, payload.platform, payload.chat_id, payload.phone)
    if linked is None:
        return {"linked": False}
    db.audit(role, "staff_link", f"staff id={linked['id']} platform={payload.platform}")
    return {"linked": True, "name": linked["full_name"] or linked["username"]}


@router.post("/admin/staff-alerts/claim")
def claim_from_bot(payload: ClaimIn, db: OwnDB = Depends(deps.get_db),
                   _: Identity = Depends(_service_only)) -> dict:
    """«برداشت» in the bot, by a linked chat. ``claimed`` = it is theirs now."""
    row = db.staff_by_link(payload.platform, payload.chat_id)
    if row is None or not row["active"]:
        return {"claimed": False, "reason": "not_linked"}
    if payload.target_type not in ("order", "request"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown target")
    target = (db.get_order(payload.target_id) if payload.target_type == "order"
              else db.get_item_request(payload.target_id))
    if target is None:
        return {"claimed": False, "reason": "gone"}
    perms = staff_alerts.effective_permissions(row["role"], row.get("perm_grant"),
                                               row.get("perm_revoke"))
    needed = "orders.view" if payload.target_type == "order" else "requests.view"
    if P_CLAIM not in perms or needed not in perms:
        return {"claimed": False, "reason": "not_allowed"}
    owner = target.get("owner_id")
    if owner is not None and owner != row["id"]:
        return {"claimed": False, "reason": "taken"}
    if owner is None and not db.claim(payload.target_type, payload.target_id, int(row["id"])):
        return {"claimed": False, "reason": "taken"}
    if owner is None:
        db.log_activity(staff_id=int(row["id"]), actor=row["username"], action=ownership.A_CLAIM,
                        target_type=payload.target_type, target_id=payload.target_id,
                        customer_id=target.get("user_id"), detail="bot")
        db.audit(row["username"], f"{payload.target_type}_claim",
                 f"{payload.target_type} id={payload.target_id} from the bot")
    return {"claimed": True}


@router.post("/admin/orders/{order_id}/claim")
def claim_order(order_id: int, db: OwnDB = Depends(deps.get_db),
                who: Identity = Depends(require_permission(P_CLAIM))) -> dict:
    """«برداشت» in ShopAdmin: stops the repeats."""
    order = ownership.ensure_visible(who, db.get_order(order_id))
    ownership.ensure_order_editable(order)
    ownership.take(db, who, "order", order)
    return {"claimed": True}


@router.post("/admin/item-requests/{request_id}/claim")
def claim_request(request_id: int, db: OwnDB = Depends(deps.get_db),
                  who: Identity = Depends(require_permission(P_CLAIM))) -> dict:
    row = ownership.ensure_visible(who, db.get_item_request(request_id), "Request")
    ownership.ensure_request_editable(row)
    ownership.take(db, who, "request", row)
    return {"claimed": True}


@router.post("/admin/staff/{staff_id}/unlink")
def unlink_staff(staff_id: int, platform: Optional[str] = Query(None, max_length=16),
                 db: OwnDB = Depends(deps.get_db),
                 who: Identity = Depends(require_permission("staff.edit"))) -> dict:
    db.delete_staff_links(staff_id, platform)
    db.audit(who.actor, "staff_unlink", f"staff id={staff_id} platform={platform or 'all'}")
    return {"ok": True}
