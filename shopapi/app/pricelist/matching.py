"""Smart, permanent price-list mapping (v2.6.2).

A row decision (map / ignore) is stored once per row key and is never asked
again. New lists are matched automatically, in this order:

1. **Same row** — the row's *smart key* (brand + model words + type + color,
   case-, spacing- and word-order-insensitive, ``256GB`` = ``256``, ``R8`` =
   ``Ram8``) equals the key of a row already decided -> the same decision.
2. **Same model** — a new color or a new part/region code (``ZAA``, ``CHA``,
   ``ویتنام`` / ``هند`` …) of a model whose decided rows all point to ONE product
   -> mapped to that product (or ignored, if the model is ignored).

Only truly new models stay «نگاشت‌نشده». Automatic decisions are flagged
(``price_mappings.auto``) so staff can confirm or undo them; an undone row is
remembered (``price_auto_rejects``) and never matched automatically again.
"""
from __future__ import annotations

import re

from .parser import normalize_key_part

#: Apple part / region codes printed after the model: ZAA, CHA, LLA, HNA, ZPA, …
_PART_CODE = re.compile(r"^[A-Z]{2}A$")
_SPLIT = re.compile(r"[\s/,()\[\]\"'«»]+")
_STORAGE = re.compile(r"^(\d+)(?:gb|g|b|tb)$")
_RAM = re.compile(r"^r(?:am)?(\d+)$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def part_code(description: str) -> str:
    """The part/region code in a description (``17 Promax 512 ZAA`` -> ``ZAA``)."""
    codes = [t for t in _SPLIT.split(str(description or "")) if _PART_CODE.match(t)]
    return codes[-1] if codes else ""


def part_label(description: str, kind: str) -> str:
    """What the customer picks after the color: the part code, else the type
    (ویتنام / هند / شرکتی …)."""
    return part_code(description) or " ".join(str(kind or "").split())


def _tokens(text: str) -> list[str]:
    value = normalize_key_part(str(text or "").translate(_DIGITS)).replace("+", " + ")
    out: list[str] = []
    for token in _SPLIT.split(value):
        if not token:
            continue
        storage = _STORAGE.match(token)
        ram = _RAM.match(token)
        out.append(storage.group(1) if storage else f"ram{ram.group(1)}" if ram else token)
    return out


def _model_tokens(description: str) -> list[str]:
    code = part_code(description).lower()
    return sorted(t for t in _tokens(description) if not code or t != code)


def smart_key(section: str, description: str, kind: str, color: str) -> str:
    return "|".join((
        " ".join(_tokens(section)),
        " ".join(sorted(_tokens(description))),
        " ".join(_tokens(kind)),
        " ".join(sorted(_tokens(color))),
    ))


def model_key(section: str, description: str) -> str:
    """The model without color, type and part code."""
    return " ".join(_tokens(section)) + "|" + " ".join(_model_tokens(description))


def auto_match(repo, list_id: int, actor: str = "system:auto") -> int:
    """Decide every undecided row of ``list_id`` that matches a decided row
    (see the module doc). Returns how many rows were decided."""
    mappings = repo.list_mappings()
    by_smart: dict[str, dict] = {}
    by_model: dict[str, set[tuple[str, int | None]]] = {}
    for m in sorted(mappings, key=lambda m: int(m.get("auto") or 0)):   # manual first
        by_smart.setdefault(smart_key(m["section"], m["description"], m["kind"], m["color"]), m)
        by_model.setdefault(model_key(m["section"], m["description"]), set()).add(
            (m["action"], m["kala_code"]))
    rejected = repo.auto_rejected_keys()
    done = 0
    for row in repo.rows(list_id):
        if row["action"] is not None or row["row_key"] in rejected:
            continue
        same = by_smart.get(smart_key(row["section"], row["description"], row["kind"],
                                      row["color"]))
        if same is not None:
            action, code, label, reason = (same["action"], same["kala_code"],
                                           same["color_label"] or "", "same_row")
        else:
            options = by_model.get(model_key(row["section"], row["description"])) or set()
            if len(options) != 1:
                continue                     # a new model, or one split over products
            (action, code), = options
            label, reason = "", "same_model"
        mapping = repo.upsert_mapping(
            row_key=row["row_key"], action=action, kala_code=code,
            color_label=label if action == "map" else "",
            section=row["section"], description=row["description"], kind=row["kind"],
            color=row["color"], actor=actor, auto=True, auto_reason=reason,
        )
        by_smart.setdefault(smart_key(row["section"], row["description"], row["kind"],
                                      row["color"]), mapping)
        by_model.setdefault(model_key(row["section"], row["description"]), set()).add(
            (action, code))
        done += 1
    return done


# ---- v2.8.0: mapping by product-name similarity ------------------------------------------------
#: A row is mapped by name only when the best product is this close ...
NAME_AUTO_MIN = 0.86
#: ... and clearly ahead of the next one (otherwise it is ambiguous: suggestions only).
NAME_AUTO_GAP = 0.08
SUGGESTIONS = 3


_PRO_MAX = re.compile(r"pro\s*max|پرو\s*مکس|پرو\s*ماکس", re.IGNORECASE)


#: The RAM size (``Ram8``, ``R4``, «رم ۸») and family words a name may or may not carry.
_RAM_SPEC = re.compile(r"(?<![^\W\d_])(?:ram|r|رم)\s*[\d۰-۹]{1,2}(?![\d۰-۹])", re.IGNORECASE)
_FILLER = re.compile(r"(?<!\w)(?:galaxy|گلکسی|گالاکسی|گوشی|موبایل)(?!\w)", re.IGNORECASE)


def expand(text: str) -> str:
    """Price-list / hand-typed spellings: ``Promax`` = ``Pro Max``; the RAM size
    and «Galaxy» are dropped (often missing on one side)."""
    value = _PRO_MAX.sub(" pro max ", str(text or ""))
    value = _RAM_SPEC.sub(" ", value)
    return _FILLER.sub(" ", value)


def row_text(row: dict) -> str:
    """«iPHONE 17 Pro 256» - section + model, without the part / region code."""
    code = part_code(row.get("description") or "")
    words = [w for w in str(row.get("description") or "").split() if not code or w != code]
    return expand(" ".join([str(row.get("section") or "")] + words))


def _digits(text: str) -> set[str]:
    """Model numbers and storage; the RAM size (``Ram8``) is often not in a name."""
    from ..fuzzy import tokens

    toks = tokens(text)
    return {t for n, t in enumerate(toks) if t.isdigit() and not (n and toks[n - 1] == "ram")}


def name_candidates(row: dict, names: dict[int, str], *, limit: int = 10) -> list[dict]:
    """Products whose «سازه حساب» name best describes the row: [{code, name, score}].
    Every number of the row (model, storage) must be in the name."""
    from ..fuzzy import similarity

    text = row_text(row)
    with_color = f"{text} {row.get('color') or ''}".strip()
    need = _digits(text)
    scored = []
    for code, raw in names.items():
        name = expand(raw)
        if need and not need <= _digits(name):
            continue
        value = max(similarity(text, name), similarity(with_color, name))
        if value >= 0.5:
            scored.append({"code": int(code), "name": str(raw), "score": round(value, 4)})
    scored.sort(key=lambda c: (-c["score"], c["code"]))
    return scored[:limit]


def confident(candidates: list[dict]) -> dict | None:
    """The one candidate safe to map automatically, or None (never on a tie)."""
    if not candidates or candidates[0]["score"] < NAME_AUTO_MIN:
        return None
    if len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < NAME_AUTO_GAP:
        return None
    return candidates[0]


def name_match(repo, list_id: int, names: dict[int, str], actor: str = "system:auto") -> int:
    """Map still-undecided rows of ``list_id`` to the product with a clearly
    matching name (flagged «خودکار», reason ``name``). Ambiguous rows stay
    unmapped; rows whose automatic match staff undid are never touched."""
    if not names:
        return 0
    rejected = repo.auto_rejected_keys()
    done = 0
    for row in repo.rows(list_id):
        if row["action"] is not None or row["row_key"] in rejected:
            continue
        best = confident(name_candidates(row, names))
        if best is None:
            continue
        repo.upsert_mapping(
            row_key=row["row_key"], action="map", kala_code=best["code"], color_label="",
            section=row["section"], description=row["description"], kind=row["kind"],
            color=row["color"], actor=actor, auto=True, auto_reason="name")
        done += 1
    return done
