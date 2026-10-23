"""Import a price-list PDF with the REQUIREMENTS §5 safety rules.

* the same file twice -> ``duplicate`` (nothing changes);
* not newer than the active list -> stored as ``superseded`` (``older``);
* unreadable / layout changed -> stored as ``failed``; the last good prices stay;
* most mapped rows missing -> ``held``: the last good prices stay until staff
  approve the list;
* otherwise the list becomes ``active``. v2.9.1 price guard: a mapped row whose
  price moves more than PRICE_GUARD_PCT (10 %) keeps its previous price; the new
  one waits for a manager (``pending_*``, event ``price_held``) - per row, the
  rest of the list applies at once;
* v2.9.1: ``latest`` (the reader's newest list post that still exists): a file
  seen before becomes the active list again when the newer post was deleted;
  every imported list teaches each model's «روال − نقد» difference (``notes``).

Every outcome except ``duplicate`` adds an event (``pricelist_imported``,
``pricelist_held``, ``pricelist_failed``); the bot turns held/failed into a
Bale alert to the owner.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..config import Settings
from ..db_own import OwnDB
from ..util import now_utc
from .matching import auto_match, smart_key
from .notes import learn_diffs
from .parser import ParseError, parse_pdf
from .pricing import change_pct, customer_price_rial
from .repo import PriceListRepo

logger = logging.getLogger("shopapi.pricelist")

#: Hold when more than half of the mapped rows (at least this many) vanish.
MIN_MAPPED_FOR_MISSING_CHECK = 4


@dataclass
class ImportResult:
    outcome: str                  # active | held | failed | duplicate | older
    list_id: int | None = None
    list_date: str = ""
    row_count: int = 0
    reasons: list[str] = field(default_factory=list)
    #: v2.6.2: rows decided automatically from earlier decisions
    auto_mapped: int = 0
    #: v2.9.1: rows whose new price waits for a manager (price guard)
    held_rows: int = 0


def _store_pdf(settings: Settings, list_id: int, list_date: str, data: bytes) -> str | None:
    folder = settings.pricelists_path()
    if folder is None:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = f"pricelist_{list_id}_{(list_date or 'unknown').replace('/', '-')}.pdf"
        tmp = folder / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, folder / name)
        return name
    except OSError as exc:  # a copy is for diagnosis only; never fail the import
        logger.warning("price list copy not stored: %s", type(exc).__name__)
        return None


def _is_older(list_date: str, posted_at: str | None, active: dict) -> bool:
    if list_date < (active.get("list_date") or ""):
        return True
    if list_date == active.get("list_date"):
        # Several lists a day: the later Telegram post wins. Manual uploads
        # (no post time) of the same date count as newer.
        if posted_at and active.get("posted_at") and posted_at <= active["posted_at"]:
            return True
    return False


def big_changes(repo: PriceListRepo, active: dict | None, new_rows: dict[str, dict],
                guard_pct: float) -> list[tuple[dict, dict, float]]:
    """v2.9.1: (old row, new row, %) of the mapped rows whose price moves more than
    ``guard_pct`` - those keep the old price until a manager approves."""
    if active is None:
        return []
    old_rows = repo.rows_by_key(active["id"])
    mapped = repo.mapped_keys()
    by_smart = {smart_key(r["section"], r["description"], r["kind"], r["color"]): r
                for r in new_rows.values()}
    out = []
    for key in sorted(mapped & set(old_rows)):
        old = old_rows[key]
        new = new_rows.get(key) or by_smart.get(
            smart_key(old["section"], old["description"], old["kind"], old["color"]))
        if new is None:
            continue
        pct = change_pct(old["price_rial"], new["price_rial"])
        if pct is not None and pct > guard_pct:
            out.append((old, new, pct))
    return out


def safety_reasons(repo: PriceListRepo, active: dict | None, new_rows: dict[str, dict],
                   max_change_pct: float | None = None) -> list[str]:
    """Why the whole list must be held for review (empty = safe). v2.9.1: only a
    changed layout (most mapped rows missing); big price changes are held per row
    (``big_changes``). ``max_change_pct`` (None = off) keeps the old whole-list rule."""
    if active is None:
        return []
    old_rows = repo.rows_by_key(active["id"])
    mapped = repo.mapped_keys() & set(old_rows)
    reasons: list[str] = []
    missing = 0
    # v2.6.2: a row whose spelling changed a little (case, spacing, word order)
    # is the same row, not a missing one.
    by_smart = {smart_key(r["section"], r["description"], r["kind"], r["color"]): r
                for r in new_rows.values()}
    for key in sorted(mapped):
        old = old_rows[key]
        new = new_rows.get(key) or by_smart.get(
            smart_key(old["section"], old["description"], old["kind"], old["color"]))
        if new is None:
            missing += 1
            continue
        pct = change_pct(old["price_rial"], new["price_rial"])
        if max_change_pct is not None and pct is not None and pct > max_change_pct:
            reasons.append(
                f"{old['description']} {old['color']}: {old['price_rial']:,} -> "
                f"{new['price_rial']:,} ({pct:.0f}%)"
            )
    if len(mapped) >= MIN_MAPPED_FOR_MISSING_CHECK and missing * 2 > len(mapped):
        reasons.append(f"{missing} of {len(mapped)} mapped rows are missing "
                       "(layout or naming changed?)")
    return reasons


def import_pdf(
    db: OwnDB,
    settings: Settings,
    data: bytes,
    *,
    source: str,
    source_ref: str = "",
    posted_at: str | None = None,
    actor: str = "",
    latest: bool = False,
) -> ImportResult:
    repo = PriceListRepo(db)
    sha = hashlib.sha256(data).hexdigest()
    existing = repo.get_by_sha(sha)
    if existing is not None:
        if latest and _reactivate(db, repo, existing, actor or source):
            return ImportResult("active", existing["id"], existing["list_date"],
                                existing["row_count"], ["the newer list post was removed"])
        return ImportResult("duplicate", existing["id"], existing["list_date"],
                            existing["row_count"])

    try:
        parsed = parse_pdf(data)
    except ParseError as exc:
        reason = f"parse failed: {exc}"
        list_id = repo.insert_list(
            list_date="", sha256=sha, source=source, source_ref=source_ref,
            posted_at=posted_at, status="failed", reason=reason, rows=[],
        )
        name = _store_pdf(settings, list_id, "", data)
        if name:
            repo.set_file_name(list_id, name)
        db.audit(actor or source, "pricelist_failed", f"list id={list_id}")
        db.add_event("pricelist_failed", list_id, actor or source)
        return ImportResult("failed", list_id, reasons=[reason])

    rows = [
        {
            "row_key": r.key, "block": r.block, "section": r.section,
            "description": r.description, "kind": r.kind, "color": r.color,
            "naghd": r.naghd, "raval": r.raval,
            "price_rial": customer_price_rial(
                r.naghd, r.raval, unit_rial=settings.pricelist_unit_rial,
                cash_surcharge_rial=settings.pricelist_cash_surcharge_rial,
            ),
        }
        for r in parsed.rows
    ]
    active = repo.active_list()
    if active is not None and _is_older(parsed.list_date, posted_at, active):
        list_id = repo.insert_list(
            list_date=parsed.list_date, sha256=sha, source=source, source_ref=source_ref,
            posted_at=posted_at, status="superseded", reason="older than the active list",
            rows=rows,
        )
        return ImportResult("older", list_id, parsed.list_date, len(rows))

    by_key = {r["row_key"]: r for r in rows}
    reasons = safety_reasons(repo, active, by_key)
    guarded = [] if reasons else big_changes(repo, active, by_key, settings.price_guard_pct)
    status_value = "held" if reasons else "active"
    list_id = repo.insert_list(
        list_date=parsed.list_date, sha256=sha, source=source, source_ref=source_ref,
        posted_at=posted_at, status=status_value,
        reason="; ".join(reasons)[:2000], rows=rows,
    )
    name = _store_pdf(settings, list_id, parsed.list_date, data)
    if name:
        repo.set_file_name(list_id, name)
    auto = auto_match(repo, list_id)
    if auto:
        db.audit(actor or source, "price_mapping_auto", f"list id={list_id} rows={auto}")
    if status_value == "active":
        for old, new, _pct in guarded:
            hold_new_row(db, list_id, old, new)
        learn_diffs(db, list_id, rows)
        repo.activate(list_id)
        db.audit(actor or source, "pricelist_import", f"list id={list_id} date={parsed.list_date}")
        db.add_event("pricelist_imported", list_id, actor or source)
        if guarded:
            db.audit(actor or source, "price_held", f"list id={list_id} rows={len(guarded)}")
            db.add_event("price_held", list_id, actor or source)
    else:
        db.audit(actor or source, "pricelist_held", f"list id={list_id} date={parsed.list_date}")
        db.add_event("pricelist_held", list_id, actor or source)
    result = ImportResult(status_value, list_id, parsed.list_date, len(rows), reasons, auto)
    result.held_rows = len(guarded)
    return result


def _reactivate(db: OwnDB, repo: PriceListRepo, existing: dict, actor: str) -> bool:
    """The channel's newest list post was deleted: the newest one that is left (a
    file seen before) is the list again - only over another channel list (never
    over a manual upload, a held or a rejected list)."""
    active = repo.active_list()
    if active is None or int(active["id"]) == int(existing["id"]):
        return False
    if existing["status"] != "superseded" or active.get("source") != "telegram" \
            or existing.get("source") != "telegram" or not existing.get("row_count"):
        return False
    repo.activate(existing["id"], actor)
    db.audit(actor, "pricelist_reactivated", f"list id={existing['id']} (newer post removed)")
    db.add_event("pricelist_imported", existing["id"], actor)
    return True


def hold_new_row(db: OwnDB, list_id: int, old: dict, new: dict) -> None:
    """Price guard on a new list: the row keeps selling at the previous price; the
    list's price waits for a manager."""
    with db._lock:
        db._conn.execute(
            "UPDATE price_list_rows SET orig_naghd=naghd, orig_raval=raval, "
            "orig_price_rial=price_rial, pending_naghd=naghd, pending_raval=raval, "
            "pending_price_rial=price_rial, pending_estimated=0, pending_source='list', "
            "naghd=?, raval=?, price_rial=?, price_flag='held', flag_note='', "
            "raval_estimated=? WHERE list_id=? AND row_key=?",
            (old.get("naghd"), old.get("raval"), old.get("price_rial"),
             int(bool(old.get("raval_estimated"))), int(list_id), new["row_key"]))
        db._commit()


def active_list_fresh(active: dict | None, settings: Settings) -> bool:
    """Phone prices from a list activated too long ago are not sold."""
    if active is None:
        return False
    if settings.pricelist_max_age_hours <= 0:
        return True
    try:
        activated = datetime.fromisoformat(active.get("activated_at") or "")
    except ValueError:
        return False
    return now_utc() - activated <= timedelta(hours=settings.pricelist_max_age_hours)
