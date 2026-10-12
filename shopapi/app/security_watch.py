"""Suspicious-activity alerts (REQUIREMENTS §10).

Every report is written to the audit log. When one source (a chat, an IP
address, a username) repeats the same kind ``threshold`` times within an hour,
the owner gets one Bale message (straight from the server, like the health
alerts) and ShopAdmin one ``security_alert`` event. The same source and kind
alert at most once per hour, and all alerts together at most ``MAX_PER_HOUR``
times, so an attack cannot flood the owner's phone.

Kinds
    contact_not_own  a contact that is not the sender's own (forwarded / someone
                     else's card) offered at registration          - bot
    rate_limited     a chat hit the bot's message rate limit           - bot
    receipt_flood    a chat hit the receipt upload limit                - bot
    order_probe      a chat asked for an order that is not its own      - shopapi
    login_failed     wrong staff passwords from one address             - shopapi
    login_throttled  the login rate limit for one address               - shopapi
    account_locked   a staff account was locked after wrong passwords   - shopapi

Messages carry only the kind, a masked source and a count - no names, phones
or tokens.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

from . import owner_alerts

logger = logging.getLogger(__name__)

WINDOW = 3600.0
ALERT_EVERY = 3600.0
MAX_PER_HOUR = 6
EVENT_KIND = "security_alert"

#: kind -> (reports from one source within WINDOW that raise an alert, Persian text)
KINDS: dict[str, tuple[int, str]] = {
    "contact_not_own": (3, "چند بار شمارهٔ شخص دیگری را برای ثبت‌نام فرستاده است"),
    "rate_limited": (3, "پشت‌سرهم بیش از حد مجاز پیام فرستاده است"),
    "receipt_flood": (2, "بیش از حد مجاز فیش فرستاده است"),
    "order_probe": (5, "چند بار سفارش‌های دیگران را خواسته است"),
    "login_failed": (10, "گذرواژهٔ اشتباه برای ورود به کنسول مدیریت زده است"),
    "login_throttled": (1, "به سقف تلاش ورود به کنسول مدیریت رسیده است"),
    "account_locked": (1, "حساب یک کارمند را با گذرواژهٔ اشتباه قفل کرده است"),
}
BOT_KINDS = frozenset({"contact_not_own", "rate_limited", "receipt_flood"})


def mask(source: str) -> str:
    """Enough to tell sources apart in the audit log, not to identify a person."""
    text = str(source or "?")
    if len(text) <= 4:
        return text
    return "…" + text[-4:]


class SecurityWatch:
    def __init__(self, *, sender: Callable[[str], int] = owner_alerts.send_owner_alert,
                 clock: Callable[[], float] = time.monotonic, background: bool = True) -> None:
        self.sender = sender
        self.clock = clock
        self.background = background
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._alerted: dict[tuple[str, str], float] = {}
        self._recent_alerts: deque[float] = deque()

    def report(self, db, kind: str, source: str, detail: str = "") -> bool:
        """Record one suspicious act; True when it raised an owner alert."""
        if kind not in KINDS:
            return False
        threshold, text = KINDS[kind]
        shown = mask(source)
        try:
            db.audit("security", f"suspicious_{kind}", f"source={shown} {detail}".strip()[:200])
        except Exception as exc:  # noqa: BLE001 - an audit failure must not break the request
            logger.warning("security audit not stored (%s)", type(exc).__name__)
        now = self.clock()
        key = (kind, str(source))
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > WINDOW:
                hits.popleft()
            hits.append(now)
            count = len(hits)
            if count < threshold:
                return False
            last = self._alerted.get(key)
            if last is not None and now - last < ALERT_EVERY:
                return False
            while self._recent_alerts and now - self._recent_alerts[0] > 3600:
                self._recent_alerts.popleft()
            if len(self._recent_alerts) >= MAX_PER_HOUR:
                return False
            self._alerted[key] = now
            self._recent_alerts.append(now)
            self._prune(now)
        logger.warning("suspicious activity: %s from %s (%s in the last hour)", kind, shown, count)
        try:
            db.add_event(EVENT_KIND, None, kind)
        except Exception as exc:  # noqa: BLE001
            logger.warning("security event not stored (%s)", type(exc).__name__)
        message = (f"🛡 هشدار امنیتی: منبع {shown} {text} "
                   f"({count} بار در یک ساعت گذشته). جزئیات در گزارش ممیزی ShopAdmin.")
        if self.background:
            threading.Thread(target=self._send, args=(message,), daemon=True).start()
        else:
            self._send(message)
        return True

    def _send(self, message: str) -> None:
        try:
            self.sender(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("security alert not delivered (%s)", type(exc).__name__)

    def _prune(self, now: float) -> None:
        if len(self._hits) < 5000:
            return
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > WINDOW]:
            self._hits.pop(key, None)


WATCH = SecurityWatch()


def report(db, kind: str, source: str, detail: str = "") -> bool:
    return WATCH.report(db, kind, source, detail)


def reset(watch: Optional[SecurityWatch] = None) -> None:
    """Tests only."""
    global WATCH
    WATCH = watch or SecurityWatch()
