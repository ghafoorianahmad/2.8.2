"""Import a price-list PDF with the REQUIREMENTS §5 safety rules.

* the same file twice -> ``duplicate`` (nothing changes);
* not newer than the active list -> stored as ``superseded`` (``older``);
* unreadable / layout changed -> stored as ``failed``; the last good prices stay;
* a mapped price moving more than PRICELIST_MAX_CHANGE_PCT, or most mapped rows
  missing -> ``held``: the last good prices stay until staff approve the list;
* otherwise the list becomes ``active``.

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


def safety_reasons(repo: PriceListRepo, active: dict | None, new_rows: dict[str, dict],
                   max_change_pct: float) -> list[str]:
    """Why the new rows must be held for review (empty = safe)."""
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
        if pct is not None and pct > max_change_pct:
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
) -> ImportResult:
    repo = PriceListRepo(db)
    sha = hashlib.sha256(data).hexdigest()
    existing = repo.get_by_sha(sha)
    if existing is not None:
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

    reasons = safety_reasons(
        repo, active, {r["row_key"]: r for r in rows}, settings.pricelist_max_change_pct
    )
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
        repo.activate(list_id)
        db.audit(actor or source, "pricelist_import", f"list id={list_id} date={parsed.list_date}")
        db.add_event("pricelist_imported", list_id, actor or source)
    else:
        db.audit(actor or source, "pricelist_held", f"list id={list_id} date={parsed.list_date}")
        db.add_event("pricelist_held", list_id, actor or source)
    return ImportResult(status_value, list_id, parsed.list_date, len(rows), reasons, auto)


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
