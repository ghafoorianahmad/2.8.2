"""Distributor price list, row mapping, proxy pool, inquiries (REQUIREMENTS §4–6).

``/admin/...``: signed-in staff (ShopAdmin) or the server-local service key.
``/worker/...``: only the Telegram worker key (WORKER_API_KEY, loopback only).
Proxy secrets are returned in full only to the worker; staff see a mask.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import deps, owner_alerts
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..pricelist.importer import ImportResult, import_pdf, reread_list
from .. import groups as group_config
from ..pricelist.matching import SUGGESTIONS, auto_match, confident, name_candidates, name_match
from ..pricelist import notes
from ..pricelist.repo import PriceListRepo
from .. import sales as sales_state
from .. import tgchannels
from ..proxypool import ACTIVE_CAP, ProxyLink, ProxyPool, masked_secret, parse_proxy_link
from ..security import Identity, get_identity, require_any, require_permission, require_worker
from ..staff import (P_PRICELIST, P_PRICELIST_VIEW, P_PROXIES, P_REQUESTS_VIEW,
                     P_SERVER_MANAGE)
from ..util import now_utc

router = APIRouter()

CAN_VIEW = Depends(require_permission(P_PRICELIST_VIEW))
CAN_PRICELIST = Depends(require_permission(P_PRICELIST))
CAN_PROXIES = Depends(require_permission(P_PROXIES))
CAN_SEE_PROXIES = Depends(require_permission(P_PRICELIST_VIEW))
#: price inquiries are shown with the list and with the item requests
CAN_SEE_INQUIRIES = Depends(require_any(P_PRICELIST_VIEW, P_REQUESTS_VIEW))
WORKER = Depends(require_worker)

#: Worker-side state kept on the server (cursor of the channel, last collection).
WORKER_STATE_PREFIX = "worker:"
WORKER_STATE_KEYS = frozenset({
    "tg_price_last_id", "tg_proxy_collected_at", "tg_proxy_last_ids", "tg_status",
    # v2.9.1: the newest list post sent (id, edit, size) and the text posts sent
    "tg_price_version", "tg_price_notes",
    # v2.9.2: the last proxy collection, and «جمع‌آوری اکنون» (asked / handled)
    "tg_collect_info", "tg_collect_request", "tg_collect_done",
    # v2.13.0: «دریافت لیست اکنون» (asked / handled)
    "tg_price_request", "tg_price_done",
})
#: v2.9.2: ShopAdmin «جمع‌آوری اکنون» -> the worker collects within seconds
COLLECT_REQUEST_KEY = WORKER_STATE_PREFIX + "tg_collect_request"
#: v2.13.0: ShopAdmin «دریافت لیست اکنون» -> the worker reads the price channel now
PRICE_REQUEST_KEY = WORKER_STATE_PREFIX + "tg_price_request"
PRICE_DONE_KEY = WORKER_STATE_PREFIX + "tg_price_done"
#: v2.13.0: «خواندن دوباره» never keeps ShopAdmin waiting longer than this
REREAD_TIMEOUT_SEC = 60
#: Alerts the worker may raise (each at most once per ALERT_REPEAT).
WORKER_ALERTS = frozenset({"telegram_login_required", "telegram_unreachable",
                           # v2.9.0: a price-list PDF of the channel could not be downloaded
                           "telegram_pricelist_error",
                           # v2.13.0: Telegram paused the reader for an hour or more;
                           # the supervisor started a part of the server again
                           "telegram_flood_wait", "worker_restarted"})
ALERT_REPEAT = timedelta(hours=6)
#: v2.13.0: these also go straight to the owner's Bale chat (the bot does not know
#: them, and the bot may be the part that was restarted)
DIRECT_ALERTS = {
    "telegram_flood_wait": "⚠️ هشدار سرور: تلگرام خوانندهٔ لیست قیمت را برای مدتی طولانی "
                           "متوقف کرده است (FloodWait). پس از پایان زمان انتظار خودکار ادامه "
                           "می‌دهد؛ تا آن زمان لیست تازه را با «بارگذاری PDF» بدهید.",
    "worker_restarted": "⚠️ هشدار سرور: «{detail}» از کار افتاده بود و خودکار دوباره "
                        "راه‌اندازی شد. اگر تکرار شد، گزارش سرور را بررسی کنید.",
}


# ---- models -----------------------------------------------------------------
class PdfIn(BaseModel):
    data_b64: str = Field(min_length=8)
    source_ref: str = Field(default="", max_length=200)
    posted_at: Optional[str] = Field(default=None, max_length=40)
    #: v2.9.1 (worker): the newest list post that still exists in the channel
    latest: bool = False


class NoteIn(BaseModel):
    """v2.9.1: a text post of the price channel after the list."""
    text: str = Field(min_length=1, max_length=4000)
    source_ref: str = Field(default="", max_length=200)
    posted_at: Optional[str] = Field(default=None, max_length=40)


class RowDecisionIn(BaseModel):
    row_key: str = Field(min_length=1, max_length=400)
    list_id: Optional[int] = None


class ChannelIn(BaseModel):
    id: int
    username: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=200)
    broadcast: bool = True


class ChannelsIn(BaseModel):
    channels: list[ChannelIn] = Field(default_factory=list, max_length=1000)


class ChannelRoleIn(BaseModel):
    role: Literal["", "pricelist", "proxy", "accessories", "used", "ignore"]


class ImportOut(BaseModel):
    outcome: str
    list_id: Optional[int] = None
    list_date: str = ""
    row_count: int = 0
    reasons: list[str] = []
    auto_mapped: int = 0
    held_rows: int = 0


class MappingIn(BaseModel):
    row_key: str = Field(min_length=1, max_length=400)
    action: Literal["map", "ignore"]
    kala_code: Optional[int] = Field(default=None, gt=0)
    color_label: str = Field(default="", max_length=60)


class IgnoreIn(BaseModel):
    row_keys: list[str] = Field(min_length=1, max_length=500)


class DecideIn(BaseModel):
    reason: str = Field(default="", max_length=300)


class ProxyIn(BaseModel):
    link: str = Field(min_length=10, max_length=1000)
    main: bool = False


class ProxyStateIn(BaseModel):
    state: Literal["probation", "main", "disabled"]


class ProxyResult(BaseModel):
    id: int
    ok: bool
    latency_ms: Optional[int] = Field(default=None, ge=0, le=600_000)


class ProxyReportIn(BaseModel):
    results: list[ProxyResult] = Field(max_length=500)


class TestedLink(BaseModel):
    link: str = Field(min_length=10, max_length=1000)
    latency_ms: Optional[int] = Field(default=None, ge=0, le=600_000)


class CandidatesIn(BaseModel):
    links: list[str] = Field(default_factory=list, max_length=2000)
    source: str = Field(default="channel", max_length=100)
    #: v2.9.0: links the worker tested itself (working ones / failed ones)
    tested: list[TestedLink] = Field(default_factory=list, max_length=500)
    failed: list[str] = Field(default_factory=list, max_length=2000)


class LinksIn(BaseModel):
    links: list[str] = Field(max_length=2000)


class WorkerStateIn(BaseModel):
    key: str
    value: str = Field(max_length=4000)


class WorkerAlertIn(BaseModel):
    kind: str
    #: v2.13.0 ``worker_restarted``: which part (a Persian label from the supervisor)
    detail: str = Field(default="", max_length=120)


# ---- helpers ----------------------------------------------------------------
def _decode_pdf(data_b64: str, settings: Settings) -> bytes:
    if len(data_b64) > settings.pricelist_max_bytes * 4 // 3 + 8:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF too large")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid base64") from None
    if len(data) > settings.pricelist_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF too large")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a PDF file")
    return data


def phone_product_names(db: OwnDB, reader: AccountingReader, settings: Settings) -> dict[int, str]:
    """v2.8.0: {code: name} of the «سازه حساب» products rows may be mapped to: the
    phone groups' products (every active product while no phone group is chosen)."""
    cfg = group_config.load(db, reader)
    if not cfg.phone_configured:
        return reader.product_names()
    known = {int(g["code"]) for g in reader.list_groups() if g.get("code") is not None}
    phone_groups = {c for c in known | cfg.phone if cfg.is_phone(c)}
    found = reader.list_products(q=None, in_stock=False, page=1, page_size=1_000_000,
                                 level=settings.price_level_bot, include_groups=phone_groups)
    return {int(p["code"]): str(p["name"] or "") for p in found["items"]
            if cfg.is_phone(p.get("group"))}


def _name_match(db: OwnDB, repo: PriceListRepo, reader: AccountingReader | None,
                settings: Settings | None, list_id: int, actor: str) -> int:
    """Name-similarity mapping of a list; the accounting DB being down = skipped."""
    if reader is None or settings is None:
        return 0
    try:
        names = phone_product_names(db, reader, settings)
    except Exception:  # noqa: BLE001 - pyodbc / timeouts: the rows stay for staff
        return 0
    done = name_match(repo, list_id, names, actor="system:auto")
    if done:
        db.audit(actor, "price_mapping_auto_name", f"list id={list_id} rows={done}")
    return done


def _import_out(result: ImportResult) -> ImportOut:
    return ImportOut(**result.__dict__)


def _proxy_out(p: dict, *, with_secret: bool) -> dict:
    out = {
        key: p.get(key) for key in (
            "id", "host", "port", "source", "state", "added_at", "promoted_at", "retired_at",
            "last_ok_at", "last_fail_at", "last_checked_at", "last_latency_ms",
            "good_days", "checked_days", "bad_streak", "stability", "failing_now",
        )
    }
    out["kind"] = ProxyLink(p["host"], p["port"], p["secret"]).kind
    if with_secret:
        out["secret"] = p["secret"]
    else:
        out["secret_masked"] = masked_secret(p["secret"])
    if out.get("stability") is not None:
        out["stability"] = round(float(out["stability"]), 3)
    return out


def _alert_once(db: OwnDB, kind: str, actor: str) -> bool:
    """Add an event ``kind`` unless one was added within ALERT_REPEAT."""
    key = f"alert_at:{kind}"
    last = db.get_state(key, "")
    now = now_utc()
    if last:
        try:
            if now - datetime.fromisoformat(last) < ALERT_REPEAT:
                return False
        except ValueError:
            pass
    db.set_state(key, now.isoformat(timespec="seconds"), actor)
    db.add_event(kind, None, actor)
    return True


# ---- price lists (staff) ----------------------------------------------------------
@router.get("/admin/pricelists")
def list_pricelists(
    limit: int = Query(50, ge=1, le=500),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> list[dict]:
    return PriceListRepo(db).list_lists(limit)


@router.post("/admin/pricelists", response_model=ImportOut)
def upload_pricelist(
    payload: PdfIn,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_PRICELIST,
) -> ImportOut:
    """Manual upload (ShopAdmin): also the fallback while Telegram is down."""
    data = _decode_pdf(payload.data_b64, settings)
    result = import_pdf(db, settings, data, source="manual",
                        source_ref=payload.source_ref, actor=who.actor)
    out = _import_out(result)
    if result.list_id:
        out.auto_mapped += _name_match(db, PriceListRepo(db), reader, settings, result.list_id,
                                       who.actor)
    return out


@router.post("/admin/pricelists/fetch")
def fetch_pricelist_now(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_PRICELIST) -> dict:
    """v2.13.0 «دریافت لیست اکنون»: the Telegram reader reads the price channel at
    once and sends its newest list again (it looks for this every 20 seconds); the
    server decides as for any list (duplicate / older / new; a file rejected before
    is read again)."""
    ts = now_utc().isoformat(timespec="seconds")
    db.set_state(PRICE_REQUEST_KEY, ts, who.actor)
    db.audit(who.actor, "pricelist_fetch_now", "")
    return {"requested_at": ts}


@router.get("/admin/pricelists/fetch")
def fetch_pricelist_state(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_VIEW) -> dict:
    """Whether the last «دریافت لیست اکنون» was handled by the reader yet."""
    asked = db.get_state(PRICE_REQUEST_KEY, "")
    done = db.get_state(PRICE_DONE_KEY, "")
    return {"requested_at": asked or None, "handled": bool(asked) and done == asked}


@router.post("/admin/pricelists/{list_id}/reread")
def reread_pricelist(
    list_id: int,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """v2.13.0 «خواندن دوباره»: read the archived PDF of a received list again.
    Answers within REREAD_TIMEOUT_SEC whatever the file does (``timeout``)."""
    import concurrent.futures

    if PriceListRepo(db).get_list(list_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "List not found")
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(reread_list, db, settings, list_id, actor=who.actor)
    try:
        result = future.result(timeout=REREAD_TIMEOUT_SEC)
    except concurrent.futures.TimeoutError:
        return {"outcome": "timeout", "list_id": list_id, "reasons": []}
    finally:
        pool.shutdown(wait=False)
    out = _import_out(result)
    if result.outcome in ("active", "held", "older") and result.list_id:
        out.auto_mapped += _name_match(db, PriceListRepo(db), reader, settings, result.list_id,
                                       who.actor)
    return out.model_dump()


@router.get("/admin/pricelists/rows")
def pricelist_rows(
    filter: Literal["unmapped", "mapped", "ignored", "auto", "held", "corrected",
                    "all"] = Query("all"),
    section: Optional[str] = Query(None, max_length=100),
    list_id: Optional[int] = Query(None),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> dict:
    """Rows of the newest list (active or held) with their mapping state.
    Decided rows never come back as unmapped on a new list (same row key, or
    matched automatically: ``auto`` = to review, v2.6.2)."""
    repo = PriceListRepo(db)
    plist = repo.get_list(list_id) if list_id else repo.latest_list()
    if plist is None:
        return {"list": None, "sections": [], "rows": [], "counts": {}}
    rows = repo.rows(plist["id"])
    sections = list(dict.fromkeys(r["section"] for r in rows))
    counts = {
        "unmapped": sum(1 for r in rows if r["action"] is None),
        "mapped": sum(1 for r in rows if r["action"] == "map"),
        "ignored": sum(1 for r in rows if r["action"] == "ignore"),
        "auto": sum(1 for r in rows if r["action"] is not None and r["auto"]),
        # v2.9.1: a new price waiting for a manager / a correction of the channel
        "held": sum(1 for r in rows if r.get("pending_price_rial") is not None),
        "corrected": sum(1 for r in rows if r.get("price_flag") == "correction"),
        "all": len(rows),
    }
    if section:
        rows = [r for r in rows if r["section"] == section]
    if filter == "unmapped":
        rows = [r for r in rows if r["action"] is None]
    elif filter == "mapped":
        rows = [r for r in rows if r["action"] == "map"]
    elif filter == "ignored":
        rows = [r for r in rows if r["action"] == "ignore"]
    elif filter == "auto":
        rows = [r for r in rows if r["action"] is not None and r["auto"]]
    elif filter == "held":
        rows = [r for r in rows if r.get("pending_price_rial") is not None]
    elif filter == "corrected":
        rows = [r for r in rows if r.get("price_flag") == "correction"]
    return {"list": plist, "sections": sections, "rows": rows, "counts": counts}


# ---- v2.9.1: price guard decisions, channel posts --------------------------------------
def _held_row(repo: PriceListRepo, payload: RowDecisionIn) -> tuple[dict, dict]:
    plist = repo.get_list(payload.list_id) if payload.list_id else repo.active_list()
    if plist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    row = repo.rows_by_key(plist["id"]).get(payload.row_key)
    if row is None or row.get("pending_price_rial") is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No price waits for approval on this row")
    return plist, row


@router.post("/admin/pricelists/rows/approve")
def approve_row_price(
    payload: RowDecisionIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """The held new price of a row (more than PRICE_GUARD_PCT) is sold from now."""
    repo = PriceListRepo(db)
    plist, row = _held_row(repo, payload)
    flag = notes.FLAG_CORRECTION if row.get("pending_source") == "correction" else ""
    notes.set_row_price(db, plist["id"], row, row["pending_naghd"], row["pending_raval"],
                        row["pending_price_rial"], flag=flag, note=row.get("flag_note") or "",
                        estimated=bool(row.get("pending_estimated")))
    db.audit(who.actor, "price_row_approve", f"list id={plist['id']}")
    db.add_event("pricelist_corrected", plist["id"], who.actor)
    return repo.rows_by_key(plist["id"])[payload.row_key]


@router.post("/admin/pricelists/rows/reject")
def reject_row_price(
    payload: RowDecisionIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """The held new price is dropped; the previous price stays."""
    repo = PriceListRepo(db)
    plist, row = _held_row(repo, payload)
    notes.set_row_price(db, plist["id"], row, row["naghd"], row["raval"], row["price_rial"],
                        flag="" if row.get("price_flag") == notes.FLAG_HELD
                        else row.get("price_flag") or "",
                        note="" if row.get("price_flag") == notes.FLAG_HELD
                        else row.get("flag_note") or "",
                        estimated=bool(row.get("raval_estimated")))
    db.audit(who.actor, "price_row_reject", f"list id={plist['id']}")
    db.add_event("pricelist_corrected", plist["id"], who.actor)
    return repo.rows_by_key(plist["id"])[payload.row_key]


@router.get("/admin/pricelists/notes")
def pricelist_notes(
    limit: int = Query(30, ge=1, le=200),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> list[dict]:
    """The price channel's text posts (corrections, «فروش بسته») and their outcome."""
    return notes.list_notes(db, limit)


def _can_channels(identity: Identity = Depends(get_identity)) -> Identity:
    """«تنظیمات سرور» on the server (service key) or a manager."""
    if identity.kind == "service":
        return identity
    if identity.must_change_password or not (identity.can(P_SERVER_MANAGE)
                                             or identity.can(P_PRICELIST)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    return identity


@router.get("/admin/telegram/channels")
def telegram_channels(db: OwnDB = Depends(deps.get_db),
                      _: Identity = Depends(_can_channels)) -> dict:
    """v2.9.1: the channels the shop's Telegram account has joined, with roles."""
    return {"channels": tgchannels.load(db), "roles": list(tgchannels.ROLES),
            "working_roles": list(tgchannels.WORKING_ROLES)}


@router.put("/admin/telegram/channels/{channel_id}")
def set_telegram_channel_role(
    channel_id: int,
    payload: ChannelRoleIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = Depends(_can_channels),
) -> dict:
    channel = tgchannels.set_role(db, channel_id, payload.role, who.actor)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    return channel


@router.get("/admin/pricelists/{list_id}")
def get_pricelist(
    list_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_VIEW,
) -> dict:
    repo = PriceListRepo(db)
    plist = repo.get_list(list_id)
    if plist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    return {**plist, "rows": repo.rows(list_id)}


@router.post("/admin/pricelists/{list_id}/approve")
def approve_pricelist(
    list_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """A held list becomes the active one (staff checked the big changes)."""
    repo = PriceListRepo(db)
    plist = repo.get_list(list_id)
    if plist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    if plist["status"] != "held":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Price list is {plist['status']}")
    active = repo.active_list()
    if active is not None and plist["list_date"] < active["list_date"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "A newer price list is already active")
    repo.activate(list_id, who.actor)
    db.audit(who.actor, "pricelist_approve", f"list id={list_id}")
    db.add_event("pricelist_imported", list_id, who.actor)
    return repo.get_list(list_id)


@router.post("/admin/pricelists/{list_id}/reject")
def reject_pricelist(
    list_id: int,
    payload: DecideIn | None = None,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    repo = PriceListRepo(db)
    plist = repo.get_list(list_id)
    if plist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    if plist["status"] != "held":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Price list is {plist['status']}")
    reason = (payload.reason if payload else "") or None
    repo.set_status(list_id, "rejected", who.actor, reason)
    db.audit(who.actor, "pricelist_reject", f"list id={list_id}")
    return repo.get_list(list_id)


# ---- mappings (staff) -------------------------------------------------------------
def _row_in_known_lists(repo: PriceListRepo, row_key: str) -> dict | None:
    for plist in (repo.latest_list(), repo.active_list()):
        if plist is not None:
            row = repo.rows_by_key(plist["id"]).get(row_key)
            if row is not None:
                return row
    return None


@router.get("/admin/price-mappings")
def list_mappings(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_VIEW) -> list[dict]:
    return PriceListRepo(db).list_mappings()


@router.put("/admin/price-mappings")
def put_mapping(
    payload: MappingIn,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """Map a PDF row to one of our products (with the color customers see), or
    ignore it (not sold here). Overwrites an earlier decision for the row."""
    repo = PriceListRepo(db)
    row = _row_in_known_lists(repo, payload.row_key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found in the current list")
    kala_code = None
    if payload.action == "map":
        if payload.kala_code is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kala_code is required")
        found = reader.get_products_for_order(
            [payload.kala_code], settings.price_level_bot, {}
        ).get(payload.kala_code)
        if found is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Product not found in accounting (or inactive)")
        kala_code = payload.kala_code
    mapping = repo.upsert_mapping(
        row_key=payload.row_key, action=payload.action, kala_code=kala_code,
        color_label=payload.color_label.strip() if payload.action == "map" else "",
        section=row["section"], description=row["description"], kind=row["kind"],
        color=row["color"], actor=who.actor,
    )
    db.audit(who.actor, f"price_mapping_{payload.action}",
             f"mapping id={mapping['id']} kala={kala_code or '-'}")
    _propagate(db, repo, who.actor)
    return repo.mapping_for_key(payload.row_key)


def _propagate(db: OwnDB, repo: PriceListRepo, actor: str,
               reader: AccountingReader | None = None, settings: Settings | None = None) -> int:
    """v2.6.2: a staff decision also decides the other colors / parts of the same
    model in the newest list (flagged «خودکار» for review). v2.8.0: with the
    reader, still-unmapped rows are then matched by product-name similarity."""
    plist = repo.latest_list()
    done = auto_match(repo, plist["id"]) if plist is not None else 0
    if done:
        db.audit(actor, "price_mapping_auto", f"list id={plist['id']} rows={done}")
    if plist is not None:
        done += _name_match(db, repo, reader, settings, plist["id"], actor)
    return done


@router.get("/admin/price-mappings/suggestions")
def mapping_suggestions(
    row_key: str = Query(min_length=1, max_length=400),
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    _: Identity = CAN_VIEW,
) -> dict:
    """v2.8.0: the 3 «سازه حساب» products whose names best match a row (the
    mapping dialog). ``confident`` = the one the matcher would map by itself."""
    repo = PriceListRepo(db)
    row = _row_in_known_lists(repo, row_key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found in the current list")
    candidates = name_candidates(row, phone_product_names(db, reader, settings))
    best = confident(candidates)
    return {"row_key": row_key, "items": candidates[:SUGGESTIONS],
            "confident": best["code"] if best else None}


@router.post("/admin/price-mappings/ignore")
def ignore_rows(
    payload: IgnoreIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """Ignore several rows at once (products this shop does not sell)."""
    repo = PriceListRepo(db)
    done = 0
    for key in dict.fromkeys(payload.row_keys):
        row = _row_in_known_lists(repo, key)
        if row is None:
            continue
        repo.upsert_mapping(
            row_key=key, action="ignore", kala_code=None, color_label="",
            section=row["section"], description=row["description"], kind=row["kind"],
            color=row["color"], actor=who.actor,
        )
        done += 1
    db.audit(who.actor, "price_mapping_ignore", f"rows={done}")
    _propagate(db, repo, who.actor)
    return {"ignored": done}


@router.delete("/admin/price-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(
    mapping_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> None:
    repo = PriceListRepo(db)
    mapping = repo.get_mapping(mapping_id)
    if mapping is None or not repo.delete_mapping(mapping_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mapping not found")
    # The row stays undecided: the matcher must not decide it again by itself.
    repo.reject_auto(mapping["row_key"], who.actor)
    db.audit(who.actor, "price_mapping_delete", f"mapping id={mapping_id}")


@router.post("/admin/price-mappings/{mapping_id}/confirm")
def confirm_mapping(
    mapping_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """Accept an automatic decision (v2.6.2)."""
    repo = PriceListRepo(db)
    if repo.get_mapping(mapping_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mapping not found")
    db.audit(who.actor, "price_mapping_confirm", f"mapping id={mapping_id}")
    return repo.confirm_mapping(mapping_id, who.actor)


@router.post("/admin/price-mappings/auto")
def run_auto_match(
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_PRICELIST,
) -> dict:
    """Match the newest list against every earlier decision now (v2.6.2), then
    by product-name similarity (v2.8.0; confident matches only)."""
    return {"auto_mapped": _propagate(db, PriceListRepo(db), who.actor, reader, settings)}


# ---- inquiries (staff / bot service key) --------------------------------------------
@router.get("/admin/inquiries")
def list_inquiries(
    limit: int = Query(100, ge=1, le=500),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_SEE_INQUIRIES,
) -> list[dict]:
    return PriceListRepo(db).list_inquiries(limit)


@router.get("/admin/inquiries/{inquiry_id}")
def get_inquiry(
    inquiry_id: int,
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_SEE_INQUIRIES,
) -> dict:
    inquiry = PriceListRepo(db).get_inquiry(inquiry_id)
    if inquiry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inquiry not found")
    return inquiry


# ---- proxies (staff) ----------------------------------------------------------------
@router.get("/admin/proxies")
def list_proxies(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_SEE_PROXIES) -> list[dict]:
    return [_proxy_out(p, with_secret=False) for p in ProxyPool(db).list_all()]


@router.post("/admin/proxies", status_code=status.HTTP_201_CREATED)
def add_proxy(
    payload: ProxyIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PROXIES,
) -> dict:
    """Manual entry (also the way out when every stored proxy is dead)."""
    link = parse_proxy_link(payload.link)
    if link is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid proxy link")
    row, created = ProxyPool(db).add(link, "manual", state="main" if payload.main else "probation")
    if not created and payload.main and row["state"] != "main":
        row = ProxyPool(db).set_state(row["id"], "main")
    db.audit(who.actor, "proxy_add", f"proxy id={row['id']}")
    return {**_proxy_out(row, with_secret=False), "created": created}


@router.post("/admin/proxies/collect")
def collect_proxies_now(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_PROXIES) -> dict:
    """v2.9.2 «جمع‌آوری اکنون»: the Telegram reader reads the proxy channels and
    tests the new links at once (it looks for this request every 20 seconds)."""
    ts = now_utc().isoformat(timespec="seconds")
    db.set_state(COLLECT_REQUEST_KEY, ts, who.actor)
    db.audit(who.actor, "proxy_collect_now", "")
    return {"requested_at": ts}


@router.post("/admin/proxies/{proxy_id}/state")
def set_proxy_state(
    proxy_id: int,
    payload: ProxyStateIn,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PROXIES,
) -> dict:
    pool = ProxyPool(db)
    if pool.get(proxy_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proxy not found")
    row = pool.set_state(proxy_id, payload.state)
    db.audit(who.actor, "proxy_state", f"proxy id={proxy_id} state={payload.state}")
    return _proxy_out(row, with_secret=False)


@router.delete("/admin/proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proxy(
    proxy_id: int,
    db: OwnDB = Depends(deps.get_db),
    who: Identity = CAN_PROXIES,
) -> None:
    if not ProxyPool(db).delete(proxy_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proxy not found")
    db.audit(who.actor, "proxy_delete", f"proxy id={proxy_id}")


# ---- worker ---------------------------------------------------------------------------
@router.post("/worker/pricelists", response_model=ImportOut)
def worker_pricelist(
    payload: PdfIn,
    db: OwnDB = Depends(deps.get_db),
    reader: AccountingReader = Depends(deps.get_reader),
    settings: Settings = Depends(deps.get_settings),
    _: str = WORKER,
) -> ImportOut:
    data = _decode_pdf(payload.data_b64, settings)
    result = import_pdf(db, settings, data, source="telegram", source_ref=payload.source_ref,
                        posted_at=payload.posted_at, actor="worker", latest=payload.latest)
    out = _import_out(result)
    if result.list_id:
        out.auto_mapped += _name_match(db, PriceListRepo(db), reader, settings, result.list_id,
                                       "worker")
    return out


@router.post("/worker/pricelist-notes")
def worker_pricelist_note(
    payload: NoteIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    _: str = WORKER,
) -> dict:
    """v2.9.1: a text post after the list: a correction («اصلاحیه») is applied to
    the active list, «فروش بسته» closes phone sales; anything else is ignored."""
    kind = notes.classify(payload.text)
    result = notes.NoteResult(kind=kind)
    active = PriceListRepo(db).active_list()
    result.list_id = int(active["id"]) if active else None
    if kind == notes.KIND_CORRECTION:
        notes.apply_correction(db, settings, payload.text, guard_pct=settings.price_guard_pct,
                               result=result)
        if result.applied or result.held:
            db.audit("worker", "pricelist_correction",
                     f"list id={result.list_id} applied={len(result.applied)} "
                     f"held={len(result.held)} unmatched={len(result.unmatched)}")
            db.add_event("pricelist_corrected", result.list_id, "worker")
        if result.held:
            db.add_event("price_held", result.list_id, "worker")
    elif kind == notes.KIND_CLOSED:
        sales_state.close_by_channel(db, settings, payload.source_ref)
    note_id = notes.store_note(db, kind, list_id=result.list_id, source_ref=payload.source_ref,
                               posted_at=payload.posted_at, text=payload.text,
                               result=result.as_dict())
    result.note_id = note_id
    if result.unmatched:
        db.add_event("price_correction_unmatched", note_id, "worker")
    return result.as_dict()


@router.post("/worker/telegram/channels")
def worker_channels(payload: ChannelsIn, db: OwnDB = Depends(deps.get_db),
                    _: str = WORKER) -> dict:
    """v2.9.1: the channels the account has joined (new ones alert the admin)."""
    out = tgchannels.sync(db, [c.model_dump() for c in payload.channels])
    return {"known": out["known"], "new": len(out["new"])}


@router.get("/worker/telegram/roles")
def worker_channel_roles(db: OwnDB = Depends(deps.get_db), _: str = WORKER) -> dict:
    return {"channels": tgchannels.roles_for_worker(db)}


@router.get("/worker/state")
def worker_get_state(db: OwnDB = Depends(deps.get_db), _: str = WORKER) -> dict:
    return {key: db.get_state(WORKER_STATE_PREFIX + key, "") for key in sorted(WORKER_STATE_KEYS)}


@router.put("/worker/state")
def worker_put_state(
    payload: WorkerStateIn, db: OwnDB = Depends(deps.get_db), _: str = WORKER
) -> dict:
    if payload.key not in WORKER_STATE_KEYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown key")
    db.set_state(WORKER_STATE_PREFIX + payload.key, payload.value, "worker")
    return {"key": payload.key, "value": payload.value}


@router.get("/worker/proxies")
def worker_proxies(db: OwnDB = Depends(deps.get_db), _: str = WORKER) -> list[dict]:
    """Usable proxies, best first, with secrets (the worker connects with them)."""
    return [_proxy_out(p, with_secret=True) for p in ProxyPool(db).ranked()]


@router.post("/worker/proxies/report")
def worker_proxy_report(
    payload: ProxyReportIn, db: OwnDB = Depends(deps.get_db), _: str = WORKER
) -> dict:
    pool = ProxyPool(db)
    recorded = sum(1 for r in payload.results if pool.record(r.id, r.ok, r.latency_ms))
    changes = pool.evaluate()
    for proxy_id, state in changes:
        db.audit("worker", "proxy_auto_state", f"proxy id={proxy_id} state={state}")
    alerted = pool.should_alert_all_dead()
    if alerted:
        db.add_event("proxies_all_dead", None, "worker")
    return {"recorded": recorded, "changes": [list(c) for c in changes], "all_dead": alerted}


@router.post("/worker/proxies/candidates")
def worker_proxy_candidates(
    payload: CandidatesIn, db: OwnDB = Depends(deps.get_db), _: str = WORKER
) -> dict:
    pool = ProxyPool(db)
    added = invalid = skipped = 0
    for raw in payload.links:
        link = parse_proxy_link(raw)
        if link is None:
            invalid += 1
            continue
        _, created = pool.add(link, payload.source)
        added += int(created)
    for item in payload.tested:
        link = parse_proxy_link(item.link)
        if link is None:
            invalid += 1
            continue
        if not pool.known(link) and pool.active_count() >= ACTIVE_CAP:
            skipped += 1
            continue
        row, created = pool.add(link, payload.source)
        if created:
            pool.record(row["id"], True, item.latency_ms)
        added += int(created)
    for raw in payload.failed:
        link = parse_proxy_link(raw)
        if link is None:
            invalid += 1
            continue
        row, created = pool.add(link, payload.source, state="retired")
        if created:
            pool.record(row["id"], False)
    return {"added": added, "invalid": invalid, "skipped": skipped}


@router.post("/worker/proxies/unknown")
def worker_proxy_unknown(
    payload: LinksIn, db: OwnDB = Depends(deps.get_db), _: str = WORKER
) -> dict:
    """v2.9.0: which of these links the server has never seen (worth a test)."""
    pool = ProxyPool(db)
    unknown = []
    for raw in payload.links:
        link = parse_proxy_link(raw)
        if link is not None and not pool.known(link) and raw not in unknown:
            unknown.append(raw)
    return {"unknown": unknown}


@router.post("/worker/alerts")
def worker_alert(
    payload: WorkerAlertIn, db: OwnDB = Depends(deps.get_db), _: str = WORKER
) -> dict:
    if payload.kind not in WORKER_ALERTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown alert")
    sent = _alert_once(db, payload.kind, "worker")
    text = DIRECT_ALERTS.get(payload.kind)
    if sent and text:
        detail = " ".join(payload.detail.split())[:120] or "یکی از بخش‌های سرور"
        try:
            owner_alerts.send_owner_alert(text.replace("{detail}", detail))
        except Exception:  # noqa: BLE001 - the ShopAdmin notification stands
            pass
    return {"sent": sent}

