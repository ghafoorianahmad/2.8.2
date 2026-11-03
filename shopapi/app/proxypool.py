"""MTProto proxy pool (REQUIREMENTS §6): parse links, rank by stability, promote
and retire. Pure policy + our SQLite; the Telegram worker (shoptg) does the
actual checks and reports results here.

Rules:
* a proxy's history is kept per UTC day: a day is *good* when it had at least
  as many successful checks as failures, *bad* when it had only failures;
* rank = tier (main before probation), then "failing right now" last, then a
  stability score (good days + 1) / (checked days + 2) over the last 30 days —
  long proven proxies outrank a new proxy with a few lucky days (§6: stability,
  not freshness);
* probation -> main after PROMOTE_GOOD_DAYS good days with stability >=
  PROMOTE_MIN_STABILITY;
* probation proxies are dropped after PROBATION_DROP_BAD_DAYS bad days in a
  row, main proxies only after RETIRE_BAD_DAYS, and never below MIN_MAIN_KEEP
  main proxies (chicken-and-egg);
* a day on which *no* proxy worked is our own outage (internet down, Telegram
  blocked harder): it never counts against a proxy;
* nothing is deleted automatically: retired proxies stay in the table.

v2.9.3:
* a proxy that answers slower than ``SLOW_MS`` (≈5 s) goes after every faster
  one, and a proxy failing right now after every working one (tier comes next);
* a *collected* proxy that is dead (failing now and no success for
  ``DEAD_AFTER``, or never worked within ``NEW_DEAD_AFTER`` of being added) is
  retired at once while other proxies work (so it is not our own outage); the
  reader then collects again to refill the pool (target ``TG_PROXY_POOL_SIZE``,
  now 10);
* a **manual** proxy is never retired automatically: its status is only shown.

v2.18.0: the list used to fill up with «قطع» rows nobody added: the reader collects links from
the proxy channels, and each one that fails its first test is kept (state ``retired``) so it is
not tested again. Now a collected proxy that has been down for ``DELETE_AFTER`` is deleted (if a
channel still offers it, it gets one fresh test a day at most). Manual ones are never deleted.
"""
from __future__ import annotations

import base64
import binascii
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from .db_own import OwnDB
from .util import now_utc

WINDOW_DAYS = 30
PROMOTE_GOOD_DAYS = 3
PROMOTE_MIN_STABILITY = 0.7
PROBATION_DROP_BAD_DAYS = 3
RETIRE_BAD_DAYS = 5
MIN_MAIN_KEEP = 3
#: All proxies failing for this long -> "all proxies dead" alert (once per ALERT_REPEAT).
ALL_DEAD_AFTER = timedelta(minutes=10)
ALERT_REPEAT = timedelta(hours=6)
ALERT_STATE_KEY = "proxies_dead_alert_at"

#: v2.9.3: slower than this (ms) = ranked after every faster proxy
SLOW_MS = 5000
#: v2.9.3: a collected proxy failing now with no success for this long is retired
DEAD_AFTER = timedelta(hours=3)
#: v2.9.3: a collected proxy that never worked this long after it was added
NEW_DEAD_AFTER = timedelta(hours=1)
#: v2.9.3: "the internet works": some proxy worked this recently
NETWORK_UP_WINDOW = timedelta(minutes=30)
MANUAL_SOURCE = "manual"
#: v2.18.0: a collected proxy down this long is deleted
DELETE_AFTER = timedelta(hours=24)

ACTIVE_STATES = ("main", "probation")
#: v2.9.0: the worker tests new links before adding them; never more usable
#: proxies than this (a busy channel must not grow the pool without end).
ACTIVE_CAP = 30
PROXY_STATES = ("probation", "main", "retired", "disabled")

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9\-.]*[A-Za-z0-9])?$")
_LINK = re.compile(
    r"(?:tg://(?:web)?proxy\?|(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?:web)?proxy/?\?)"
    r"[^\s<>\"')\]]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProxyLink:
    host: str
    port: int
    secret: str          # lowercase hex

    @property
    def kind(self) -> str:
        """'ee' = fake-TLS, 'dd' = randomized padding, 'plain' = classic."""
        if self.secret.startswith("ee"):
            return "ee"
        if self.secret.startswith("dd"):
            return "dd"
        return "plain"

    def as_link(self) -> str:
        return f"tg://proxy?server={self.host}&port={self.port}&secret={self.secret}"


def normalize_secret(raw: str) -> str | None:
    """Hex (any case) or base64/base64url -> lowercase hex; None if invalid."""
    value = (raw or "").strip()
    if not value:
        return None
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
        data = bytes.fromhex(value)
    else:
        padded = value.replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        try:
            data = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            return None
    if len(data) < 16:
        return None
    if data[:1] in (b"\xdd",) and len(data) != 17:
        return None
    if data[:1] not in (b"\xdd", b"\xee") and len(data) != 16:
        return None
    return data.hex()


def parse_proxy_link(text: str) -> ProxyLink | None:
    """``tg://proxy?server=..&port=..&secret=..`` or the t.me/proxy form. v2.9.1:
    also ``t.me/webproxy`` (no port = 443), ``&amp;`` and a host ending with a dot."""
    value = html.unescape(text or "").strip()
    if not value:
        return None
    if value.lower().startswith(("t.me/", "telegram.me/", "www.t.me/", "telegram.dog/")):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() == "tg":
        if parts.netloc.lower() not in ("proxy", "webproxy"):
            return None
    elif parts.scheme.lower() in ("http", "https"):
        if parts.netloc.lower() not in ("t.me", "www.t.me", "telegram.me", "telegram.dog") or \
                parts.path.rstrip("/").lower() not in ("/proxy", "/webproxy"):
            return None
    else:
        return None
    query = parse_qs(parts.query)
    host = unquote((query.get("server") or [""])[0]).strip().rstrip(".")
    port_raw = (query.get("port") or [""])[0].strip() or "443"
    secret = normalize_secret(unquote((query.get("secret") or [""])[0]))
    if not host or not _HOST.match(host) or not port_raw.isdigit() or secret is None:
        return None
    port = int(port_raw)
    if not 0 < port < 65536:
        return None
    return ProxyLink(host.lower(), port, secret)


def extract_proxy_links(text: str) -> list[ProxyLink]:
    """All valid proxy links in a message (channel post), without duplicates."""
    found: list[ProxyLink] = []
    for match in _LINK.finditer(text or ""):
        link = parse_proxy_link(match.group(0).rstrip(".,;"))
        if link is not None and link not in found:
            found.append(link)
    return found


def _day(at: datetime) -> str:
    return at.date().isoformat()


class ProxyPool:
    def __init__(self, db: OwnDB, clock: Callable[[], datetime] = now_utc):
        self.db = db
        self.clock = clock

    # ---- storage ------------------------------------------------------------
    def get(self, proxy_id: int) -> dict | None:
        with self.db._lock:
            return self.db._fetchone("SELECT * FROM proxies WHERE id=?", (int(proxy_id),))

    def known(self, link: ProxyLink) -> bool:
        with self.db._lock:
            return self.db._fetchone(
                "SELECT id FROM proxies WHERE host=? AND port=? AND secret=?",
                (link.host, link.port, link.secret)) is not None

    def active_count(self) -> int:
        with self.db._lock:
            row = self.db._fetchone(
                "SELECT COUNT(*) AS c FROM proxies WHERE state IN ('main','probation')")
            return int(row["c"])

    def add(self, link: ProxyLink, source: str, *, state: str = "probation") -> tuple[dict, bool]:
        """Add a proxy (new ones start on probation; v2.9.0: a link that failed the
        worker's first test is kept as ``retired`` so it is never tested again).
        Returns (row, created)."""
        if state not in ("probation", "main", "retired"):
            raise ValueError("state")
        with self.db._lock:
            existing = self.db._fetchone(
                "SELECT * FROM proxies WHERE host=? AND port=? AND secret=?",
                (link.host, link.port, link.secret),
            )
            if existing is not None:
                return existing, False
            ts = self.clock().isoformat(timespec="seconds")
            cur = self.db._conn.execute(
                "INSERT INTO proxies (host, port, secret, source, state, added_at, promoted_at, "
                "retired_at) VALUES (?,?,?,?,?,?,?,?)",
                (link.host, link.port, link.secret, source[:100], state, ts,
                 ts if state == "main" else None, ts if state == "retired" else None),
            )
            self.db._commit()
            return self.get(cur.lastrowid), True

    def set_state(self, proxy_id: int, state: str) -> dict | None:
        if state not in PROXY_STATES:
            raise ValueError("state")
        with self.db._lock:
            ts = self.clock().isoformat(timespec="seconds")
            self.db._conn.execute(
                "UPDATE proxies SET state=?, "
                "promoted_at=CASE WHEN ?='main' THEN ? ELSE promoted_at END, "
                "retired_at=CASE WHEN ?='retired' THEN ? ELSE retired_at END WHERE id=?",
                (state, state, ts, state, ts, int(proxy_id)),
            )
            self.db._commit()
        return self.get(proxy_id)

    def delete(self, proxy_id: int) -> bool:
        with self.db._lock:
            cur = self.db._conn.execute("DELETE FROM proxies WHERE id=?", (int(proxy_id),))
            self.db._commit()
            return cur.rowcount > 0

    def is_down(self, proxy: dict) -> bool:
        """«قطع»: retired, or failing at its last check."""
        return proxy["state"] == "retired" or bool(proxy.get("failing_now"))

    def delete_many(self, ids) -> int:
        with self.db._lock:
            count = 0
            for proxy_id in ids:
                count += self.db._conn.execute("DELETE FROM proxies WHERE id=?",
                                               (int(proxy_id),)).rowcount
            self.db._commit()
        return count

    def down_ids(self) -> list[int]:
        return [p["id"] for p in self.list_all() if self.is_down(p)]

    def prune_dead(self) -> list[int]:
        """Collected proxies down for ``DELETE_AFTER``: not while the network itself is out
        (a day without any working proxy says nothing about them)."""
        proxies = self.list_all()
        if not self._network_up(proxies):
            return []
        limit = (self.clock() - DELETE_AFTER).isoformat(timespec="seconds")
        gone = [p["id"] for p in proxies
                if p.get("source") != MANUAL_SOURCE and self.is_down(p)
                and str(p.get("added_at") or "") < limit
                and str(p.get("last_ok_at") or "") < limit]
        self.delete_many(gone)
        return gone

    def record(self, proxy_id: int, ok: bool, latency_ms: int | None = None,
               at: datetime | None = None) -> bool:
        """One health-check result. False when the proxy is unknown."""
        at = at or self.clock()
        ts = at.isoformat(timespec="seconds")
        with self.db._lock:
            if self.get(proxy_id) is None:
                return False
            column = "ok" if ok else "fail"
            self.db._conn.execute(
                f"INSERT INTO proxy_days (proxy_id, day, {column}) VALUES (?,?,1) "
                f"ON CONFLICT(proxy_id, day) DO UPDATE SET {column}={column}+1",
                (int(proxy_id), _day(at)),
            )
            if ok:
                self.db._conn.execute(
                    "UPDATE proxies SET last_ok_at=?, last_checked_at=?, last_latency_ms=? "
                    "WHERE id=?",
                    (ts, ts, int(latency_ms) if latency_ms is not None else None, int(proxy_id)),
                )
            else:
                self.db._conn.execute(
                    "UPDATE proxies SET last_fail_at=?, last_checked_at=? WHERE id=?",
                    (ts, ts, int(proxy_id)),
                )
            self.db._commit()
            return True

    # ---- statistics -----------------------------------------------------------
    def _days(self) -> dict[int, dict[str, tuple[int, int]]]:
        since = _day(self.clock() - timedelta(days=WINDOW_DAYS))
        with self.db._lock:
            rows = self.db._fetchall(
                "SELECT proxy_id, day, ok, fail FROM proxy_days WHERE day > ?", (since,)
            )
        out: dict[int, dict[str, tuple[int, int]]] = {}
        for r in rows:
            out.setdefault(int(r["proxy_id"]), {})[r["day"]] = (int(r["ok"]), int(r["fail"]))
        return out

    @staticmethod
    def _network_up_days(days: dict[int, dict[str, tuple[int, int]]]) -> set[str]:
        """Days on which at least one proxy worked (otherwise: our own outage)."""
        return {day for per in days.values() for day, (ok, _) in per.items() if ok > 0}

    @staticmethod
    def _stats(per_day: dict[str, tuple[int, int]], up_days: set[str]) -> dict:
        good = sum(1 for ok, fail in per_day.values() if ok > 0 and ok >= fail)
        checked = sum(1 for ok, fail in per_day.values() if ok + fail > 0)
        # Consecutive bad days, newest first, ignoring our own outage days.
        streak = 0
        for day in sorted(per_day, reverse=True):
            ok, fail = per_day[day]
            if day not in up_days:
                continue
            if ok == 0 and fail > 0:
                streak += 1
            elif ok > 0:
                break
        return {
            "good_days": good,
            "checked_days": checked,
            "bad_streak": streak,
            "stability": (good + 1) / (checked + 2),
        }

    def list_all(self) -> list[dict]:
        """Every proxy with its statistics, ranked (active ones first)."""
        with self.db._lock:
            proxies = self.db._fetchall("SELECT * FROM proxies")
        days = self._days()
        up = self._network_up_days(days)
        for p in proxies:
            p.update(self._stats(days.get(p["id"], {}), up))
            p["failing_now"] = bool(
                p["last_fail_at"] and (not p["last_ok_at"] or p["last_fail_at"] > p["last_ok_at"])
            )
        tier = {"main": 0, "probation": 1, "disabled": 2, "retired": 3}
        for p in proxies:
            latency = p.get("last_latency_ms")
            p["slow"] = bool(latency is not None and int(latency) > SLOW_MS)
        # v2.9.3: usable first; among them working before failing, fast before slow
        # (> SLOW_MS), then main before probation, stability, and the faster one
        proxies.sort(key=lambda p: (
            p["state"] not in ACTIVE_STATES, p["failing_now"], p["slow"],
            tier.get(p["state"], 9), -p["stability"], -p["good_days"],
            int(p.get("last_latency_ms") or 10 ** 6), p["id"],
        ))
        return proxies

    def ranked(self) -> list[dict]:
        """Usable proxies, best first: what the worker tries, in this order."""
        return [p for p in self.list_all() if p["state"] in ACTIVE_STATES]

    # ---- policy ----------------------------------------------------------------
    def _network_up(self, proxies: list[dict]) -> bool:
        """Some proxy worked within NETWORK_UP_WINDOW (else: our own outage)."""
        since = (self.clock() - NETWORK_UP_WINDOW).isoformat(timespec="seconds")
        return any(p.get("last_ok_at") and p["last_ok_at"] >= since for p in proxies)

    def is_dead(self, proxy: dict) -> bool:
        """v2.9.3: a collected proxy that stopped working (see DEAD_AFTER)."""
        if proxy.get("source") == MANUAL_SOURCE or proxy["state"] not in ACTIVE_STATES \
                or not proxy.get("failing_now"):
            return False
        now = self.clock()
        if proxy.get("last_ok_at"):
            return proxy["last_ok_at"] < (now - DEAD_AFTER).isoformat(timespec="seconds")
        return str(proxy.get("added_at") or "") < (now - NEW_DEAD_AFTER).isoformat(
            timespec="seconds")

    def evaluate(self) -> list[tuple[int, str]]:
        """Apply promotion / retirement. Returns [(proxy_id, new_state)].
        v2.9.3: dead collected proxies are retired at once (while the network works);
        manual proxies are never retired automatically."""
        proxies = self.list_all()
        changes: list[tuple[int, str]] = []
        main_count = sum(1 for p in proxies if p["state"] == "main"
                         and p.get("source") != MANUAL_SOURCE)
        dead: set[int] = set()
        if self._network_up(proxies):
            for p in proxies:
                if self.is_dead(p):
                    dead.add(p["id"])
                    changes.append((p["id"], "retired"))
                    if p["state"] == "main":
                        main_count -= 1
        for p in proxies:
            if p["id"] in dead or p.get("source") == MANUAL_SOURCE:
                continue
            if p["state"] == "probation":
                if (p["good_days"] >= PROMOTE_GOOD_DAYS
                        and p["stability"] >= PROMOTE_MIN_STABILITY and p["bad_streak"] == 0):
                    changes.append((p["id"], "main"))
                    main_count += 1
                elif p["bad_streak"] >= PROBATION_DROP_BAD_DAYS:
                    changes.append((p["id"], "retired"))
        # Worst main proxies first, never below MIN_MAIN_KEEP.
        for p in sorted((p for p in proxies if p["state"] == "main" and p["id"] not in dead
                         and p.get("source") != MANUAL_SOURCE),
                        key=lambda p: (-p["bad_streak"], p["stability"])):
            if p["bad_streak"] >= RETIRE_BAD_DAYS and main_count > MIN_MAIN_KEEP:
                changes.append((p["id"], "retired"))
                main_count -= 1
        for proxy_id, state in changes:
            self.set_state(proxy_id, state)
        return changes

    def all_dead(self) -> bool:
        """Every usable proxy is failing and none worked for ALL_DEAD_AFTER."""
        usable = self.ranked()
        if not usable:
            return True
        if not all(p["failing_now"] for p in usable):
            return False
        limit = (self.clock() - ALL_DEAD_AFTER).isoformat(timespec="seconds")
        return all(not p["last_ok_at"] or p["last_ok_at"] < limit for p in usable)

    def should_alert_all_dead(self) -> bool:
        """True at most once per ALERT_REPEAT while all proxies are dead."""
        if not self.all_dead():
            if self.db.get_state(ALERT_STATE_KEY, ""):
                self.db.set_state(ALERT_STATE_KEY, "", "system:proxypool")
            return False
        last = self.db.get_state(ALERT_STATE_KEY, "")
        now = self.clock()
        if last:
            try:
                if now - datetime.fromisoformat(last) < ALERT_REPEAT:
                    return False
            except ValueError:
                pass
        self.db.set_state(ALERT_STATE_KEY, now.isoformat(timespec="seconds"), "system:proxypool")
        return True


def pool_summary(pool: "ProxyPool", target: int | None = None) -> dict:
    """v2.9.0: counts for «سرور فروشگاه» (no hosts, no secrets)."""
    proxies = pool.list_all()
    active = [p for p in proxies if p["state"] in ACTIVE_STATES]
    working = [p for p in active if p.get("last_ok_at") and not p["failing_now"]]
    return {
        "target": target,
        "working": len(working),
        "active": len(active),
        "main": sum(1 for p in active if p["state"] == "main"),
        "probation": sum(1 for p in active if p["state"] == "probation"),
        "manual": sum(1 for p in active if p.get("source") == "manual"),
        # v2.9.3: working, but slower than SLOW_MS (used last)
        "slow": sum(1 for p in working if p.get("slow")),
        "retired": sum(1 for p in proxies if p["state"] == "retired"),
        "disabled": sum(1 for p in proxies if p["state"] == "disabled"),
        "all_failing": bool(active) and not working,
    }


def masked_secret(secret: str) -> str:
    """For staff screens: the kind and the last 4 hex digits only."""
    return f"{secret[:2]}…{secret[-4:]}" if len(secret) > 8 else "…"
