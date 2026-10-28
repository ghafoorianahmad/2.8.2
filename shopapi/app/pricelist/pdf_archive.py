"""v2.13.0: the archive of every received price-list PDF.

* every file the server receives (from the channel or a manual upload, read or
  rejected) is kept in ``<data>\\pricelists`` as ``1405-08-05-1.pdf``,
  ``1405-08-05-2.pdf``, … - the Tehran (Jalali) date it arrived + a number; the
  same file twice is kept once (the import sees it as a duplicate);
* nothing here is ever deleted automatically;
* the owner is reminded to empty the folder once at the new year (1 Farvardin)
  and once every three months (1 Tir, 1 Mehr, 1 Dey): one event + one Bale
  message per date, never repeated (the date reminded is kept in the own DB).
  The first check after an upgrade only notes the current quarter, so nobody
  gets a reminder for a date that passed before the feature existed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import owner_alerts
from ..config import Settings
from ..db_own import OwnDB
from ..util import now_utc

logger = logging.getLogger("shopapi.pricelist")

#: Iran has no daylight saving time since 2022
TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")
#: Jalali months a reminder is due on (day 1): new year, then every three months
REMINDER_MONTHS = (1, 4, 7, 10)
REMINDER_KEY = "pricelist:archive_reminded"
REMINDER_EVENT = "pricelist_archive_reminder"
CHECK_SECONDS = 3600
_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d+)\.pdf$", re.IGNORECASE)
#: BUILTIN\Users: the archive is only public price lists, so a non-elevated
#: administrator can open it in Explorer on the server («باز کردن پوشه»)
_USERS_SID = "*S-1-5-32-545"
_shared: set[str] = set()


def to_jalali(year: int, month: int, day: int) -> tuple[int, int, int]:
    g_dm = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = year + 1 if month > 2 else year
    days = (355666 + 365 * year + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + day + g_dm[month - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def tehran_jalali(now: datetime | None = None) -> tuple[int, int, int]:
    local = (now or now_utc()).astimezone(TEHRAN)
    return to_jalali(local.year, local.month, local.day)


def archive_name(folder: Path, now: datetime | None = None) -> str:
    """The next free ``YYYY-MM-DD-n.pdf`` (Jalali date in Tehran) in ``folder``."""
    jy, jm, jd = tehran_jalali(now)
    prefix = f"{jy:04d}-{jm:02d}-{jd:02d}-"
    taken = 0
    try:
        for entry in folder.iterdir():
            match = _NAME.match(entry.name)
            if match and entry.name.startswith(prefix):
                taken = max(taken, int(match.group(4)))
    except OSError:
        pass
    return f"{prefix}{taken + 1}.pdf"


def _share_read(folder: Path) -> None:
    """Best effort: let the computer's users read the archive (Explorer on the
    server). Never fails the import; tried once per folder and process."""
    key = str(folder).lower()
    if sys.platform != "win32" or key in _shared:
        return
    _shared.add(key)
    try:
        subprocess.run(["icacls", str(folder), "/grant", f"{_USERS_SID}:(OI)(CI)RX", "/C", "/Q"],
                       capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def store_pdf(settings: Settings, data: bytes, now: datetime | None = None) -> str | None:
    """Keep the received file; returns its name in the archive (None = not kept)."""
    folder = settings.pricelists_path()
    if folder is None:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _share_read(folder)
        for _attempt in range(5):
            name = archive_name(folder, now)
            target = folder / name
            if target.exists():
                continue
            tmp = folder / (name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            return name
    except OSError as exc:  # the archive is a copy: the import itself never fails here
        logger.warning("price list copy not stored: %s", type(exc).__name__)
    return None


def stored_path(settings: Settings, file_name: str | None) -> Path | None:
    """The archived file of a list (only names inside the archive folder)."""
    folder = settings.pricelists_path()
    if folder is None or not file_name:
        return None
    name = Path(str(file_name)).name
    if name != str(file_name) or not name.lower().endswith(".pdf"):
        return None
    return folder / name


def normalize_archive(db: OwnDB, settings: Settings) -> int:
    """v2.14.0: a file of the archive with another name (an older build kept
    ``pricelist_16_unknown.pdf``) gets the standard ``1405-08-05-1.pdf`` name of
    the day it was received (its file time); the list that points at it follows.
    Returns how many were renamed. Never deletes anything."""
    folder = settings.pricelists_path()
    if folder is None or not folder.is_dir():
        return 0
    renamed = 0
    try:
        odd = sorted((e for e in folder.iterdir() if e.is_file() and e.suffix.lower() == ".pdf"
                      and not _NAME.match(e.name)), key=lambda e: e.stat().st_mtime)
    except OSError:
        return 0
    for entry in odd:
        try:
            when = datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
            name = archive_name(folder, when)
            target = folder / name
            if target.exists():
                continue
            os.replace(entry, target)
        except OSError as exc:
            logger.warning("archive file not renamed: %s", type(exc).__name__)
            continue
        with db._lock:
            db._conn.execute("UPDATE price_lists SET file_name=? WHERE file_name=?",
                             (name, entry.name))
            db._commit()
        renamed += 1
    return renamed


def archive_info(settings: Settings) -> dict:
    """For «تنظیمات سرور فروشگاه»: where the archive is, how many files, how big."""
    folder = settings.pricelists_path()
    out = {"path": str(folder) if folder else "", "files": 0, "bytes": 0}
    if folder is None or not folder.is_dir():
        return out
    try:
        for entry in folder.iterdir():
            if entry.is_file() and entry.suffix.lower() == ".pdf":
                out["files"] += 1
                out["bytes"] += entry.stat().st_size
    except OSError:
        pass
    return out


# ---- the «empty the archive» reminder --------------------------------------------------
def current_slot(now: datetime | None = None) -> str:
    """The last reminder date reached: ``1405-07`` (1 Mehr 1405), ``1406-01`` …"""
    jy, jm, _jd = tehran_jalali(now)
    month = max(m for m in REMINDER_MONTHS if m <= jm)
    return f"{jy:04d}-{month:02d}"


def reminder_text(slot: str, info: dict) -> str:
    year, month = slot.split("-")
    when = "سال نو" if month == "01" else "سه‌ماهه"
    size_mb = info.get("bytes", 0) / (1024 * 1024)
    return (f"🗂 یادآوری {when}: پوشهٔ بایگانی لیست‌های قیمت ({info.get('files', 0)} فایل، "
            f"{size_mb:.1f} مگابایت) را در صورت نیاز خالی کنید. هیچ فایلی خودکار پاک نمی‌شود. "
            "نشانی پوشه در «تنظیمات سرور فروشگاه» است.")


def check_reminder(db: OwnDB, settings: Settings, now: datetime | None = None, *,
                   sender=owner_alerts.send_owner_alert) -> bool:
    """One reminder per date; True when one was sent now."""
    slot = current_slot(now)
    last = db.get_state(REMINDER_KEY, "")
    if not last:
        db.set_state(REMINDER_KEY, slot, "system")      # first run: no back-dated reminder
        return False
    if last >= slot:
        return False
    db.set_state(REMINDER_KEY, slot, "system")
    db.add_event(REMINDER_EVENT, None, "system")
    try:
        sender(reminder_text(slot, archive_info(settings)))
    except Exception as exc:  # noqa: BLE001 - the ShopAdmin notification stands
        logger.warning("archive reminder not sent to Bale (%s)", type(exc).__name__)
    return True


async def reminder_loop(settings: Settings, db_factory) -> None:
    """Background loop started with the API (never raises)."""
    while True:
        try:
            db = db_factory()
            await asyncio.to_thread(normalize_archive, db, settings)
            await asyncio.to_thread(check_reminder, db, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("archive reminder check failed: %s", type(exc).__name__)
        await asyncio.sleep(CHECK_SECONDS)
