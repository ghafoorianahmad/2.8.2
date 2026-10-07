"""Persian text, Persian digits and Shamsi (Jalali) date handling.

The whole UI goes through these helpers so that no English digit or Gregorian
date can leak into a visible string.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ENGLISH_DIGITS = "0123456789"

_DIGIT_TRANS = str.maketrans(ENGLISH_DIGITS, PERSIAN_DIGITS)
_TO_ENGLISH = str.maketrans(
    {
        **{p: e for p, e in zip(PERSIAN_DIGITS, ENGLISH_DIGITS)},
        # Arabic-Indic digits too, so pasted input still parses.
        **{chr(0x0660 + i): str(i) for i in range(10)},
    }
)
# Arabic yeh/kaf -> Persian yeh/kaf, for search and comparison.
_ARABIC_TRANS = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "آ"})

PERSIAN_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
PERSIAN_WEEKDAYS = (
    "شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه",
)


# --------------------------------------------------------------------------
# digits
# --------------------------------------------------------------------------
def to_persian_digits(value: object) -> str:
    """Convert every ASCII digit in ``value`` to a Persian digit."""
    return str(value).translate(_DIGIT_TRANS)


def to_english_digits(value: object) -> str:
    """Convert Persian/Arabic digits back to ASCII (for parsing user input)."""
    return str(value).translate(_TO_ENGLISH)


#: Unicode bidi isolates: keep a run of digits/symbols left-to-right inside RTL text.
LRI = "⁦"   # left-to-right isolate
PDI = "⁩"   # pop directional isolate


def isolate_ltr(text: object) -> str:
    """Wrap ``text`` so digits, ``+``, ``*`` or ``/`` never get reordered in an RTL cell."""
    value = str(text)
    if not value or value == "—":
        return value
    return f"{LRI}{value}{PDI}"


def format_phone(value: object) -> str:
    """Phone/code with Persian digits, shown left-to-right even inside RTL text."""
    text = str(value or "").strip()
    return isolate_ltr(to_persian_digits(text)) if text else "—"


def normalize_fa(text: object) -> str:
    """Normalize Persian text for searching/comparison (letters + digits)."""
    return to_english_digits(text).translate(_ARABIC_TRANS).strip()


def format_int(value: object) -> str:
    """``1234567`` -> ``۱٬۲۳۴٬۵۶۷`` (Persian digits, thousands separator)."""
    try:
        number = int(round(float(to_english_digits(value))))
    except (TypeError, ValueError):
        return to_persian_digits(value)
    return to_persian_digits(f"{number:,}").replace(",", "٬")


def format_qty(value: object) -> str:
    """Quantities: drop a pointless ``.0`` and use the Persian decimal mark."""
    try:
        number = float(to_english_digits(value))
    except (TypeError, ValueError):
        return to_persian_digits(value)
    if number == int(number):
        return format_int(int(number))
    text = f"{number:,}".rstrip("0").rstrip(".")
    return to_persian_digits(text).replace(",", "٬").replace(".", "٫")


def format_money(value: object, with_unit: bool = True) -> str:
    """Amount in تومان, Persian digits."""
    text = format_int(value)
    return f"{text} تومان" if with_unit else text


def format_percent(value: float, digits: int = 0) -> str:
    return to_persian_digits(f"{value:.{digits}f}") + "٪"


# --------------------------------------------------------------------------
# Shamsi (Jalali) calendar
# --------------------------------------------------------------------------
def gregorian_to_jalali(g_y: int, g_m: int, g_d: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to the Jalali (Shamsi) calendar.

    Dependency-free implementation of the well-known algorithm; accurate for
    the whole range this application can ever display.
    """
    gy = g_y - 1600
    gm = g_m - 1
    gd = g_d - 1

    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for i in range(gm):
        g_day_no += (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[i]
    if gm > 1 and ((g_y % 4 == 0 and g_y % 100 != 0) or g_y % 400 == 0):
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    month_lengths = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)
    for i in range(11):
        if j_day_no < month_lengths[i]:
            jm = i
            break
        j_day_no -= month_lengths[i]
    else:
        jm = 11
    return jy, jm + 1, j_day_no + 1


def jalali_to_gregorian(j_y: int, j_m: int, j_d: int) -> tuple[int, int, int]:
    """Inverse of :func:`gregorian_to_jalali`."""
    jy = j_y - 979
    jm = j_m - 1
    jd = j_d - 1

    j_day_no = 365 * jy + (jy // 33) * 8 + (jy % 33 + 3) // 4
    for i in range(jm):
        j_day_no += (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)[i]
    j_day_no += jd

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097
    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False
    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    month_lengths = [31, 28 + (1 if leap else 0), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for i, length in enumerate(month_lengths):
        if g_day_no < length:
            gm = i
            break
        g_day_no -= length
    else:
        gm = 11
    return gy, gm + 1, g_day_no + 1


def today_shamsi() -> date:
    return date(*gregorian_to_jalali(*date.today().timetuple()[:3]))


def shamsi_to_date(jy: int, jm: int, jd: int) -> date:
    return date(*jalali_to_gregorian(jy, jm, jd))


def format_shamsi(value: object, with_weekday: bool = False) -> str:
    """Format a date/datetime (Gregorian input) as a Shamsi string.

    ``value`` may be a ``date``, ``datetime``, an ISO-8601 string (as returned
    by shopapi) or ``None``. ISO strings are treated as UTC and converted to
    local time before the calendar conversion.
    """
    moment = coerce_datetime(value)
    if moment is None:
        return "—"
    jy, jm, jd = gregorian_to_jalali(moment.year, moment.month, moment.day)
    text = f"{to_persian_digits(jy)}/{to_persian_digits(f'{jm:02d}')}/{to_persian_digits(f'{jd:02d}')}"
    if with_weekday:
        # Python: Monday=0. Persian week starts on Saturday.
        weekday_index = (moment.weekday() + 2) % 7
        text = f"{PERSIAN_WEEKDAYS[weekday_index]} {text}"
    return text


def format_shamsi_long(value: object) -> str:
    """``۱۴۰۴/۰۷/۱۳`` -> ``۱۳ مهر ۱۴۰۴``."""
    moment = coerce_datetime(value)
    if moment is None:
        return "—"
    jy, jm, jd = gregorian_to_jalali(moment.year, moment.month, moment.day)
    return f"{to_persian_digits(jd)} {PERSIAN_MONTHS[jm - 1]} {to_persian_digits(jy)}"


def format_datetime_shamsi(value: object) -> str:
    """Shamsi date plus 24h time, all Persian digits."""
    moment = coerce_datetime(value)
    if moment is None:
        return "—"
    jy, jm, jd = gregorian_to_jalali(moment.year, moment.month, moment.day)
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    return (
        f"{to_persian_digits(jy)}/{to_persian_digits(f'{jm:02d}')}/"
        f"{to_persian_digits(f'{jd:02d}')} {to_persian_digits(clock)}"
    )


def coerce_datetime(value: object) -> Optional[datetime]:
    """Best-effort conversion of shopapi timestamps to a local ``datetime``."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    else:
        text = to_english_digits(value).strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
                try:
                    moment = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def month_range_shamsi(reference: Optional[date] = None) -> tuple[date, date]:
    """First and last Gregorian day of the current Shamsi month."""
    ref = reference or date.today()
    jy, jm, _ = gregorian_to_jalali(ref.year, ref.month, ref.day)
    first = shamsi_to_date(jy, jm, 1)
    last = shamsi_to_date(jy, jm, 31) if jm <= 6 else (
        shamsi_to_date(jy, jm, 30) if jm <= 11 else shamsi_to_date(jy, jm, 29)
    )
    # Esfand has 29 or 30 days; clamp and re-resolve when the month rolled over.
    if jm == 12:
        candidate = shamsi_to_date(jy, 12, 30)
        last = candidate if gregorian_to_jalali(candidate.year, candidate.month, candidate.day)[1] == 12 \
            else shamsi_to_date(jy, 12, 29)
    return first, last


def relative_fa(value: object) -> str:
    """Human Persian relative time, e.g. ``۵ دقیقه پیش``."""
    moment = coerce_datetime(value)
    if moment is None:
        return "—"
    delta = datetime.now(moment.tzinfo) - moment
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "لحظه‌ای پیش"
    if seconds < 60:
        return "لحظه‌ای پیش"
    minutes = seconds // 60
    if minutes < 60:
        return f"{to_persian_digits(minutes)} دقیقه پیش"
    hours = minutes // 60
    if hours < 24:
        return f"{to_persian_digits(hours)} ساعت پیش"
    days = hours // 24
    if days < 30:
        return f"{to_persian_digits(days)} روز پیش"
    return format_shamsi(moment)


def join_fa(parts: Iterable[str], sep: str = "، ") -> str:
    return sep.join(p for p in parts if p)


def price_level_label(level: int) -> str:
    """Persian name of a shopapi price level."""
    return {
        1: "سطح قیمت ۱ (عمده)",
        2: "سطح قیمت ۲",
        3: "سطح قیمت ۳ (خرده)",
        4: "سطح قیمت ۴",
        5: "سطح قیمت ۵",
    }.get(int(to_english_digits(level) or 0), f"سطح قیمت {to_persian_digits(level)}")
