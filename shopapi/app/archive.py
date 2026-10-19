"""Weekly archive (v2.8.0): every Thursday 23:30 Asia/Tehran, finished orders
(sent, cancelled, rejected, expired) and finished item requests move to
«بایگانی». Nothing is deleted; archived rows are read-only for everyone (changes
to a finished order happen only in «سازه حساب»).

The loop checks every few minutes; a run that was missed (server off on
Thursday night) happens on the next check. The last run is kept in
``shop_state`` so a restart never archives twice for the same week.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

from .db_own import OwnDB
from .sales import TEHRAN

logger = logging.getLogger("shopapi.archive")

#: Thursday (Monday = 0) 23:30 Iran time.
ARCHIVE_WEEKDAY = 3
ARCHIVE_AT = time(23, 30)
STATE_KEY = "archive_last_run"
CHECK_SECONDS = 300
EVENT_ARCHIVED = "archive_done"


def last_due(now: datetime | None = None) -> datetime:
    """The latest Thursday 23:30 (Tehran) at or before ``now`` (UTC-aware)."""
    now = (now or datetime.now(timezone.utc)).astimezone(TEHRAN)
    days_back = (now.weekday() - ARCHIVE_WEEKDAY) % 7
    due = datetime.combine(now.date() - timedelta(days=days_back), ARCHIVE_AT, tzinfo=TEHRAN)
    if due > now:
        due -= timedelta(days=7)
    return due


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def archive_now(db: OwnDB, actor: str, cutoff: str | None = None) -> dict:
    """Archive every finished row changed before ``cutoff`` (default: now)."""
    cutoff = cutoff or _iso_utc(datetime.now(timezone.utc))
    counts = db.archive_closed(cutoff)
    if counts["orders"] or counts["requests"]:
        db.audit(actor, "archive", f"orders={counts['orders']} requests={counts['requests']}")
        db.log_activity(staff_id=None, actor=actor, action="archive", target_type="archive",
                        target_id=None,
                        detail=f"orders={counts['orders']} requests={counts['requests']}")
        db.add_event(EVENT_ARCHIVED, None, actor)
    return counts


def run_due(db: OwnDB, now: datetime | None = None) -> dict | None:
    """Run the weekly archive when this week's Thursday 23:30 has passed and it
    has not run for it yet. Returns the counts, or None when nothing was due."""
    due = last_due(now)
    stamp = _iso_utc(due)
    if db.get_state(STATE_KEY, "") >= stamp:
        return None
    counts = archive_now(db, "system:archive", cutoff=stamp)
    db.set_state(STATE_KEY, stamp, "system:archive")
    return counts


async def archive_loop(db_factory) -> None:
    """Background loop started with the API (never raises)."""
    while True:
        try:
            await asyncio.to_thread(run_due, db_factory())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - try again next round
            logger.warning("archive check failed: %s", type(exc).__name__)
        await asyncio.sleep(CHECK_SECONDS)
