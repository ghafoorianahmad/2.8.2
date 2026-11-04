"""v2.18.1 «محاسبهٔ اقساط»: settings, saved quotes, the customer card, and the same service for the
bot and the mini app behind a switch that is off by default.

Everything for customers goes through :func:`installments.customer_view`: no rate, no interest.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import deps, faq, installment_card, installments, ownership
from ..accounting_reader import AccountingReader
from .public import _staff_products
from ..config import Settings
from ..db_own import OwnDB
from ..security import Identity, get_api_identity, require_any, require_permission
from ..staff import (
    P_INSTALLMENT_EDIT,
    P_INSTALLMENT_RULES_EDIT,
    P_INSTALLMENT_RULES_VIEW,
    P_INSTALLMENT_VIEW,
)
from ..util import now_iso

router = APIRouter()
logger = logging.getLogger("shopapi.installments")

RATE_KEY = "installment_rate"
CUSTOMER_KEY = "installment_customer_enabled"
SHOP_NAME = "عصر ارتباطات ۲"
#: ``POST /installments/quote`` while the switch is off
SWITCHED_OFF = "Installment calculator is off"
MIN_CUSTOMER_SEARCH = 2

CAN_VIEW = Depends(require_permission(P_INSTALLMENT_VIEW))
CAN_EDIT = Depends(require_permission(P_INSTALLMENT_EDIT))
CAN_READ_SETTINGS = Depends(require_any(P_INSTALLMENT_VIEW, P_INSTALLMENT_RULES_VIEW))
CAN_CHANGE_RULES = Depends(require_permission(P_INSTALLMENT_RULES_EDIT))


class SheetIn(BaseModel):
    phone_name: str = Field(default="", max_length=200)
    price: int = Field(ge=0)
    down: int = Field(ge=0)
    rate: str = Field(default=installments.DEFAULT_RATE, max_length=12)
    checks: list[int] = Field(min_length=1, max_length=installments.MAX_MONTHS)
    dates: list[str] = Field(default_factory=list, max_length=installments.MAX_MONTHS)


class SendIn(BaseModel):
    user_id: int
    sheet: SheetIn


class SettingsIn(BaseModel):
    rate: Optional[str] = Field(None, max_length=12)
    customer_enabled: Optional[bool] = None


class DeliveryResultIn(BaseModel):
    ok: bool
    error: str = Field(default="", max_length=300)


class CustomerQuoteIn(BaseModel):
    phone_name: str = Field(default="", max_length=120)
    price: int = Field(ge=0)
    down: int = Field(ge=0)
    months: int


def saved_rate(db: OwnDB) -> str:
    value = db.get_state(RATE_KEY, installments.DEFAULT_RATE) or installments.DEFAULT_RATE
    return value if installments.parse_rate(value) is not None else installments.DEFAULT_RATE


def customer_enabled(db: OwnDB) -> bool:
    """Off until the owner turns it on in «قواعد فروشگاه»."""
    return db.get_state(CUSTOMER_KEY, "0") == "1"


def _settings_out(db: OwnDB) -> dict:
    return {"rate": saved_rate(db), "customer_enabled": customer_enabled(db)}


def _today_jalali() -> str:
    return installments.jalali_text(*installments.jalali_from_date(date.today()))


def _sheet(payload: SheetIn) -> installments.Sheet:
    if installments.parse_rate(payload.rate) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نرخ ماهانه درست نیست.")
    sheet = installments.Sheet(
        phone_name=" ".join(payload.phone_name.split()), price=payload.price, down=payload.down,
        rate=installments.rate_text(payload.rate), checks=tuple(payload.checks),
        dates=tuple(payload.dates), date=_today_jalali())
    problem = installments.sheet_problem(sheet)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    return sheet


def _card(db: OwnDB, sheet: installments.Sheet) -> dict:
    """The customer's view, its text, and its image (empty when no browser can make one)."""
    view = installments.customer_view(sheet)
    png = installment_card.render_png(view, shop=SHOP_NAME, phone=faq.values(db).get("phone", ""))
    return {"view": view, "text": installments.customer_text(sheet, SHOP_NAME),
            "png_b64": base64.b64encode(png).decode("ascii") if png else ""}


def _sheet_of(row: dict) -> installments.Sheet:
    data = json.loads(row["sheet"])
    return installments.Sheet(
        phone_name=str(data.get("phone_name") or ""), price=int(data["price"]),
        down=int(data["down"]), rate=str(data.get("rate") or ""),
        checks=tuple(int(c) for c in data["checks"]),
        dates=tuple(str(d) for d in data.get("dates") or ()), date=str(data.get("date") or ""))


def _quote_out(db: OwnDB, row: dict) -> dict:
    sheet = _sheet_of(row)
    user = db.get_user_by_id(int(row["user_id"])) if row.get("user_id") else None
    return {"id": row["id"], "created_at": row["created_at"], "actor": row["actor"],
            "user_id": row.get("user_id"), "customer_name": str((user or {}).get("name") or ""),
            "status": row["status"], "error": row.get("error") or "",
            "phone_name": sheet.phone_name, "price": sheet.price, "down": sheet.down,
            "rate": sheet.rate, "checks": list(sheet.checks), "dates": list(sheet.dates),
            "date": sheet.date, "interest": sheet.interest, "grand_total": sheet.grand_total}


def _store(db: OwnDB, who: Identity, sheet: installments.Sheet, user_id: int | None,
           state: str) -> dict:
    body = json.dumps({"phone_name": sheet.phone_name, "price": sheet.price, "down": sheet.down,
                       "rate": sheet.rate, "checks": list(sheet.checks),
                       "dates": list(sheet.dates), "date": sheet.date}, ensure_ascii=False)
    with db._lock:
        cursor = db._conn.execute(
            "INSERT INTO installment_quotes (created_at, actor, staff_id, user_id, sheet, status) "
            "VALUES (?,?,?,?,?,?)",
            (now_iso(), who.actor, ownership.staff_id(who), user_id, body, state))
        db._commit()
        return db._fetchone("SELECT * FROM installment_quotes WHERE id=?", (cursor.lastrowid,))


# ---- settings ---------------------------------------------------------------------------------
@router.get("/admin/installments/settings")
def get_settings(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_READ_SETTINGS) -> dict:
    return _settings_out(db)


@router.put("/admin/installments/settings")
def put_settings(payload: SettingsIn, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_CHANGE_RULES) -> dict:
    """The default rate and the customers' calculator: only with their own tick."""
    if payload.rate is not None:
        if installments.parse_rate(payload.rate) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نرخ ماهانه درست نیست.")
        db.set_state(RATE_KEY, installments.rate_text(payload.rate), who.actor)
    if payload.customer_enabled is not None:
        db.set_state(CUSTOMER_KEY, "1" if payload.customer_enabled else "0", who.actor)
    db.audit(who.actor, "installment_settings", json.dumps(_settings_out(db)))
    return _settings_out(db)


# ---- what the page picks from ------------------------------------------------------------------
@router.get("/admin/installments/items")
def pick_items(
    q: str = Query("", max_length=100),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: Identity = CAN_VIEW,
) -> list[dict]:
    """Names and prices to pick from (without the tick of «محصولات»: only these two). A phone
    has one row per color, at its price in the current list."""
    try:
        found = _staff_products(reader, db, settings, q=q.strip() or None, group=None,
                                in_stock=False, page=1, page_size=50,
                                level=settings.price_level_for("staff"))
    except Exception as exc:  # noqa: BLE001 - the price can still be typed
        logger.warning("items not read: %s", type(exc).__name__)
        return []
    out: list[dict] = []
    for item in found.get("items") or ():
        for variant in item.get("variants") or ():
            price = float(variant.get("unit_price") or 0)
            if price > 0 and not variant.get("price_held"):
                name = " ".join(p for p in (str(item["name"]), str(variant.get("color") or ""),
                                            str(variant.get("part") or "")) if p)
                out.append({"code": int(item["code"]), "name": name, "price": int(price)})
        if not item.get("variants") and float(item.get("unit_price") or 0) > 0:
            out.append({"code": int(item["code"]), "name": str(item["name"]),
                        "price": int(float(item["unit_price"]))})
    return out


@router.get("/admin/installments/customers")
def pick_customers(
    q: str = Query("", max_length=100),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_EDIT,
) -> list[dict]:
    """Who a card can go to: the name and the last two digits of the number, nothing more."""
    needle = " ".join(q.split())
    if len(needle) < MIN_CUSTOMER_SEARCH:
        return []
    out: list[dict] = []
    for user in db.list_users("approved") + db.list_users("pending"):
        if not user.get("chat_id"):
            continue
        if needle in str(user.get("name") or "") or needle in str(user.get("phone") or ""):
            out.append({"id": user["id"], "name": str(user.get("name") or ""),
                        "platform": str(user.get("platform") or ""),
                        "phone_tail": str(user.get("phone") or "")[-2:]})
        if len(out) >= 20:
            break
    return out


# ---- cards and quotes (staff) -------------------------------------------------------------------
@router.post("/admin/installments/card")
def staff_card(payload: SheetIn, db: OwnDB = Depends(deps.get_db),
               _: Identity = CAN_VIEW) -> dict:
    return _card(db, _sheet(payload))


@router.post("/admin/installments/quotes", status_code=status.HTTP_201_CREATED)
def save_quote(payload: SheetIn, db: OwnDB = Depends(deps.get_db),
               who: Identity = CAN_EDIT) -> dict:
    row = _store(db, who, _sheet(payload), None, "saved")
    db.audit(who.actor, "installment_quote", f"quote id={row['id']}")
    return _quote_out(db, row)


@router.get("/admin/installments/quotes")
def list_quotes(limit: int = Query(100, ge=1, le=500), db: OwnDB = Depends(deps.get_db),
                who: Identity = CAN_VIEW) -> list[dict]:
    """A user's own quotes; «مدیر» everyone's."""
    with db._lock:
        if ownership.is_manager(who):
            rows = db._fetchall("SELECT * FROM installment_quotes ORDER BY id DESC LIMIT ?",
                                (limit,))
        else:
            rows = db._fetchall("SELECT * FROM installment_quotes WHERE staff_id=? "
                                "ORDER BY id DESC LIMIT ?", (ownership.staff_id(who), limit))
    return [_quote_out(db, row) for row in rows]


@router.post("/admin/installments/send", status_code=status.HTTP_201_CREATED)
def send_card(payload: SendIn, db: OwnDB = Depends(deps.get_db),
              who: Identity = CAN_EDIT) -> dict:
    """To the customer's chat. Saved as ``pending``; the bot of their platform delivers it
    (events feed) and reports the outcome, which «تاریخچه» shows."""
    if who.kind != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can message customers")
    user = db.get_user_by_id(payload.user_id)
    if user is None or user["status"] == "rejected" or not user.get("chat_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    row = _store(db, who, _sheet(payload.sheet), payload.user_id, "pending")
    db.audit(who.actor, "installment_send", f"quote id={row['id']} user id={payload.user_id}")
    db.add_event("installment_card", row["id"], who.actor)
    return _quote_out(db, row)


@router.get("/admin/installments/deliveries/{quote_id}")
def delivery(quote_id: int, db: OwnDB = Depends(deps.get_db),
             who: Identity = CAN_VIEW) -> dict:
    """For the bot (service key): where it goes and the customer's card, nothing else."""
    if who.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    with db._lock:
        row = db._fetchone("SELECT * FROM installment_quotes WHERE id=?", (quote_id,))
    user = db.get_user_by_id(int(row["user_id"])) if row and row.get("user_id") else None
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found")
    card = _card(db, _sheet_of(row))
    return {"status": row["status"], "platform": user["platform"], "chat_id": user["chat_id"],
            "text": card["text"], "png_b64": card["png_b64"]}


@router.post("/admin/installments/deliveries/{quote_id}/result")
def delivery_result(quote_id: int, payload: DeliveryResultIn, db: OwnDB = Depends(deps.get_db),
                    who: Identity = CAN_VIEW) -> dict:
    if who.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    with db._lock:
        db._conn.execute("UPDATE installment_quotes SET status=?, error=? WHERE id=?",
                         ("sent" if payload.ok else "failed", payload.error, quote_id))
        db._commit()
    return {"ok": True}


# ---- the same service for customers (behind a switch that is off by default) --------------------
@router.get("/installments/settings")
def public_settings(db: OwnDB = Depends(deps.get_db), _: str = Depends(get_api_identity)) -> dict:
    """Only whether it is on: the rate never leaves the server this way."""
    return {"enabled": customer_enabled(db)}


@router.post("/installments/quote")
def customer_quote(payload: CustomerQuoteIn, db: OwnDB = Depends(deps.get_db),
                   _: str = Depends(get_api_identity)) -> dict:
    """The customer's own calculator: the card and its text, never the rate or the interest."""
    if not customer_enabled(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, SWITCHED_OFF)
    try:
        quote = installments.calculate(payload.price, payload.down, payload.months, saved_rate(db))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    next_month = installments.add_months(*installments.jalali_from_date(date.today()), 1)
    sheet = installments.Sheet(
        phone_name=" ".join(payload.phone_name.split()), price=quote.price, down=quote.down,
        rate=quote.rate, checks=quote.checks,
        dates=tuple(installments.schedule(installments.jalali_text(*next_month), quote.months)),
        date=_today_jalali())
    return _card(db, sheet)
