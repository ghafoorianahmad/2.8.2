"""Persian text normalization and masking (no app imports: safe for any module)."""
from __future__ import annotations

# Arabic yeh/kaf and Arabic-Indic + Persian digits -> Persian yeh/kaf + ASCII digits.
_FA_TRANS = str.maketrans(
    {
        "ي": "ی",
        "ك": "ک",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)


def normalize_fa(text: str | None) -> str:
    """Normalize Persian/Arabic text for search and phone comparison only."""
    if text is None:
        return ""
    return str(text).translate(_FA_TRANS).strip()


def mask_phone(phone: str | None) -> str:
    p = normalize_fa(phone or "")
    if not p:
        return "****"
    if len(p) < 4:
        return "*" * len(p)
    return p[:2] + "*" * (len(p) - 4) + p[-2:]


def mask_name(name: str | None) -> str:
    if not name:
        return ""
    return name[0] + "*" * (len(name) - 1)


def mobile_key(phone: str | None) -> str | None:
    """The last 10 digits of an Iranian mobile number (``9xxxxxxxxx``, ASCII).

    This is the matching key of recipe R4 (``RIGHT(DetailTBL.Comment, 10)``).
    Accepts 09…, +989…, 00989…, 989… and 9… with spaces/dashes and Persian or
    Arabic digits. Returns None for anything that is not a mobile number.
    """
    digits = "".join(ch for ch in normalize_fa(phone) if ch in "0123456789")
    if len(digits) < 10:
        return None
    key = digits[-10:]
    prefix = digits[:-10]
    if prefix not in ("", "0", "98", "098", "0098") or not key.startswith("9"):
        return None
    return key
