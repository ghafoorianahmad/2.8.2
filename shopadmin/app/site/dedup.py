"""v2.14.0: several PDFs into one branch without doubles.

Each imported row is compared with the items already in the branch and with
the rows read before it:

* **same** — same «کد کالا», or (no code on one side) the same title after
  normalising (ک/ی، digits, spaces, brackets, case, word order) and the same
  colours: merged automatically (``updated`` when something changed,
  ``duplicate`` when nothing did);
* **near** — a title a few characters different: never merged automatically;
  the preview shows both with pictures and the manager clicks «یکی است» or
  «جداست»;
* **new** — everything else.

Guards (never «same», never even «near»): a different number (capacity,
wattage, model number), a different colour, or a different model word.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import textfix as tf

NEW, UPDATED, DUPLICATE, NEAR = "new", "updated", "duplicate", "near"
NEAR_RATIO = 0.86
WORD_RATIO = 0.75
#: fields that make an «updated» row (the rest is kept from the item already here)
UPDATE_FIELDS = ("name", "brand_name", "specs", "description", "colors", "product_code")


@dataclass
class Match:
    status: str
    #: the item already here (or an earlier row of this import: ``row_index``)
    other: dict | None = None
    row_index: int = -1
    changed: list[str] = field(default_factory=list)


def _colors(item: dict) -> set[str]:
    return {tf.plain(c.get("name") if isinstance(c, dict) else c).replace(" ", "")
            for c in item.get("colors") or []}


def guards_differ(a: dict, b: dict) -> bool:
    """True when two items can never be the same: number, colour or model word."""
    if tf.numbers(a.get("name", "")) != tf.numbers(b.get("name", "")):
        return True
    if _colors(a) != _colors(b):
        return True
    only_a = tf.words(a.get("name", "")) - tf.words(b.get("name", ""))
    only_b = tf.words(b.get("name", "")) - tf.words(a.get("name", ""))
    if len(only_a) != len(only_b):
        return True
    # every word that differs must have a look-alike on the other side (a typo)
    for word in only_a:
        if not any(SequenceMatcher(None, word, other).ratio() >= WORD_RATIO for other in only_b):
            return True
    return False


def same_title(a: dict, b: dict) -> bool:
    return tf.match_key(a.get("name", "")) == tf.match_key(b.get("name", ""))


def near_title(a: dict, b: dict) -> bool:
    ka, kb = tf.match_key(a.get("name", "")), tf.match_key(b.get("name", ""))
    return ka != kb and SequenceMatcher(None, ka, kb).ratio() >= NEAR_RATIO


def changed_fields(old: dict, new: dict) -> list[str]:
    def norm(value):
        if isinstance(value, str):
            return tf.plain(value)
        if isinstance(value, list):
            return [norm(v) for v in value]
        if isinstance(value, dict):
            return norm(value.get("name"))
        return value
    out = [f for f in UPDATE_FIELDS if new.get(f) and norm(new.get(f)) != norm(old.get(f))]
    if "name" in out and same_title(old, new):
        out.remove("name")          # only the word order differs
    return out


def classify(item: dict, existing: list[dict], earlier: list[dict] | None = None) -> Match:
    """Where one imported item belongs. ``existing``: the branch's items;
    ``earlier``: the rows of this import already classified as not-a-double."""
    pools = [(other, -1) for other in existing]
    pools += [(other, n) for n, other in enumerate(earlier or [])]
    code = item.get("product_code") or ""
    if code:
        for other, n in pools:
            if other.get("product_code") == code:
                changed = changed_fields(other, item)
                return Match(UPDATED if changed else DUPLICATE, other, n, changed)
    for other, n in pools:
        if other.get("product_code") and code and other["product_code"] != code:
            continue        # two different codes are two items, whatever the title says
        if same_title(item, other) and not guards_differ(item, other):
            changed = changed_fields(other, item)
            return Match(UPDATED if changed else DUPLICATE, other, n, changed)
    for other, n in pools:
        if other.get("product_code") and code and other["product_code"] != code:
            continue
        if near_title(item, other) and not guards_differ(item, other):
            return Match(NEAR, other, n)
    return Match(NEW)


def merge(old: dict, new: dict) -> dict:
    """The item already here updated from an imported row: its site code, «پنهان»
    and picture stay unless the row brings a picture."""
    out = dict(old)
    for key in UPDATE_FIELDS:
        if new.get(key):
            out[key] = new[key]
    if new.get("image"):
        out["image"] = new["image"]
    return out


def summary(matches: list[Match]) -> dict[str, int]:
    out = {NEW: 0, UPDATED: 0, DUPLICATE: 0, NEAR: 0}
    for match in matches:
        out[match.status] += 1
    return out
