"""Smart phone search in the current price list (v2.8.0).

A customer types a phone name, full or partial, Persian or English, in any
spelling: «آیفون ۱۷ پرو», «17pro», «iphone 17 pro 256», «سامسونگ a55 ۲۵۶ گیگ».
Both the text and every row of the active list are reduced to the same tokens
(``fuzzy.tokens``: case, ی/ي, Persian/Arabic digits, letter/digit boundaries,
Persian brand and model words -> English, ``گیگ``/``GB`` -> ``gb``) plus a few
price-list spellings (``Promax`` = ``Pro Max``, brand implied by the section).
Word order never matters.

A row matches when every number the customer typed is in the row and most of
the other words are; a row with an extra model word (``Max`` when the customer
asked for «17 Pro») ranks lower. Rows are grouped into models (the description
without the part / region code), best model first.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from . import fuzzy
from .pricelist.matching import model_key, part_code, part_label

#: Price-list spellings -> tokens.
_COMPOUNDS = {
    "promax": ("pro", "max"), "pro+": ("pro", "plus"), "proplus": ("pro", "plus"),
    "ultra+": ("ultra", "plus"),
}
#: A brand implies its family name and back (the section says «iPHONE» / «SAMSUNG»).
_IMPLIED = {
    "iphone": {"apple"}, "apple": {"iphone"}, "samsung": {"galaxy"}, "galaxy": {"samsung"},
    "redmi": {"xiaomi"}, "poco": {"xiaomi"}, "xiaomi": {"mi"},
}
#: Persian / loose spellings fuzzy does not know.
_EXTRA_WORDS = {
    "پرومکس": ("pro", "max"), "پروماکس": ("pro", "max"), "ماکس": ("max",),
    "اپل": ("apple",), "ایرپاد": ("airpod",), "ایربادز": ("airpod",), "واچ": ("watch",),
    "ردمی": ("redmi",), "پوکو": ("poco",), "تبلت": ("tab",), "تب": ("tab",),
    "airpods": ("airpod",), "tablet": ("tab",), "iphon": ("iphone",), "ifon": ("iphone",),
    "samsong": ("samsung",), "sumsung": ("samsung",), "xaomi": ("xiaomi",),
}
_QUALIFIERS = {"pro", "max", "plus", "ultra", "mini", "lite", "fold", "flip", "edge", "air",
               "fe", "neo", "prime", "e", "s", "c"}
_LOW = {"gb", "tb", "ram", "5g", "4g", "wifi"}

MIN_COVERAGE = 0.75
MAX_MODELS = 6
MAX_ROWS = 40


def search_tokens(text: str | None) -> list[str]:
    raw = str(text or "")
    for word, parts in _EXTRA_WORDS.items():
        raw = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", " " + " ".join(parts) + " ", raw,
                     flags=re.IGNORECASE)
    out: list[str] = []
    for tok in fuzzy.tokens(raw):
        parts = _COMPOUNDS.get(tok)
        out.extend(parts if parts else (tok,))
    return out


def _weight(tok: str) -> float:
    return 0.3 if tok in _LOW or tok in fuzzy._VARIANT else 1.0


def _close(tok: str, pool: set[str]) -> bool:
    if tok in pool:
        return True
    if len(tok) < 4 or tok.isdigit():
        return False
    return any(len(p) >= 4 and SequenceMatcher(None, tok, p).ratio() >= 0.8 for p in pool)


def row_tokens(row: dict) -> set[str]:
    toks = set(search_tokens(" ".join(str(row.get(k) or "") for k in
                                      ("section", "description", "color", "kind"))))
    for tok in list(toks):
        toks |= _IMPLIED.get(tok, set())
    return toks


def score(query: list[str], row: dict) -> float:
    """0..1; 0 = not this row."""
    if not query:
        return 0.0
    pool = row_tokens(row)
    digits = {t for t in query if t.isdigit()}
    if not digits <= pool:
        return 0.0
    matched = sum(_weight(t) for t in query if _close(t, pool))
    total = sum(_weight(t) for t in query)
    coverage = matched / total if total else 0.0
    if coverage < MIN_COVERAGE:
        return 0.0
    model = set(search_tokens(row.get("description")))
    extra_qualifiers = (model & _QUALIFIERS) - set(query)
    return round(max(0.0, coverage - 0.15 * len(extra_qualifiers)), 4)


def model_name(row: dict) -> str:
    """«17 Pro 256» (the description without the part / region code)."""
    code = part_code(row.get("description") or "")
    words = [w for w in str(row.get("description") or "").split() if not code or w != code]
    return " ".join(words)


def search(rows: list[dict], text: str) -> list[dict]:
    """Best rows of ``rows`` (active-list rows with their mapping) for ``text``,
    grouped by model, best first. Rows without a price or ignored are skipped
    (v2.9.2: a row whose price waits for a manager stays, without a price)."""
    query = list(dict.fromkeys(search_tokens(text)))
    scored = []
    for row in rows:
        if (not row.get("price_rial") and not row.get("price_held"))                 or row.get("action") == "ignore":
            continue
        value = score(query, row)
        if value > 0:
            scored.append((value, row))
    groups: dict[str, dict] = {}
    for value, row in scored:
        key = model_key(row.get("section") or "", row.get("description") or "")
        group = groups.setdefault(key, {"score": 0.0, "rows": [], "min_price": None})
        group["score"] = max(group["score"], value)
        group["rows"].append(row)
        if not row.get("price_rial"):
            continue
        price = int(row["price_rial"])
        group["min_price"] = price if group["min_price"] is None else min(group["min_price"], price)
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["score"], kv[1]["min_price"] or 0,
                                                     kv[0]))
    if ranked:
        # far weaker models only add noise next to a good one
        best = ranked[0][1]["score"]
        ranked = [kv for kv in ranked if kv[1]["score"] > best - 0.26][:MAX_MODELS]
    out: list[dict] = []
    for index, (_key, group) in enumerate(ranked):
        for row in group["rows"]:
            out.append({**row, "model_index": index, "score": group["score"],
                        "model": model_name(row),
                        "part": part_label(row.get("description") or "", row.get("kind") or "")})
    return out[:MAX_ROWS]
