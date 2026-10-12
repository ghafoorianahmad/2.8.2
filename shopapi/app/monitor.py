"""Health monitoring (REQUIREMENTS §8).

Every ``HEALTH_CHECK_SECONDS`` the server checks:

* ``sql``  - the accounting database answers,
* ``bot``  - the Bale bot loop is running (when a Bale token is configured),
* ``bale`` - the bot can reach Bale (it keeps failing to poll),
* ``tg``   - the Telegram worker publishes its status (only once it ever did).

A component is reported **down** after ``HEALTH_FAIL_THRESHOLD`` bad checks in a
row and **up** again on the first good check after that. Each change adds one
event (``health_<check>_down`` / ``health_<check>_up``) for the ShopAdmin tray
and sends one Bale message straight to the owner, so the alert also arrives when
the bot is the thing that is down. Price-list holds and dead proxies are alerted
by their own code paths (events -> bot), not here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import control, owner_alerts
from .util import now_utc

logger = logging.getLogger(__name__)

CHECKS = ("sql", "bot", "bale", "tg")
#: The bot counts as cut off from Bale after this many failed polls in a row
#: and no successful poll for BALE_SILENCE.
BALE_ERRORS = 3
BALE_SILENCE = timedelta(minutes=3)
TG_STATUS_KEY = "worker:tg_status"

TEXTS_DOWN = {
    "sql": "⚠️ هشدار سرور: پایگاه دادهٔ حسابداری (SQL) در دسترس نیست. "
           "سفارش‌ها در صف می‌مانند ولی موجودی و قیمت خوانده نمی‌شود.",
    "bot": "⚠️ هشدار سرور: ربات بله متوقف شده است. سرویس را بررسی کنید.",
    "bale": "⚠️ هشدار سرور: ربات به سرورهای بله وصل نمی‌شود (اینترنت؟).",
    "tg": "⚠️ هشدار سرور: کارگر تلگرام (لیست قیمت/پراکسی) گزارش نمی‌دهد.",
}
TEXTS_UP = {
    "sql": "✅ پایگاه دادهٔ حسابداری دوباره در دسترس است.",
    "bot": "✅ ربات بله دوباره کار می‌کند.",
    "bale": "✅ اتصال ربات به بله برقرار شد.",
    "tg": "✅ کارگر تلگرام دوباره گزارش می‌دهد.",
}


def _parse_time(raw: str | None) -> Optional[datetime]:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class HealthMonitor:
    def __init__(self, settings, db_factory: Callable, reader_factory: Callable, *,
                 sender: Callable[[str], int] = owner_alerts.send_owner_alert,
                 clock: Callable[[], datetime] = now_utc) -> None:
        self.settings = settings
        self.db_factory = db_factory
        self.reader_factory = reader_factory
        self.sender = sender
        self.clock = clock
        self.threshold = max(1, int(getattr(settings, "health_fail_threshold", 2)))
        self.fails: dict[str, int] = {name: 0 for name in CHECKS}
        self.down: dict[str, bool] = {name: False for name in CHECKS}
        self.last: dict[str, Optional[bool]] = {name: None for name in CHECKS}
        self.checked_at: Optional[datetime] = None

    # ---- probes: True = good, False = bad, None = not applicable ------------
    def probe_sql(self) -> Optional[bool]:
        try:
            self.reader_factory().ping()
            return True
        except Exception:  # noqa: BLE001 - any failure = unreachable
            return False

    @staticmethod
    def _bale_health() -> Optional[dict]:
        bots = control.provider_status().get("bots")
        if not isinstance(bots, dict) or "bale" not in (bots.get("configured") or []):
            return None  # plain uvicorn (no launcher) or no Bale token
        return (bots.get("platforms") or {}).get("bale") or {}

    def probe_bot(self) -> Optional[bool]:
        health = self._bale_health()
        if health is None:
            return None
        return bool(health.get("running"))

    def probe_bale(self) -> Optional[bool]:
        health = self._bale_health()
        if not health or not health.get("running"):
            return None  # the bot check covers a stopped bot
        if int(health.get("consecutive_errors") or 0) < BALE_ERRORS:
            return True
        last_ok = _parse_time(health.get("last_ok_at"))
        return last_ok is not None and self.clock() - last_ok < BALE_SILENCE

    def probe_tg(self) -> Optional[bool]:
        raw = self.db_factory().get_state(TG_STATUS_KEY, "")
        if not raw:
            return None  # the worker is not installed (never reported)
        try:
            at = _parse_time(json.loads(raw).get("at"))
        except (ValueError, AttributeError):
            at = None
        if at is None:
            return False
        stale = timedelta(minutes=int(getattr(self.settings, "tg_status_stale_minutes", 20)))
        return self.clock() - at < stale

    # ---- one round ------------------------------------------------------------
    def tick(self) -> list[str]:
        """Run every check once; return the event kinds that were raised."""
        results = {name: getattr(self, f"probe_{name}")() for name in CHECKS}
        self.checked_at = self.clock()
        raised: list[str] = []
        for name, ok in results.items():
            self.last[name] = ok
            if ok is None:
                self.fails[name] = 0
                continue
            if ok:
                self.fails[name] = 0
                if self.down[name]:
                    self.down[name] = False
                    raised.append(self._raise(name, up=True))
                continue
            self.fails[name] += 1
            if not self.down[name] and self.fails[name] >= self.threshold:
                self.down[name] = True
                raised.append(self._raise(name, up=False))
        return raised

    def _raise(self, name: str, *, up: bool) -> str:
        kind = f"health_{name}_{'up' if up else 'down'}"
        if up:
            logger.info("health: %s recovered", name)
        else:
            logger.warning("health: %s is down", name)
        try:
            self.db_factory().add_event(kind, None, "monitor")
        except Exception as exc:  # noqa: BLE001 - the Bale alert still goes out
            logger.warning("health: event not stored (%s)", type(exc).__name__)
        try:
            self.sender((TEXTS_UP if up else TEXTS_DOWN)[name])
        except Exception as exc:  # noqa: BLE001
            logger.warning("health: owner alert failed (%s)", type(exc).__name__)
        return kind

    def snapshot(self) -> dict:
        return {
            "checked_at": self.checked_at.isoformat(timespec="seconds") if self.checked_at else None,
            "checks": {
                name: {"ok": self.last[name], "down": self.down[name], "fails": self.fails[name]}
                for name in CHECKS
            },
        }


#: The running monitor (for the server status page); None until started.
CURRENT: Optional[HealthMonitor] = None


async def health_loop(settings, db_factory, reader_factory) -> None:
    """Background loop started with the API (never raises)."""
    global CURRENT
    interval = int(settings.health_check_seconds)
    if interval <= 0:
        return
    monitor = HealthMonitor(settings, db_factory, reader_factory)
    CURRENT = monitor
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(monitor.tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - tick already guards each step
            logger.warning("health check failed: %s", type(exc).__name__)
