"""Fuzzy, normalized product-name matching (REQUIREMENTS §9a).

Sazeh Hesab names are typed by hand («آیفون۱۷ پرو ۲۵۶ گیگ», «Iphone 17pro 256G»),
site names are English («iPhone 17 Pro»). Both sides are reduced to the same
tokens before comparing:

* case, ی/ي, ک/ك, Persian/Arabic digits, ZWNJ, tatweel and diacritics;
* letter/digit boundaries split (``17pro`` -> ``17 pro``), punctuation = space;
* common Persian model words mapped to English (آیفون -> iphone, پرو -> pro,
  گیگ -> gb, ...), so the two scripts compare equal.

Identity first: numbers (17 vs 16, 256 vs 512), model qualifiers (Pro, Max,
Ultra, ...) and accessory words (قاب, گلس, ...) on one side only cost a lot, so a
different model or an accessory never looks "close". Colors and units cost
little, so «… 256 گیگ» and «… 256 گیگ آبی» stay close.
No app imports except ``text``: safe for any module.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from .text import normalize_fa

#: Persian (and loose English) spellings -> one canonical token.
_WORDS = {
    "آیفون": "iphone", "ایفون": "iphone", "آیفن": "iphone", "ifone": "iphone",
    "اپل": "apple",
    "سامسونگ": "samsung", "سامسونک": "samsung",
    "گلکسی": "galaxy", "گالاکسی": "galaxy", "گلاکسی": "galaxy",
    "شیائومی": "xiaomi", "شیاومی": "xiaomi", "شیامی": "xiaomi",
    "ردمی": "redmi", "پوکو": "poco", "نوت": "note",
    "پرو": "pro", "مکس": "max", "پلاس": "plus",
    "الترا": "ultra", "اولترا": "ultra", "آلترا": "ultra",
    "مینی": "mini", "لایت": "lite", "فولد": "fold", "فلیپ": "flip", "اج": "edge", "ایر": "air",
    "هواوی": "huawei", "آنر": "honor", "نوکیا": "nokia", "موتورولا": "motorola", "ریلمی": "realme",
    "گیگ": "gb", "گیگابایت": "gb", "گیگابایتی": "gb", "گیگی": "gb", "gig": "gb", "g": "gb",
    "ترابایت": "tb", "ترا": "tb",
    "رم": "ram",
    # letters as spoken in model names: «ردمی ۱۴ سی» = Redmi 14C, «اس ۲۵» = S25
    "سی": "c", "اس": "s", "زد": "z", "ایکس": "x", "تی": "t",
    "قاب": "case", "کاور": "cover", "گلس": "glass", "محافظ": "protector",
    "شارژر": "charger", "کابل": "cable", "هندزفری": "handsfree", "باتری": "battery",
}
#: Filler words that carry no identity.
_STOP = {"گوشی", "موبایل", "تلفن", "همراه", "مدل", "phone", "mobile", "smartphone", "و", "با"}
#: Model qualifiers: «17 Pro» and «17 Pro Max» are different models.
_QUALIFIERS = {"pro", "max", "plus", "ultra", "mini", "lite", "fold", "flip", "edge", "air",
               "note", "fe", "neo", "prime"}
#: Accessories: «قاب آیفون 17 پرو» is not the phone.
_ACCESSORIES = {"case", "cover", "glass", "protector", "charger", "cable", "handsfree",
                "battery", "adapter", "airpods", "strap", "holder", "lens", "screen"}
#: Variant words (storage unit, color, packing): cheap to add or drop.
_VARIANT = {
    "gb", "tb", "ram",
    "آبی", "مشکی", "سفید", "نقره", "نقرهای", "ای", "طلایی", "بنفش", "سبز", "قرمز", "صورتی",
    "خاکستری", "زرد", "نارنجی", "سرمه", "سرمهای", "کرم", "تیتانیوم", "تیتانیومی", "طبیعی",
    "black", "white", "blue", "silver", "gold", "purple", "green", "red", "pink", "gray",
    "grey", "yellow", "orange", "titanium", "natural", "desert", "graphite", "midnight",
    "starlight", "cream", "violet", "lavender",
}
_VARIANT_WEIGHT = 0.3

_MARKS = re.compile("[\u064b-\u065f\u0670\u0640\u200c\u200d\u200e\u200f\u00ad]")
_SPLIT_LD = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
_PUNCT = re.compile(r"[^\w]+|_")


def tokens(text: str | None) -> list[str]:
    """Normalized identity tokens of a product/model name."""
    value = normalize_fa(text).lower()
    value = _MARKS.sub("", value).replace("+", " plus ")
    value = _SPLIT_LD.sub(" ", value)
    value = _PUNCT.sub(" ", value)
    raw = value.split()
    out = []
    for n, tok in enumerate(raw):
        if tok == "ای" and any(0 <= k < len(raw) and raw[k].isdigit() for k in (n - 1, n + 1)):
            tok = "e"  # «آیفون ۱۷ ای» = 17e; «نقره ای» stays a color word
        tok = _WORDS.get(tok, tok)
        if tok and tok not in _STOP:
            out.append(tok)
    return out


def light_key(text: str | None) -> str:
    """Only trivial differences removed (ی/ي, digits, case, repeated spaces):
    two names with the same key are "unchanged"."""
    return " ".join(normalize_fa(text).lower().split())


def _identity(toks: list[str], kind: set[str] | None) -> set[str]:
    if kind is None:
        return {t for t in toks if t.isdigit()}
    if kind is _QUALIFIERS:
        # a single latin letter is a model letter too: 17 / 17e, 14 / 14c, S25 / A25
        return {t for t in toks if t in kind or (len(t) == 1 and t.isascii() and t.isalpha())}
    return {t for t in toks if t in kind}


def _weight(toks) -> float:
    return sum(_VARIANT_WEIGHT if t in _VARIANT else 1.0 for t in toks)


def _ratio(a: list[str], b: list[str]) -> float:
    return SequenceMatcher(None, "".join(a), "".join(b)).ratio()


#: Storage sizes: dropped (with their unit) when a customer's text is matched
#: against model names - «آیفون ۱۷ پرو ۲۵۶ گیگ» is the model «iPhone 17 Pro».
_STORAGE = {"32", "64", "128", "256", "512", "1024"}


def model_tokens(text: str | None) -> list[str]:
    """``tokens`` without storage sizes, units and color words."""
    toks = tokens(text)
    out = []
    for n, tok in enumerate(toks):
        nxt = toks[n + 1] if n + 1 < len(toks) else ""
        if tok in _VARIANT or (tok in _STORAGE and nxt in ("", "gb", "tb")):
            continue
        if tok in ("1", "2") and nxt == "tb":
            continue
        out.append(tok)
    return out


def similarity(a: str | None, b: str | None, *, model_only: bool = False) -> float:
    """Symmetric 0..1: how much two names describe the same thing.

    Used for name drift (confirmed vs current accounting name) and, with
    ``model_only`` (storage/color ignored), for matching a customer's text
    against model names.
    """
    split = model_tokens if model_only else tokens
    ta, tb = split(a), split(b)
    if not ta or not tb:
        return 0.0
    common = list((Counter(ta) & Counter(tb)).elements())
    dice = 2.0 * _weight(common) / (_weight(ta) + _weight(tb))
    score = 0.8 * dice + 0.2 * _ratio(ta, tb)
    for kind in (None, _QUALIFIERS, _ACCESSORIES):
        if _identity(ta, kind) != _identity(tb, kind):
            score *= 0.5
    return round(score, 4)


def coverage(query: str | None, candidate: str | None) -> float:
    """Asymmetric 0..1: is ``candidate`` (an accounting name) the model ``query``
    (a site model name)? Extra variant words in the candidate (storage, color)
    cost little, other extra words more, so «iPhone 17 Pro» ranks «… Pro 256»
    above «… Pro Max 256» and far above «قاب … Pro»."""
    tq, tc = tokens(query), tokens(candidate)
    if not tq or not tc:
        return 0.0
    common = list((Counter(tq) & Counter(tc)).elements())
    extra = list((Counter(tc) - Counter(tq)).elements())
    cost = sum(0.02 if (t in _VARIANT or t.isdigit()) else 0.08 for t in extra)
    score = (_weight(common) / _weight(tq)) / (1.0 + cost)
    score = 0.85 * score + 0.15 * _ratio(tq, tc)
    if not _identity(tq, None) <= _identity(tc, None):
        score *= 0.5  # a model number the candidate does not have
    if _identity(tq, _QUALIFIERS) != _identity(tc, _QUALIFIERS):
        score *= 0.6
    if _identity(tc, _ACCESSORIES) - _identity(tq, _ACCESSORIES):
        score *= 0.4
    return round(score, 4)


def rank(query: str, names: dict[int, str], *, limit: int = 10,
         min_score: float = 0.35) -> list[dict]:
    """``names`` = {code: name} -> best [{code, name, score}] by ``coverage``."""
    scored = []
    for code, name in names.items():
        score = coverage(query, name)
        if score >= min_score:
            scored.append({"code": int(code), "name": name, "score": score})
    scored.sort(key=lambda r: (-r["score"], r["code"]))
    return scored[:limit]
