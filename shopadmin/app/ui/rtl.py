"""Right-to-left helpers (v2.8.0).

In a right-to-left widget Qt mirrors ``AlignRight`` to the LEFT edge (it swaps
left and right unless ``AlignAbsolute`` is set). Until v2.7.0 tables, labels and
form captions used plain ``AlignRight`` and so sat on the left. ``RIGHT`` is the
real right edge.

Text without Persian letters (codes, part numbers, paths, URLs, usernames) is
shown left-to-right inside the right-aligned cell, so «C:\\Data» or «ZAA-256»
never comes out scrambled.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt

#: The physical right edge (never mirrored).
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute

_PERSIAN = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN = re.compile(r"[A-Za-z]")
#: LEFT-TO-RIGHT EMBEDDING ... POP DIRECTIONAL FORMATTING
LRE, PDF = "\u202a", "\u202c"


def is_ltr_text(text: str) -> bool:
    """Latin text without any Persian letter (an English name, code, path, URL)."""
    value = str(text or "")
    return bool(_LATIN.search(value)) and not _PERSIAN.search(value)


def bidi(text: str) -> str:
    """``text`` ready for a right-to-left widget: LTR-only text is embedded LTR."""
    value = str(text if text is not None else "")
    if value.startswith(LRE) or not is_ltr_text(value):
        return value
    return f"{LRE}{value}{PDF}"
