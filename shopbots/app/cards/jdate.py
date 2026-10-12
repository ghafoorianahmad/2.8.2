"""Gregorian -> Shamsi (Jalali) date, dependency free (used on the cards only)."""
from __future__ import annotations

import datetime as _dt


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


def shamsi_date(value=None) -> str:
    """'1405/07/20' for a date/datetime/ISO string (default: today)."""
    if value is None:
        value = _dt.date.today()
    elif isinstance(value, str):
        try:
            value = _dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            value = _dt.date.today()
    elif isinstance(value, _dt.datetime):
        value = value.date()
    jy, jm, jd = to_jalali(value.year, value.month, value.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"
