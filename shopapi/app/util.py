"""Small shared helpers."""
from __future__ import annotations

import math
from datetime import datetime, timezone

# SQL Server object names may contain spaces (e.g. the accounting database
# "hesab5 t"), so the database name is quoted as a bracketed identifier instead
# of being restricted to a bare word.
MAX_IDENTIFIER_LEN = 128


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def round_half_up(x: float) -> float:
    """Round to an integer with ties away from zero (matches SQL ROUND(x, 0))."""
    if x < 0:
        return -math.floor(-x + 0.5 + 1e-9)
    return math.floor(x + 0.5 + 1e-9)


def quote_identifier(name: str) -> str:
    """Return a safe, bracketed SQL Server identifier.

    Only config-provided names reach this helper; any closing bracket is escaped
    so the value can never break out of the brackets:

        "hesab5 t" -> "[hesab5 t]"
        "a]b"      -> "[a]]b]"
    """
    if name is None:
        raise ValueError("unsafe SQL identifier: None")
    text = str(name)
    if not text.strip():
        raise ValueError("unsafe SQL identifier: empty")
    if len(text) > MAX_IDENTIFIER_LEN:
        raise ValueError("unsafe SQL identifier: too long (max 128 characters)")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError("unsafe SQL identifier: contains a control character")
    return "[" + text.replace("]", "]]") + "]"


def safe_identifier(name: str) -> str:
    """Deprecated alias kept for callers outside this package."""
    return quote_identifier(name)
