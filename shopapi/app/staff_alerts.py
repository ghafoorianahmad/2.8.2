"""Staff notifications on Bale and Telegram (v2.17.0).

Staff link their chat once by sharing their phone in the bot (the mobile a manager
entered in «کاربران سیستم»). Then:

* during working hours every new unclaimed order, receipt or request goes to all
  linked staff who may see it, again every 5 minutes until someone takes it
  («برداشت», or any first action in ShopAdmin);
* outside working hours nothing is sent; one summary goes out at opening time;
* a manual choice on the dashboard beats the schedule until the next working period:
  «روشن کردن اعلان‌ها», «خاموش کردن اعلان‌ها» and «تعطیلی امروز».

The bots only deliver: they ask ``due`` what to send, per platform, and ``due`` records
it as sent at once, so a failed delivery simply comes again at the next repeat.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

from .db_own import OwnDB
from .sales import TEHRAN, parse_hhmm
from .staff import effective_permissions
from .text import mobile_key
from .util import now_utc

HOURS_KEY = "work_hours"
OVERRIDE_KEY = "staff_alert_override"
SUMMARY_KEY = "staff_alert_summary"       # + ":<platform>" -> the local date it went out

#: Default: 09:00 - 21:00, Saturday to Thursday (Python weekdays; Friday = 4 is off,
#: as phone sales are). All editable in ShopAdmin.
DEFAULT_START = "09:00"
DEFAULT_END = "21:00"
DEFAULT_DAYS = (5, 6, 0, 1, 2, 3)
REPEAT_SECONDS = 300

ACTION_ON = "on"
ACTION_OFF = "off"
ACTION_HOLIDAY = "holiday"
ACTIONS = (ACTION_ON, ACTION_OFF, ACTION_HOLIDAY)

KIND_ORDER = "order"
KIND_RECEIPT = "receipt"
KIND_REQUEST = "request"


@dataclass(frozen=True)
class WorkHours:
    start: str = DEFAULT_START
    end: str = DEFAULT_END
    days: tuple[int, ...] = DEFAULT_DAYS

    def start_time(self) -> time:
        return parse_hhmm(self.start, time(9, 0))

    def end_time(self) -> time:
        return parse_hhmm(self.end, time(21, 0))

    def is_open(self, local: datetime) -> bool:
        if local.weekday() not in self.days:
            return False
        return self.start_time() <= local.time().replace(tzinfo=None) < self.end_time()

    def period_start(self, day: date) -> datetime:
        return datetime.combine(day, self.start_time(), tzinfo=TEHRAN)

    def next_start(self, local: datetime, *, after_today: bool = False) -> datetime | None:
        """The next opening after ``local`` (or after the whole of its day)."""
        first = 1 if after_today else 0
        for offset in range(first, 8):
            day = local.date() + timedelta(days=offset)
            if day.weekday() in self.days and self.period_start(day) > local:
                return self.period_start(day)
        return None

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "days": list(self.days)}


def load_hours(db: OwnDB) -> WorkHours:
    raw = db.get_state(HOURS_KEY, "")
    if not raw:
        return WorkHours()
    try:
        value = json.loads(raw)
        return WorkHours(str(value["start"]), str(value["end"]),
                         tuple(sorted({int(d) for d in value["days"]})))
    except (ValueError, KeyError, TypeError):
        return WorkHours()


def hours_problem(start: str, end: str, days) -> str | None:
    for value in (start, end):
        try:
            hours, minutes = str(value).split(":")
            time(int(hours), int(minutes))
        except (ValueError, TypeError):
            return "Time must look like 09:00"
    if parse_hhmm(start, time(0)) >= parse_hhmm(end, time(0)):
        return "The end must be after the start"
    if any(int(d) not in range(7) for d in days):
        return "Unknown day"
    return None


def save_hours(db: OwnDB, start: str, end: str, days, actor: str) -> WorkHours:
    hours = WorkHours(start, end, tuple(sorted({int(d) for d in days})))
    db.set_state(HOURS_KEY, json.dumps(hours.as_dict()), actor)
    return hours


# ---- on / off ----------------------------------------------------------------------------------
@dataclass
class AlertState:
    active: bool
    in_hours: bool
    #: "" | on | off | holiday: a manual choice that still holds
    override: str = ""
    override_by: str = ""
    #: When the manual choice ends (ISO, UTC), if known.
    until: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _load_override(db: OwnDB, now: datetime) -> dict | None:
    raw = db.get_state(OVERRIDE_KEY, "")
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if value.get("until") and datetime.fromisoformat(value["until"]) <= now:
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    return value


def state(db: OwnDB, now: datetime | None = None) -> AlertState:
    now = now or now_utc()
    in_hours = load_hours(db).is_open(now.astimezone(TEHRAN))
    override = _load_override(db, now)
    if override is None:
        return AlertState(active=in_hours, in_hours=in_hours)
    return AlertState(active=override.get("mode") == ACTION_ON, in_hours=in_hours,
                      override=str(override.get("mode") or ""),
                      override_by=str(override.get("by") or ""), until=override.get("until"))


def apply_action(db: OwnDB, action: str, actor: str, now: datetime | None = None) -> AlertState:
    """The dashboard's buttons. Each holds until the next working period begins;
    «روشن» during working hours just goes back to the schedule (it must not keep
    the repeats going through the night)."""
    now = now or now_utc()
    hours = load_hours(db)
    local = now.astimezone(TEHRAN)
    if action == ACTION_ON and hours.is_open(local):
        db.set_state(OVERRIDE_KEY, "", actor)
        return state(db, now)
    ends = hours.next_start(local, after_today=action == ACTION_HOLIDAY)
    until = ends.astimezone(now.tzinfo).isoformat(timespec="seconds") if ends else None
    db.set_state(OVERRIDE_KEY, json.dumps({"mode": action, "until": until, "by": actor}), actor)
    return state(db, now)


# ---- what is waiting ---------------------------------------------------------------------------
def open_items(db: OwnDB) -> list[dict]:
    """Every unclaimed order / receipt / request: {kind, target_type, target_id, since,
    label, total}. A receipt counts from its arrival, so it is news of its own."""
    items = []
    for row in db.unclaimed_orders():
        receipt = row["status"] == "receipt_uploaded"
        items.append({"kind": KIND_RECEIPT if receipt else KIND_ORDER, "target_type": "order",
                      "target_id": int(row["id"]), "total": float(row.get("total") or 0),
                      "since": row["updated_at"] if receipt else row["created_at"],
                      "label": str(row.get("first_item") or "")})
    for row in db.unclaimed_requests():
        items.append({"kind": KIND_REQUEST, "target_type": "request",
                      "target_id": int(row["id"]), "total": 0.0,
                      "since": row["created_at"],
                      "label": str(row.get("product_name") or row.get("text") or "")[:120]})
    return items


def _recipients(db: OwnDB, platform: str) -> dict[str, set[str]]:
    """{permission: chats} of the staff who get notices on this platform."""
    out: dict[str, set[str]] = {"orders.view": set(), "requests.view": set()}
    for row in db.staff_links_for_platform(platform):
        perms = effective_permissions(row["role"], row.get("perm_grant"), row.get("perm_revoke"))
        if "staff_alerts.view" not in perms:
            continue
        for needed, chats in out.items():
            if needed in perms:
                chats.add(str(row["chat_id"]))
    return out


def _needed(item: dict) -> str:
    return "orders.view" if item["target_type"] == "order" else "requests.view"


def _older(stamp: str | None, cutoff: datetime) -> bool:
    if not stamp:
        return True
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=cutoff.tzinfo)
    return when <= cutoff


def due(db: OwnDB, platform: str, now: datetime | None = None) -> list[dict]:
    """What this platform must send now; recorded as sent. Each entry has ``kind``
    (order / receipt / request / summary), ``chats`` and its details."""
    now = now or now_utc()
    current = state(db, now)
    if not current.active:
        return []
    chats = _recipients(db, platform)
    if not any(chats.values()):
        return []
    items = open_items(db)
    out: list[dict] = []
    hours = load_hours(db)
    local = now.astimezone(TEHRAN)
    summary_key = f"{SUMMARY_KEY}:{platform}"
    today = local.date().isoformat()
    log = db.staff_alert_log(platform)
    stamp = now.isoformat(timespec="seconds")
    if hours.is_open(local) and db.get_state(summary_key, "") != today:
        # opening: what came in while the shop was closed, in one message
        db.set_state(summary_key, today, "system:staff_alerts")
        opening = hours.period_start(local.date())
        waiting = [it for it in items if _older(it["since"], opening.astimezone(now.tzinfo))]
        if waiting:
            counts = {kind: sum(1 for it in waiting if it["kind"] == kind)
                      for kind in (KIND_ORDER, KIND_RECEIPT, KIND_REQUEST)}
            receivers = set()
            for it in waiting:
                receivers |= chats[_needed(it)]
                db.record_staff_alert(it["target_type"], it["target_id"], it["kind"], platform,
                                      stamp)
            out.append({"kind": "summary", "counts": counts, "chats": sorted(receivers)})
            sent = {(it["target_type"], it["target_id"], it["kind"]) for it in waiting}
            items = [it for it in items
                     if (it["target_type"], it["target_id"], it["kind"]) not in sent]
    cutoff = now - timedelta(seconds=REPEAT_SECONDS)
    for it in items:
        last = log.get((it["target_type"], it["target_id"], it["kind"]))
        if last is not None and not _older(last["sent_at"], cutoff):
            continue
        receivers = chats[_needed(it)]
        if not receivers:
            continue
        db.record_staff_alert(it["target_type"], it["target_id"], it["kind"], platform, stamp)
        out.append({**it, "repeat": int(last["count"]) if last else 0,
                    "chats": sorted(receivers)})
    return out


# ---- linking -----------------------------------------------------------------------------------
def clean_mobile(value: str) -> str:
    """09xxxxxxxxx, or "" for an empty value. ValueError: not a mobile number."""
    value = str(value or "").strip()
    if not value:
        return ""
    key = mobile_key(value)
    if key is None:
        raise ValueError("not a mobile number")
    return "0" + key


def link(db: OwnDB, platform: str, chat_id: str, phone: str) -> dict | None:
    """The verified phone of a chat belongs to an active staff member: link them
    (one chat per staff member on each platform). None: not a staff number."""
    key = mobile_key(phone)
    if key is None:
        return None
    staff = db.get_staff_by_mobile("0" + key)
    if staff is None or not staff["active"]:
        return None
    db.set_staff_link(int(staff["id"]), platform, str(chat_id))
    return staff
