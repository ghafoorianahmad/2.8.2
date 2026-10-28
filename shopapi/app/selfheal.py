"""v2.14.0 «سلامت سیستم»: what the server found, what it fixed by itself, what
needs the owner — one journal (own DB state, newest first, 200 entries).

Routine problems are fixed without asking, and only safe things are done:

* Telegram / Bale connection lost -> the worker / bot reconnect and switch the
  proxy by themselves (already so); here only «دوباره برقرار شد» is written;
* fresh proxies are collected by the worker when the pool runs low (already so);
* a received price list that could not be read is read again, up to
  ``RETRY_TIMES`` times, ``RETRY_MINUTES`` apart;
* a dead worker is restarted by the ShopServer supervisor; its alert is written.

Disk full, a failed backup, SQL down -> one notification with a Persian fix (the
monitor) and an entry «نیاز به شما». Never automatic: writing to accounting,
deleting data, changing prices — those are only reported.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .db_own import OwnDB
from .util import now_iso, now_utc

logger = logging.getLogger(__name__)

JOURNAL_KEY = "health:journal"
RETRY_KEY = "health:pricelist_retries"
MAX_ENTRIES = 200
RETRY_TIMES = 3
RETRY_MINUTES = 30
DISK_MIN_BYTES = 2 * 1024 ** 3
DISK_MIN_SHARE = 0.05

FOUND, FIXED, NEEDS_YOU = "found", "fixed", "needs_you"
LABELS = {"sql": "پایگاه دادهٔ حسابداری (SQL)", "bot": "ربات بله", "bale": "اتصال به بله",
          "tg": "کارگر تلگرام", "backup": "پشتیبان‌گیری", "disk": "فضای دیسک سرور",
          "pricelist": "لیست قیمت"}
FIXES = {
    "sql": "سرویس SQL Server روی رایانهٔ سرور روشن باشد و شبکه وصل؛ اگر رایانه تازه روشن شده، "
           "چند دقیقه صبر کنید.",
    "bot": "سرویس ShopServer را از «سرور فروشگاه» دوباره راه‌اندازی کنید.",
    "bale": "اینترنت رایانهٔ سرور را بررسی کنید؛ ربات خودش دوباره وصل می‌شود.",
    "tg": "خودکار دوباره وصل می‌شود و پراکسی عوض می‌کند؛ اگر طول کشید، «ورود تلگرام» را در "
          "تنظیمات سرور ببینید.",
    "backup": "پوشهٔ پشتیبان (و رایانهٔ مقصد) را در «تنظیمات سرور» بررسی و «آزمایش» کنید.",
    "disk": "پوشهٔ بایگانی لیست‌ها یا پشتیبان‌های قدیمی را به دیسک دیگری ببرید و فضای دیسک "
            "را آزاد کنید.",
    "pricelist": "فایل لیست را باز کنید؛ اگر قالبش عوض شده، لیست را دستی بارگذاری کنید.",
}


def journal(db: OwnDB) -> list[dict]:
    try:
        value = json.loads(db.get_state(JOURNAL_KEY, "") or "[]")
    except ValueError:
        value = []
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def record(db: OwnDB, kind: str, check: str, text_fa: str, *, fix_fa: str = "") -> dict:
    entry = {"at": now_iso(), "kind": kind, "check": check, "label": LABELS.get(check, check),
             "text": text_fa[:400], "fix": (fix_fa or (FIXES.get(check, "") if kind == NEEDS_YOU
                                                     else ""))[:400]}
    entries = [entry] + journal(db)
    db.set_state(JOURNAL_KEY, json.dumps(entries[:MAX_ENTRIES], ensure_ascii=False), "system")
    return entry


# ---- checks -----------------------------------------------------------------------------
def disk_ok(path: Path) -> tuple[bool | None, str]:
    """(ok, Persian detail) of the disk the server keeps its data on."""
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
    except OSError:
        return None, ""
    free_gb = usage.free / 1024 ** 3
    ok = usage.free >= DISK_MIN_BYTES and usage.free >= usage.total * DISK_MIN_SHARE
    return ok, f"{free_gb:.1f} گیگابایت آزاد از {usage.total / 1024 ** 3:.0f}"


# ---- safe repairs ---------------------------------------------------------------------------
def retry_failed_list(db: OwnDB, settings, now: datetime | None = None, *, reread=None) -> str:
    """The newest received price list could not be read: read its kept file again
    (a few times, apart). Returns '', 'fixed', 'retried' or 'gave_up'."""
    from .pricelist.repo import PriceListRepo

    if reread is None:
        from .pricelist.importer import reread_list as reread
    now = now or now_utc()
    lists = PriceListRepo(db).list_lists(1)          # the newest received, whatever its state
    latest = lists[0] if lists else None
    if not latest or latest.get("status") != "failed" or not latest.get("file_name"):
        return ""
    try:
        state = json.loads(db.get_state(RETRY_KEY, "") or "{}")
    except ValueError:
        state = {}
    mine = state.get(str(latest["id"])) or {"times": 0, "at": ""}
    if mine["times"] >= RETRY_TIMES:
        return ""
    if mine["at"]:
        try:
            if now - datetime.fromisoformat(mine["at"]) < timedelta(minutes=RETRY_MINUTES):
                return ""
        except ValueError:
            pass
    mine = {"times": mine["times"] + 1, "at": now.isoformat(timespec="seconds")}
    db.set_state(RETRY_KEY, json.dumps({str(latest["id"]): mine}), "system")
    try:
        result = reread(db, settings, int(latest["id"]), actor="selfheal")
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        logger.warning("self-heal: re-read failed (%s)", type(exc).__name__)
        result = None
    outcome = str(getattr(result, "outcome", "") or "")
    if outcome and outcome != "failed":
        record(db, FIXED, "pricelist", f"لیست قیمت دریافتی که خوانده نشده بود، دوباره خوانده شد "
                                       f"({mine['times']} بار).")
        return "fixed"
    if mine["times"] >= RETRY_TIMES:
        record(db, NEEDS_YOU, "pricelist",
               f"لیست قیمت دریافتی پس از {RETRY_TIMES} بار خواندن دوباره هم خوانده نشد.")
        return "gave_up"
    return "retried"


WORKER_FIXED = {"worker_restarted": "کارگر تلگرام از کار افتاده بود و خودکار دوباره راه‌اندازی شد.",
                "worker_back": "کارگر تلگرام دوباره کار می‌کند."}


def worker_alert(db: OwnDB, kind: str) -> None:
    """An alert the worker sent: a restart it did by itself is «خودکار برطرف شد»."""
    if kind in WORKER_FIXED:
        record(db, FIXED, "tg", WORKER_FIXED[kind])
    else:
        record(db, FOUND, "tg", f"کارگر تلگرام گزارش داد: {kind}")
