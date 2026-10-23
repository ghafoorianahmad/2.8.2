"""Channels the shop's Telegram account has joined, and their roles (v2.9.1).

The reader reports the joined channels (``POST /worker/telegram/channels``,
every few hours). A manager picks a role per channel in «تنظیمات سرور ← تلگرام»:

* ``pricelist`` - the phone price list (one channel; choosing another clears it),
* ``proxy``     - MTProto proxies for the pool,
* ``accessories`` / ``used`` - accessories / used phones (placeholders: not read yet),
* ``ignore``    - not read,
* ``""``        - not chosen yet (not read).

The configured channels (TG_PRICE_CHANNEL, @ProxyMTProto) get their role when they
are first seen; a channel joined later raises ``telegram_channel_new`` (ShopAdmin).
Stored as JSON in the state table (``tg_channels``); no message content.
"""
from __future__ import annotations

import json

from .db_own import OwnDB
from .util import now_iso

STATE_KEY = "tg_channels"
ROLE_PRICELIST = "pricelist"
ROLE_PROXY = "proxy"
ROLES = ("", ROLE_PRICELIST, ROLE_PROXY, "accessories", "used", "ignore")
#: the roles the reader acts on today; the others are placeholders
WORKING_ROLES = (ROLE_PRICELIST, ROLE_PROXY)
EVENT_NEW = "telegram_channel_new"
DEFAULT_ROLES = {"abrishamiiphonemashhad": ROLE_PRICELIST, "proxymtproto": ROLE_PROXY}


def load(db: OwnDB) -> list[dict]:
    try:
        value = json.loads(db.get_state(STATE_KEY, "") or "[]")
    except ValueError:
        return []
    return [c for c in value if isinstance(c, dict) and c.get("id") is not None] \
        if isinstance(value, list) else []


def _save(db: OwnDB, channels: list[dict], actor: str) -> None:
    db.set_state(STATE_KEY, json.dumps(channels, ensure_ascii=False), actor)


def ref(channel: dict) -> str:
    return str(channel.get("username") or channel.get("id"))


def sync(db: OwnDB, found: list[dict], *, defaults: dict[str, str] | None = None) -> dict:
    """Merge the reader's list. Returns {"known": n, "new": [ids]}; one
    ``telegram_channel_new`` event per channel joined since the first report."""
    defaults = {k.lower(): v for k, v in (defaults or DEFAULT_ROLES).items()}
    known = {int(c["id"]): c for c in load(db)}
    first_report = not known
    ts = now_iso()
    new_ids: list[int] = []
    present = set()
    for item in found:
        try:
            cid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        present.add(cid)
        username = str(item.get("username") or "")[:64]
        title = str(item.get("title") or "")[:120]
        current = known.get(cid)
        if current is None:
            current = {"id": cid, "role": defaults.get(username.lower(), ""), "first_seen": ts}
            known[cid] = current
            if not first_report:
                new_ids.append(cid)
        current.update(username=username, title=title, broadcast=bool(item.get("broadcast", True)),
                       last_seen=ts)
    for cid, channel in known.items():
        channel["present"] = cid in present
    _save(db, sorted(known.values(), key=lambda c: (not c.get("present"), c.get("title") or "")),
          "worker")
    for cid in new_ids:
        db.add_event(EVENT_NEW, cid, "worker")
    return {"known": len(known), "new": new_ids}


def set_role(db: OwnDB, channel_id: int, role: str, actor: str) -> dict | None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    channels = load(db)
    target = next((c for c in channels if int(c["id"]) == int(channel_id)), None)
    if target is None:
        return None
    if role == ROLE_PRICELIST:
        for other in channels:
            if other is not target and other.get("role") == ROLE_PRICELIST:
                other["role"] = ""
    target["role"] = role
    target["role_by"] = actor
    target["role_at"] = now_iso()
    _save(db, channels, actor)
    db.audit(actor, "telegram_channel_role", f"channel id={channel_id} role={role or '-'}")
    return target


def roles_for_worker(db: OwnDB) -> list[dict]:
    """[{ref, role}] of every known channel (the reader decides with its defaults)."""
    return [{"ref": ref(c), "role": str(c.get("role") or "")} for c in load(db)]
