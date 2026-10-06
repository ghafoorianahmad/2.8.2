"""Small pure helpers: digit normalization, phone validation, masking, logging.

Privacy rule: nothing here ever puts a phone number, a name or message text into
a log line. `log_event` logs only platform, update id and event type.
"""
from __future__ import annotations

import logging
import re

# Persian (۰-۹) and Arabic-Indic (٠-٩) digits -> ASCII digits.
_DIGIT_TRANS = str.maketrans(
    {
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
)

_IRAN_MOBILE = re.compile(r"^09\d{9}$")
_NON_DIGIT = re.compile(r"[^0-9+]")


def normalize_digits(text: str | None) -> str:
    """Convert Persian/Arabic digits to ASCII and trim."""
    if not text:
        return ""
    return str(text).translate(_DIGIT_TRANS).strip()


def only_digits(text: str | None) -> str:
    return _NON_DIGIT.sub("", normalize_digits(text))


def parse_int(text: str | None, *, minimum: int | None = None, maximum: int | None = None):
    """Parse an int from user input; returns None when it is not a valid number."""
    raw = only_digits(text)
    if not raw.isdigit():
        return None
    value = int(raw)
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def normalize_mobile(text: str | None) -> str:
    """Return a canonical Iranian mobile number, or '' when invalid."""
    digits = only_digits(text)
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits if _IRAN_MOBILE.match(digits) else ""


def is_valid_mobile(text: str | None) -> bool:
    return bool(normalize_mobile(text))


def mask_phone(phone: str | None) -> str:
    digits = only_digits(phone)
    if len(digits) < 4:
        return "*" * len(digits)
    return digits[:3] + "*" * (len(digits) - 5) + digits[-2:]


def mask_name(name: str | None) -> str:
    if not name:
        return ""
    name = str(name).strip()
    if len(name) <= 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


def fmt_num(value) -> str:
    """Format a number for display with thousands separators and no decimals."""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def shorten(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit]


def log_event(logger: logging.Logger, platform: str, update_id, event_type: str) -> None:
    """The only allowed log shape: platform, update id, event type."""
    logger.info("platform=%s update_id=%s event=%s", platform, update_id, event_type)
