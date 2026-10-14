"""Sales windows (decision 2026-10-14).

Sales follow the distributor's price list, in Iran time (Asia/Tehran):

* a list posted before ``SALES_MORNING_CLOSE`` (13:30) is the morning list:
  sales are open until 13:30 of that day;
* a list posted before ``SALES_EVENING_CLOSE`` (20:30) is the evening list:
  sales are open until 20:30 of that day;
* otherwise (no list today, the window has passed, a list posted after 20:30,
  Friday) sales are closed. The bot then shows the last prices with
  «لیست به‌روز نشده، فروش بسته است» and refuses orders.

Staff can override in ShopAdmin (stored here, audited, an event each):

* ``holiday``: closed until the next morning (00:00 of the next day);
* ``close``:   closed now, until a new list arrives or someone opens again;
* ``open``:    open now, until the next transition — a new list or the next
  closing time (13:30 / 20:30) — and can be closed again at any time.

The state is computed on every request from the active list and the override,
so nothing goes stale when the server restarts.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo

from .config import Settings
from .db_own import OwnDB
from .pricelist.repo import PriceListRepo
from .util import now_utc

OVERRIDE_KEY = "sales_override"
#: Last state seen by the background loop (for sales_opened / sales_closed events).
LAST_STATE_KEY = "sales_last_open"

MODES = ("holiday", "close", "open")

REASON_LIST = "list"              # open: today's list, inside its window
REASON_MANUAL_OPEN = "manual_open"
REASON_MANUAL_CLOSE = "manual_close"
REASON_HOLIDAY = "holiday"
REASON_WEEKDAY = "weekday_closed"  # Friday
REASON_NO_LIST = "no_list"
REASON_LIST_EXPIRED = "list_not_updated"  # window passed / no list today / list too late
REASON_DISABLED = "windows_disabled"      # SALES_WINDOWS_ENABLED=false: open unless closed

MESSAGES_FA = {
    REASON_LIST: "فروش باز است.",
    REASON_MANUAL_OPEN: "فروش به‌صورت دستی باز شده است.",
    REASON_MANUAL_CLOSE: "فروش به‌صورت دستی بسته شده است.",
    REASON_HOLIDAY: "امروز تعطیل است؛ فروش تا صبح فردا بسته است.",
    REASON_WEEKDAY: "جمعه‌ها فروش بسته است.",
    REASON_NO_LIST: "هنوز لیست قیمتی دریافت نشده؛ فروش بسته است.",
    REASON_LIST_EXPIRED: "لیست قیمت به‌روز نشده است؛ فروش بسته است.",
    REASON_DISABLED: "فروش باز است.",
}


def tehran_tz() -> tzinfo:
    """Asia/Tehran. Windows has no tz database without the ``tzdata`` package;
    Iran has had no daylight saving time since 2022, so UTC+03:30 is exact."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Tehran")
    except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError, missing module
        return timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")


TEHRAN = tehran_tz()


def parse_hhmm(value: str, default: time) -> time:
    try:
        hours, minutes = str(value).strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return default


@dataclass
class SalesState:
    open: bool
    reason: str
    message_fa: str
    #: When this state ends by itself (ISO, UTC), if known.
    until: str | None = None
    list_id: int | None = None
    list_date: str = ""
    #: "morning" / "evening" / "" for the active list.
    list_slot: str = ""
    override: str | None = None
    override_by: str = ""
    override_at: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if value else None


def _closes(settings: Settings) -> tuple[time, time]:
    morning = parse_hhmm(settings.sales_morning_close, time(13, 30))
    evening = parse_hhmm(settings.sales_evening_close, time(20, 30))
    if evening <= morning:
        evening = time(23, 59)
    return morning, evening


def _at(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=TEHRAN)


def list_time(plist: dict | None) -> datetime | None:
    """When a list was published: the Telegram post time, else its activation."""
    if not plist:
        return None
    return _parse_dt(plist.get("posted_at")) or _parse_dt(plist.get("activated_at")) \
        or _parse_dt(plist.get("created_at"))


def list_window(plist: dict | None, settings: Settings) -> tuple[str, datetime] | None:
    """("morning"|"evening", closing time) of a list, or None (posted too late)."""
    published = list_time(plist)
    if published is None:
        return None
    local = published.astimezone(TEHRAN)
    morning, evening = _closes(settings)
    if local.time() < morning:
        return "morning", _at(local.date(), morning)
    if local.time() < evening:
        return "evening", _at(local.date(), evening)
    return None


def next_closing(settings: Settings, now: datetime) -> datetime:
    """The next 13:30 / 20:30 after ``now`` (tomorrow's morning close at night)."""
    local = now.astimezone(TEHRAN)
    morning, evening = _closes(settings)
    for at in (morning, evening):
        candidate = _at(local.date(), at)
        if candidate > local:
            return candidate
    return _at(local.date() + timedelta(days=1), morning)


def next_morning(now: datetime) -> datetime:
    local = now.astimezone(TEHRAN)
    return _at(local.date() + timedelta(days=1), time(0, 0))


def load_override(db: OwnDB) -> dict | None:
    raw = db.get_state(OVERRIDE_KEY, "")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("mode") in MODES else None


def _override_live(override: dict, active_id: int | None, now: datetime) -> bool:
    until = _parse_dt(override.get("until"))
    if until is not None and now >= until:
        return False
    if override["mode"] in ("close", "open"):
        # A new list is a transition: the override ends with it.
        return override.get("list_id") == active_id
    return True


def compute(db: OwnDB, settings: Settings, now: datetime | None = None) -> SalesState:
    now = now or now_utc()
    active = PriceListRepo(db).active_list()
    active_id = int(active["id"]) if active else None
    window = list_window(active, settings) if active else None
    base = {
        "list_id": active_id,
        "list_date": (active or {}).get("list_date") or "",
        "list_slot": window[0] if window else "",
    }

    override = load_override(db)
    if override is not None and _override_live(override, active_id, now):
        extra = {"override": override["mode"], "override_by": override.get("by") or "",
                 "override_at": override.get("at")}
        mode = override["mode"]
        if mode == "open":
            return SalesState(True, REASON_MANUAL_OPEN, MESSAGES_FA[REASON_MANUAL_OPEN],
                              until=override.get("until"), **base, **extra)
        reason = REASON_HOLIDAY if mode == "holiday" else REASON_MANUAL_CLOSE
        return SalesState(False, reason, MESSAGES_FA[reason],
                          until=override.get("until"), **base, **extra)

    if not settings.sales_windows_enabled:
        return SalesState(True, REASON_DISABLED, MESSAGES_FA[REASON_DISABLED], **base)

    local = now.astimezone(TEHRAN)
    if local.weekday() in settings.sales_closed_weekdays:
        return SalesState(False, REASON_WEEKDAY, MESSAGES_FA[REASON_WEEKDAY], **base)
    if active is None:
        return SalesState(False, REASON_NO_LIST, MESSAGES_FA[REASON_NO_LIST], **base)
    if window is None or window[1].date() != local.date() or now >= window[1]:
        return SalesState(False, REASON_LIST_EXPIRED, MESSAGES_FA[REASON_LIST_EXPIRED], **base)
    return SalesState(True, REASON_LIST, MESSAGES_FA[REASON_LIST], until=_iso(window[1]), **base)


def set_override(db: OwnDB, settings: Settings, mode: str, actor: str,
                 now: datetime | None = None) -> SalesState:
    """Store a staff decision (audited, one event) and return the new state."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    now = now or now_utc()
    active = PriceListRepo(db).active_list()
    until: datetime | None = None
    if mode == "holiday":
        until = next_morning(now)
    elif mode == "open":
        until = next_closing(settings, now)
    record = {
        "mode": mode, "until": _iso(until), "by": actor, "at": _iso(now),
        "list_id": int(active["id"]) if active else None,
    }
    db.set_state(OVERRIDE_KEY, json.dumps(record), actor)
    db.audit(actor, f"sales_{mode}", f"until={record['until'] or '-'} list={record['list_id']}")
    db.add_event({"holiday": "sales_holiday", "close": "sales_closed_manual",
                  "open": "sales_opened_manual"}[mode], None, actor)
    state = compute(db, settings, now)
    db.set_state(LAST_STATE_KEY, "1" if state.open else "0", actor)
    return state


def record_transition(db: OwnDB, settings: Settings, now: datetime | None = None) -> SalesState:
    """Background check: add ``sales_opened`` / ``sales_closed`` once when the
    state flips by itself (a new list, a closing time, Friday)."""
    state = compute(db, settings, now)
    last = db.get_state(LAST_STATE_KEY, "")
    current = "1" if state.open else "0"
    if last != current:
        db.set_state(LAST_STATE_KEY, current, "system:sales")
        if last:   # the first run only records the position
            db.add_event("sales_opened" if state.open else "sales_closed", state.list_id,
                         "system:sales")
    return state
