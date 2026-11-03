"""v2.18.0: is this customer a person «سازه حساب» already knows? (port of the reference matcher,
RULES.md of the persian name matcher bundle; every case of tests/data/name_match_tests.json passes)

``match(first, last, national_code, name, existing_code)`` -> score 0..100 and a verdict:
same (>= 95, suggest the link), similar (70..94, ask staff), different (a new person).
No imports from the app: pure text.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

SAME = "same"
SIMILAR = "similar"
DIFFERENT = "different"

_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})

_UNIFY = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ے": "ی",
    "ك": "ک", "ڪ": "ک",
    "ة": "ه", "ۀ": "ه", "ہ": "ه", "ە": "ه",
    "آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ؤ": "و",
    "ء": None,
})
_FORMAT_MARKS = re.compile("[‌‍‎‏ ]")
_DIACRITICS = re.compile("[ـً-ٰٟۖ-ۭ]")
_PUNCTUATION = re.compile(r"[(),.;:!?/\\|\[\]{}\"'`~@#$%^&*+=<>_-]+")

FORMAL_TITLES = frozenset({
    "اقای", "اقا", "خانم", "جناب", "سرکار", "بانو", "دکتر", "مهندس", "استاد", "کربلایی",
    "مشهدی", "مشتری", "فروشگاه", "موبایل", "همکار",
})
OPTIONAL_HONORIFICS = frozenset({"سید", "سیده", "حاج", "حاجی"})

SPELLING_VARIANTS = {
    "اسمعیل": "اسماعیل", "اسمعیلی": "اسماعیلی", "مصطفا": "مصطفی", "مرتضا": "مرتضی",
    "مجتبا": "مجتبی", "موسا": "موسی", "عیسا": "عیسی", "یحیا": "یحیی", "کبرا": "کبری",
    "صغرا": "صغری", "ابرهیم": "ابراهیم", "ابرهیمی": "ابراهیمی", "اسحق": "اسحاق",
    "اسحقی": "اسحاقی", "داود": "داوود", "داودی": "داوودی", "کاوس": "کاووس", "کاوسی": "کاووسی",
    "طاوس": "طاووس", "طاوسی": "طاووسی", "تهماسب": "طهماسب", "تهماسبی": "طهماسبی",
    "تاهره": "طاهره", "تاهری": "طاهری", "قاصم": "قاسم", "قاصمی": "قاسمی", "منسور": "منصور",
    "منسوری": "منصوری", "رحمن": "رحمان", "رحمنی": "رحمانی", "عبدالرحمن": "عبدالرحمان",
    "سلیمن": "سلیمان", "ابولفضل": "ابوالفضل",
}
#: compound names whose last part has another spelling (محمدمصطفا -> محمدمصطفی)
_VARIANT_ENDINGS = (
    ("مصطفا", "مصطفی"), ("مرتضا", "مرتضی"), ("مجتبا", "مجتبی"), ("اسمعیل", "اسماعیل"),
    ("اسمعیلی", "اسماعیلی"), ("ابرهیم", "ابراهیم"), ("ابرهیمی", "ابراهیمی"), ("داود", "داوود"),
    ("داودی", "داوودی"), ("الرحمن", "الرحمان"),
)

COMPOUND_PREFIXES = frozenset({
    "محمد", "علی", "امیر", "غلام", "عبد", "ابو", "ابوال", "نور", "جان", "ملک", "شاه", "مهر",
    "ناز", "گل", "پری", "ماه",
})
COMPOUND_SECOND_PARTS = frozenset({
    "رضا", "حسین", "حسن", "علی", "مهدی", "جواد", "باقر", "صادق", "کاظم", "تقی", "نقی", "هادی",
    "عباس", "اکبر", "اصغر", "امین", "امیر", "طاهر", "پاشا", "امید", "عرفان", "ارسلان", "صدرا",
    "عطا", "پارسا", "سبحان", "یاسین", "سجاد", "صالح", "رسول", "نبی", "ولی", "قلی", "خدا",
    "الله", "اله", "الرحمان", "الرحمن", "الرحیم", "الکریم", "العظیم", "العزیز", "الحسین",
    "الحسن", "الرضا", "الفضل", "القاسم",
})
FAMILY_SUFFIXES = frozenset({
    "پور", "زاده", "نژاد", "نیا", "فر", "فرد", "لو", "وند", "ان", "یان", "ی", "ابادی", "اباد",
    "منش", "مقدم", "تبار", "بخش", "خواه", "دوست", "جو", "صفت", "نسب", "پناه", "مهر", "راد",
    "کیا", "بیگی", "بیگ", "خان", "خانی",
})

_HOMOPHONES = str.maketrans({"ط": "ت", "ص": "س", "ث": "س", "ذ": "ز", "ض": "ز", "ظ": "ز",
                             "ق": "غ", "ه": "ح"})

#: similar spelling, but two different people: never a typo of each other
DISTINCT_NAMES = (
    ("حسن", "حسین"), ("حسنی", "حسینی"), ("زهرا", "زهره"), ("محمد", "محمود"),
    ("محمدی", "محمودی"), ("احمد", "احمدی"), ("حامد", "حمید"), ("امین", "امیر"),
    ("امینی", "امیری"), ("علی", "ولی"), ("سارا", "سحر"), ("مریم", "مرجان"), ("فرهاد", "فرزاد"),
    ("فرشاد", "فرهاد"), ("فرشاد", "فرزاد"), ("بهرام", "بهنام"), ("شهرام", "شهنام"),
    ("مهرداد", "مهرزاد"), ("سامان", "ساسان"), ("اشکان", "ایمان"), ("کاوه", "کیوان"),
    ("نازنین", "نسترن"), ("حمیده", "فهیمه"), ("اعظم", "اکرم"), ("اکبر", "اصغر"),
    ("اکبری", "اصغری"), ("باقر", "طاهر"), ("باقری", "طاهری"), ("صادق", "صالح"),
    ("صادقی", "صالحی"), ("جعفر", "جواد"), ("جعفری", "جوادی"), ("کاظم", "قاسم"),
    ("کاظمی", "قاسمی"), ("کریم", "رحیم"), ("کریمی", "رحیمی"), ("کریمی", "کرمی"),
    ("رحمان", "رحیم"), ("رحمانی", "رحیمی"), ("ستاری", "سالاری"), ("عباسی", "عبادی"),
    ("هاشمی", "حاتمی"), ("حیدری", "صفدری"), ("موسوی", "مهدوی"), ("نوری", "نوذری"),
    ("زارع", "زاهد"), ("زارعی", "زاهدی"),
)
_DISTINCT = frozenset(frozenset(pair) for pair in DISTINCT_NAMES)


@dataclass
class Normalized:
    tokens: list[str] = field(default_factory=list)
    text: str = ""
    compact: str = ""
    honorific: bool = False


@dataclass(frozen=True)
class MatchResult:
    score: int
    verdict: str
    rule: str


def normalize_code(code) -> str | None:
    """Digits only; None when nothing is left."""
    if code is None:
        return None
    digits = re.sub(r"[\s\-_./]", "", str(code).translate(_DIGITS)).strip()
    return digits or None


def normalize_characters(text: str | None) -> str:
    if not text:
        return ""
    value = str(text).translate(_DIGITS)
    value = _FORMAT_MARKS.sub(" ", value)
    value = _DIACRITICS.sub("", value)
    value = value.translate(_UNIFY)
    value = _PUNCTUATION.sub(" ", value)
    return " ".join(value.split())


def _canonical(token: str) -> str:
    value = token
    if (len(value) > 4 and value.endswith("اله") and not value.endswith("الله")
            and not value.endswith(("لاله", "ژاله", "هاله"))):
        value = value[:-3] + "الله"
    if len(value) > 5 and value.endswith("الهی") and not value.endswith("اللهی"):
        value = value[:-4] + "اللهی"
    value = SPELLING_VARIANTS.get(value, value)
    for ending, right in _VARIANT_ENDINGS:
        if value.endswith(ending):
            value = value[:-len(ending)] + right
    return value


def _unify(words: list[str]) -> list[str]:
    tokens = [t for t in (_canonical(w) for w in words) if t]
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        current = tokens[i]
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if following:
            if following in ("الله", "اله", "خدا"):
                merged.append(_canonical(current + ("الله" if following == "اله" else following)))
                i += 2
                continue
            if current in ("ابو", "عبد") and (following.startswith("ال")
                                              or following in COMPOUND_SECOND_PARTS):
                merged.append(_canonical(current + following))
                i += 2
                continue
            if current in COMPOUND_PREFIXES and following in COMPOUND_SECOND_PARTS:
                merged.append(_canonical(current + following))
                i += 2
                continue
            if following in FAMILY_SUFFIXES:
                merged.append(_canonical(current + following))
                i += 2
                continue
        merged.append(current)
        i += 1
    # a family suffix after a stem merged above (عبد + الله + زاده)
    out: list[str] = []
    j = 0
    while j < len(merged):
        current = merged[j]
        following = merged[j + 1] if j + 1 < len(merged) else None
        if following and following in FAMILY_SUFFIXES:
            out.append(_canonical(current + following))
            j += 2
        else:
            out.append(current)
            j += 1
    return out


def normalize_name(raw: str | None) -> Normalized:
    words = normalize_characters(raw).split(" ") if raw else []
    words = [w for w in words if w]
    kept: list[str] = []
    honorific = False
    for index, word in enumerate(words):
        if word.isdigit():           # a ledger's account number after the name
            continue
        if word in FORMAL_TITLES:
            continue
        if word in OPTIONAL_HONORIFICS and len(words) > 1:
            if index == len(words) - 1 and kept:
                kept.append(word)    # the family name itself
            else:
                honorific = True
            continue
        kept.append(word)
    tokens = _unify(kept or words)
    return Normalized(tokens, " ".join(tokens), "".join(tokens), honorific)


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein (optimal string alignment)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        table[i][0] = i
    for j in range(len(b) + 1):
        table[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[len(a)][len(b)]


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    longest = max(len(a), len(b))
    return max(0.0, (longest - edit_distance(a, b)) / longest)


def _round(value: float) -> int:
    return math.floor(value + 0.5)     # as JavaScript's Math.round (Python's round is banker's)


def _distinct(a: str, b: str) -> bool:
    return a != b and frozenset((a, b)) in _DISTINCT


def _affix_variant(a: str, b: str) -> bool:
    if a == b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if not longer.startswith(shorter) or len(shorter) < 3:
        return False
    return longer[len(shorter):] in FAMILY_SUFFIXES


def _result(score: int, verdict: str, rule: str) -> MatchResult:
    return MatchResult(score, verdict, rule)


def match(first: str | None, last: str | None, national_code, name: str | None,
          existing_code=None) -> MatchResult:
    new_code, old_code = normalize_code(national_code), normalize_code(existing_code)
    norm_first, norm_last = normalize_name(first or ""), normalize_name(last or "")
    new = normalize_name(f"{first or ''} {last or ''}".strip())
    new.honorific = new.honorific or norm_first.honorific or norm_last.honorific
    old = normalize_name(name or "")

    if new_code is not None and old_code is not None:
        if new_code == old_code:
            return _result(100, SAME, "NATIONAL_CODE_EXACT_MATCH")
        return _result(0, DIFFERENT, "NATIONAL_CODE_MISMATCH")
    if not new.compact or not old.compact:
        return _result(0, DIFFERENT, "EMPTY_NAME")
    if new.text == old.text or new.compact == old.compact:
        return _result(97 if new.honorific != old.honorific else 100, SAME,
                       "EXACT_NORMALIZED_MATCH")

    new_first, new_last = norm_first.compact, norm_last.compact
    swapped = new_last + new_first
    if new_first and new_last and swapped == old.compact:
        return _result(88, SIMILAR, "SWAPPED_FIRST_LAST_NAME")
    if (len(new.tokens) >= 2 and len(new.tokens) == len(old.tokens)
            and sorted(new.tokens) == sorted(old.tokens)):
        return _result(88, SIMILAR, "REORDERED_NAME_TOKENS")

    old_first = old.tokens[0] if old.tokens else ""
    old_last = "".join(old.tokens[1:]) if len(old.tokens) > 1 else ""
    if (new_first and new_last and old_first and old_last
            and similarity(new_first, old_last) >= 0.85
            and similarity(new_last, old_first) >= 0.85
            and edit_distance(swapped, old.compact) <= 1):
        return _result(80, SIMILAR, "SWAPPED_WITH_MINOR_TYPO")

    if len(old.tokens) == 1 and new_first and new_last and old.tokens[0] in (new_last, new_first):
        return _result(75, SIMILAR, "PARTIAL_SINGLE_NAME_RECORD")

    if new_first and new_last and old_first and old_last:
        first_dist, last_dist = edit_distance(new_first, old_first), edit_distance(new_last, old_last)
        first_sim, last_sim = similarity(new_first, old_first), similarity(new_last, old_last)
        if new_first == old_first:
            if _distinct(new_last, old_last):
                return _result(min(55, _round(first_sim * 30 + last_sim * 35)), DIFFERENT,
                               "SAME_FIRST_DIFFERENT_FAMILY")
            if _affix_variant(new_last, old_last):
                return _result(84, SIMILAR, "FAMILY_AFFIX_VARIANT")
            if new_last.translate(_HOMOPHONES) == old_last.translate(_HOMOPHONES):
                return _result(90, SIMILAR, "PHONETIC_HOMOPHONE_FAMILY")
            if last_dist == 1 and max(len(new_last), len(old_last)) >= 4:
                return _result(86, SIMILAR, "ONE_LETTER_TYPO_IN_LAST_NAME")
            if last_dist == 2 and min(len(new_last), len(old_last)) >= 7:
                return _result(76, SIMILAR, "MINOR_TYPO_IN_LONG_LAST_NAME")
            return _result(min(55, _round(25 + last_sim * 35)), DIFFERENT,
                           "SAME_FIRST_DIFFERENT_FAMILY")
        if new_last == old_last:
            shorter, longer = ((new_first, old_first) if len(new_first) < len(old_first)
                               else (old_first, new_first))
            if len(shorter) >= 3 and (longer.startswith(shorter) or longer.endswith(shorter)):
                rest = (longer[len(shorter):] if longer.startswith(shorter)
                        else longer[:len(longer) - len(shorter)])
                if (shorter in COMPOUND_PREFIXES or rest in COMPOUND_SECOND_PARTS
                        or rest in COMPOUND_PREFIXES):
                    return _result(82, SIMILAR, "COMPOUND_FIRST_NAME_TRUNCATION")
            if _distinct(new_first, old_first):
                return _result(48, DIFFERENT, "DIFFERENT_FIRST_SAME_FAMILY")
            if new_first.translate(_HOMOPHONES) == old_first.translate(_HOMOPHONES):
                return _result(90, SIMILAR, "PHONETIC_HOMOPHONE_FIRST")
            if first_dist == 1 and max(len(new_first), len(old_first)) >= 3:
                return _result(85, SIMILAR, "ONE_LETTER_TYPO_IN_FIRST_NAME")
            return _result(min(52, _round(25 + first_sim * 30)), DIFFERENT,
                           "DIFFERENT_FIRST_SAME_FAMILY")
        if (first_dist == 1 and last_dist == 1 and not _distinct(new_first, old_first)
                and not _distinct(new_last, old_last)
                and len(new_first) >= 4 and len(new_last) >= 5):
            return _result(74, SIMILAR, "MINOR_TYPO_BOTH_PARTS")

    if edit_distance(new.compact, old.compact) == 1 and min(len(new.compact),
                                                           len(old.compact)) >= 6:
        return _result(83, SIMILAR, "FULL_NAME_SINGLE_CHAR_TYPO")
    return _result(min(65, _round(similarity(new.compact, old.compact) * 65)), DIFFERENT,
                   "NAMES_DIFFERENT")
