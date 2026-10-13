"""Integer -> Persian words (used for the grand total on the invoice cards)."""
from __future__ import annotations

_ONES = ("", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده", "یازده", "دوازده",
         "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده")
_TENS = ("", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود")
_HUNDREDS = ("", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد")
_AND = " و "


def _below_1000(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10])
        n %= 10
    if n:
        parts.append(_ONES[n])
    return _AND.join(parts)


def number_to_words_fa(value) -> str:
    """12 -> «دوازده»; 525000000 -> «پانصد و بیست و پنج میلیون»; 0 -> «صفر».

    Non-numbers and negatives give ``""`` (the card then omits the line); decimals are rounded."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return ""
    if n < 0:
        return ""
    if n == 0:
        return "صفر"
    parts = []
    billions, rest = divmod(n, 10**9)
    millions, rest = divmod(rest, 10**6)
    thousands, units = divmod(rest, 10**3)
    if billions:
        parts.append(number_to_words_fa(billions) + " میلیارد")
    if millions:
        parts.append(_below_1000(millions) + " میلیون")
    if thousands:
        parts.append("هزار" if thousands == 1 else _below_1000(thousands) + " هزار")
    if units:
        parts.append(_below_1000(units))
    return _AND.join(parts)


def amount_in_words(value, currency: str = "ریال") -> str:
    words = number_to_words_fa(value)
    return f"{words} {currency}".strip() if words else ""
