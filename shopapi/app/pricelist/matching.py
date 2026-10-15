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
