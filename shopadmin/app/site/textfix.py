"""v2.14.0: Persian text from supplier PDFs, and keys for finding duplicates.

* ``fix_chars``: Arabic ك/ي/ى -> Persian ک/ی, presentation forms (ﻻ …) -> plain letters.
* ``visual_to_logical``: many supplier PDFs store a right-to-left line in the order
  it is *drawn* (left to right), so a text reader gets «تاحيضوت» for «توضيحات».
  The line is reversed, brackets are mirrored and every left-to-right run
  (Latin words, numbers) is turned back.
* ``match_key``: one form for comparing titles — ک/ی, ASCII digits, no brackets
  or punctuation, lower case, words sorted (word order does not matter).
* ``numbers`` / ``price_problems``: the site never shows a price.
"""
from __future__ import annotations

import re
import unicodedata

_ARABIC = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ئ": "ی", "ٱ": "ا"})
_DIGITS_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_RTL = re.compile(r"[֐-ࣿיִ-﷿ﹰ-﻿]")
_PRESENTATION = re.compile(r"[ﭐ-﷿ﹰ-﻿]")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")
_DIGIT = "0-9٠-٩۰-۹"
#: a left-to-right run: starts and ends with a Latin letter or digit; may hold
#: spaces and the neutral signs used inside model names and specs
_LTR_RUN = re.compile(rf"[A-Za-z{_DIGIT}](?:[A-Za-z{_DIGIT} .,/\-:+%*×•'_&°=~#]*[A-Za-z{_DIGIT}])?")


def fix_chars(text: str) -> str:
    text = _PRESENTATION.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text or "")
    return text.translate(_ARABIC).replace("‏", "").replace("‎", "")


def has_rtl(text: str) -> bool:
    return bool(_RTL.search(text or ""))


def _fix_latin_brackets(line: str) -> str:
    """``(12V/1.87A (22.5W`` -> ``12V/1.87A (22.5W)``: in a right-to-left cell the
    closing bracket of a Latin line is drawn at its start."""
    while line.startswith("(") and line.count("(") > line.count(")"):
        line = line[1:].lstrip() + ")"
    return line


def visual_to_logical(line: str) -> str:
    line = (line or "").strip()
    if not has_rtl(line):
        return _fix_latin_brackets(fix_chars(line))
    # flip first: a ligature such as ﻻ is one drawn glyph and expands to «لا» afterwards
    flipped = line[::-1].translate(_MIRROR)
    return fix_chars(_LTR_RUN.sub(lambda m: m.group(0)[::-1], flipped))


_GLUED = re.compile(r"([A-Za-z0-9])([؀-ۿ])")
_GLUED_BACK = re.compile(r"([؀-ۿ])([A-Za-z])")


def clean_line(line: str) -> str:
    """One line of a cell: logical order, no list bullets around it."""
    line = visual_to_logical(line)
    line = line.strip(" \t-–—•·*⚡")
    # «20000mAhمناسب» -> «20000mAh مناسب»
    line = _GLUED.sub(r"\1 \2", _GLUED_BACK.sub(r"\1 \2", line))
    return " ".join(line.split())


# ---- comparing ---------------------------------------------------------------------------
_PUNCT = re.compile(r"[()\[\]{}«»<>\"'`،,؛;:!?.\-_/\\|+*×•·]+")


def ascii_digits(text: str) -> str:
    return (text or "").translate(_DIGITS_ASCII)


def plain(text: str) -> str:
    """ک/ی, ASCII digits, no punctuation, lower case, single spaces (word order kept)."""
    text = ascii_digits(fix_chars(text)).replace("‌", " ").lower()
    text = _PUNCT.sub(" ", text)
    # «20000mAh» and «20000 mah» are the same
    text = re.sub(r"(\d)([a-z؀-ۿ])", r"\1 \2", text)
    text = re.sub(r"([a-z؀-ۿ])(\d)", r"\1 \2", text)
    return " ".join(text.split())


def match_key(text: str) -> str:
    """The same for any word order: ``plain`` with sorted words."""
    return " ".join(sorted(plain(text).split()))


_NUMBER = re.compile(r"\d+(?:[.,٫٬]\d+)*")


def numbers(text: str) -> set[str]:
    """Every number in the text (capacity, wattage, model numbers), as plain digits."""
    out = set()
    for raw in _NUMBER.findall(ascii_digits(fix_chars(text))):
        value = re.sub(r"[,٬]", "", raw).replace("٫", ".")
        out.add(value.lstrip("0") or "0")
    return out


def words(text: str) -> set[str]:
    return {w for w in plain(text).split() if not w.isdigit()}


# ---- prices ------------------------------------------------------------------------------
_CURRENCY = re.compile(r"(?:\d[\d,٬.]*\s*(?:هزار\s*)?(?:تومان|تومن|ریال|toman|rial|irr|irt)\b)"
                       r"|(?:قیمت\s*[:：]?\s*\d)|(?:(?:تومان|ریال)\s*\d)", re.IGNORECASE)
_UNIT_AFTER = re.compile(r"\s*(?:mah|wh|w|v|a|mm|cm|m|g|kg|hz|gb|tb|mb|%|°|اینچ|وات|ولت|آمپر|"
                         r"گرم|میلی|ساعت|متر|سانت|گیگ|ترابایت)", re.IGNORECASE)


def price_number_forms(value: str) -> set[str]:
    """``٢,٢٠٠`` -> {``2,200``, ``2200``}: how a dropped price could show up again."""
    digits = re.sub(r"[^\d]", "", ascii_digits(value or ""))
    if len(digits) < 3:
        return set()
    grouped = f"{int(digits):,}"
    return {digits, grouped}


def price_problems(text: str, blocked: set[str] | frozenset = frozenset()) -> list[str]:
    """Why ``text`` looks like it holds a price (empty = fine). ``blocked``: price
    numbers dropped from imported lists (``price_number_forms``)."""
    text = ascii_digits(fix_chars(text or ""))
    problems = []
    match = _CURRENCY.search(text)
    if match:
        problems.append(f"«{match.group(0).strip()}»")
    for form in sorted(blocked):
        for found in re.finditer(rf"(?<![\d.,]){re.escape(form)}(?![\d]|[.,]\d)", text):
            if not _UNIT_AFTER.match(text, found.end()):
                problems.append(f"«{form}»")
                break
    return problems
