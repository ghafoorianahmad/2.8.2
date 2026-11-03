"""v2.18.0 the bot's automatic answers (port of the FAQ bundle's matcher; ``data/faq_fa.json``).

``find(text)`` -> the best question of the bank with a score 0..100. Only a confident match is
answered; the answers hold no price, only placeholders, and an answer whose placeholder has no
value yet is not sent at all (nothing invented). ``needs_staff`` answers also tell staff.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .db_own import OwnDB
from .util import now_iso

DATA_FILE = Path(__file__).with_name("data") / "faq_fa.json"
ENABLED_KEY = "faq_enabled"
VALUES_KEY = "faq_values"
#: below this the bot does not answer: a wrong answer is worse than the menu
MIN_SCORE = 80
PLACEHOLDERS = ("hours", "address", "phone", "instagram", "telegram", "website")
#: The shop's public details as the owner gave them for the mini app; editable in «قواعد فروشگاه».
DEFAULT_VALUES = {
    "address": "مشهد، ۱۷ شهریور، ابتدای کوچه آیت‌الله صدوقی (چهنو)، سومین فروشگاه سمت راست",
    "phone": "09155000432", "website": "https://asrertebatat2.ir",
    "instagram": "https://instagram.com/asrertebatat2", "telegram": "https://t.me/Asrertebatat_2",
}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

_STOP = frozenset({
    "سلام", "علیکم", "وقت", "بخیر", "خسته", "نباشید", "نباشی", "ببخشید", "لطفا", "لطف", "میکنید",
    "میکنین", "میشه", "بگید", "بگین", "میخواستم", "بدونم", "بپرسم", "آقا", "اقا", "داداش", "عزیز",
    "جان", "شما", "دارید", "دارین", "دارن", "داره", "هست", "هستین", "هستید", "چیه", "چجوریه",
    "چطوریه", "چطوره", "کجاست", "کجاس", "واسه", "برای", "توی", "تو", "در", "به", "از", "با", "رو",
    "را", "هم", "که", "این", "اون", "یک", "یه", "من", "ما", "بیزحمت",
})
_SYNONYMS = {
    "اقساتی": "اقساطی", "قسطی": "اقساطی", "اقساط": "اقساطی", "قسط": "اقساطی", "ادرس": "آدرس",
    "لوکیشن": "آدرس", "نشانی": "آدرس", "اینستا": "اینستاگرام", "پیج": "اینستاگرام",
    "رجستری": "رجیستری", "ریجستری": "رجیستری", "رجیستر": "رجیستری", "ریجستر": "رجیستری",
    "همتا": "رجیستری", "دستدوم": "کارکرده", "استوک": "کارکرده", "زنگ": "تلفن", "سایت": "وبسایت",
    "بات": "ربات", "فیش": "رسید", "واریزی": "رسید", "کارتبهکارت": "کارت", "گارد": "قاب",
    "کاور": "قاب", "اداپتور": "شارژر", "آداپتور": "شارژر", "کلگی": "شارژر", "ایرپاد": "هندزفری",
    "بادز": "هندزفری", "کارتن": "جعبه",
}
_SUFFIXES = ("هایتان", "هایمان", "هایشان", "هاتون", "هامون", "هاشون", "تون", "مون", "شون", "تان",
             "مان", "شان", "هایی", "های", "ها", "ین", "ید", "ند", "یم", "ام", "ات", "اش")
_LETTERS = str.maketrans({"ي": "ی", "ئ": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ؤ": "و", "إ": "ا",
                          "أ": "ا", "‌": " "})
_MARKS = re.compile("[ً-ٰٟ]")
_PUNCT = re.compile(r"[؟?!،,.;:«»\"'\-_()/\\|+*~@#$%^&\[\]{}<>]")


def normalize(text: str | None) -> str:
    value = _MARKS.sub("", str(text or "").translate(_LETTERS))
    value = _PUNCT.sub(" ", value)
    return " ".join(value.split()).lower()


def _stem(word: str) -> str:
    value = word.strip()
    if len(value) <= 3:
        return _SYNONYMS.get(value, value)
    for suffix in _SUFFIXES:
        if value.endswith(suffix) and len(value) - len(suffix) >= 3:
            value = value[:-len(suffix)]
            break
    return _SYNONYMS.get(value, value)


def _distance(a: str, b: str) -> int:
    if a == b:
        return 0
    row = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        previous, row[0] = row[0], i
        for j, ca in enumerate(a, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def _dice(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 0.0
    grams: dict[str, int] = {}
    for i in range(len(a) - 1):
        grams[a[i:i + 2]] = grams.get(a[i:i + 2], 0) + 1
    common = 0
    for i in range(len(b) - 1):
        if grams.get(b[i:i + 2], 0) > 0:
            common += 1
            grams[b[i:i + 2]] -= 1
    return 2 * common / (len(a) - 1 + len(b) - 1)


def _important(text: str) -> list[str]:
    words = normalize(text).split()
    return [_stem(w) for w in ([w for w in words if w not in _STOP] or words)]


def score(query: str, candidate: str) -> int:
    norm_q, norm_c = normalize(query), normalize(candidate)
    if not norm_q or not norm_c:
        return 0
    if norm_q == norm_c:
        return 100
    joined_q, joined_c = norm_q.replace(" ", ""), norm_c.replace(" ", "")
    if joined_q == joined_c:
        return 98
    q_tokens, c_tokens = _important(query), _important(candidate)
    matched = total = 0.0
    for token in q_tokens:
        weight = 2.0 if len(token) >= 4 else 1.0
        total += weight
        best = 0.0
        for other in c_tokens:
            if token == other:
                best = 1.0
                break
            if (len(token) >= 4 and token in other) or (len(other) >= 4 and other in token):
                best = max(best, 0.9)
            longest = max(len(token), len(other))
            if longest >= 4:
                gap = _distance(token, other)
                if gap == 1:
                    best = max(best, 0.88)
                elif gap == 2 and longest >= 6:
                    best = max(best, 0.72)
        matched += weight * best
    recall = matched / total if total else 0.0
    covered = 0
    for other in c_tokens:
        if any(token == other or (len(token) >= 4 and token in other)
               or (len(other) >= 4 and other in token)
               or (max(len(token), len(other)) >= 4 and _distance(token, other) <= 1)
               for token in q_tokens):
            covered += 1
    precision = covered / len(c_tokens) if c_tokens else 0.0
    bonus = 0.18 if len(joined_q) >= 5 and (joined_q in joined_c or joined_c in joined_q) else 0.0
    combined = recall * 0.52 + precision * 0.23 + _dice(joined_q, joined_c) * 0.25 + bonus
    return min(97, math.floor(combined * 100 + 0.5))


@lru_cache(maxsize=1)
def load_data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Match:
    item: dict
    score: int


def find(text: str | None) -> Match | None:
    """The best item for ``text`` (None for an empty text)."""
    if not str(text or "").strip():
        return None
    best: Match | None = None
    for item in load_data()["items"]:
        value = max((score(text, q) for q in item["questions"]), default=0)
        by_category = score(text, item["category"])
        if by_category > value:
            value = min(85, by_category)
        if best is None or value > best.score:
            best = Match(item, value)
    return best


# ---- the switch and the shop's own values -------------------------------------------------------
def enabled(db: OwnDB) -> bool:
    return db.get_state(ENABLED_KEY, "1") != "0"


def set_enabled(db: OwnDB, on: bool, actor: str) -> None:
    db.set_state(ENABLED_KEY, "1" if on else "0", actor)


def values(db: OwnDB) -> dict:
    try:
        saved = json.loads(db.get_state(VALUES_KEY, "") or "{}")
    except ValueError:
        saved = {}
    out = {key: str(saved.get(key) or DEFAULT_VALUES.get(key) or "").strip()
           for key in PLACEHOLDERS}
    if not out["hours"]:
        out["hours"] = _hours_text(db)
    return out


def _hours_text(db: OwnDB) -> str:
    """«۰۹:۰۰ تا ۱۳:۰۰ و ۱۶:۰۰ تا ۲۱:۰۰» from «ساعت کار» (the answer of the shop's own rule)."""
    from .staff_alerts import load_hours

    digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return " و ".join(f"{a} تا {b}" for a, b in load_hours(db).shifts).translate(digits)


def save_values(db: OwnDB, new: dict, actor: str) -> dict:
    cleaned = {key: " ".join(str(new.get(key) or "").split())[:300] for key in PLACEHOLDERS}
    db.set_state(VALUES_KEY, json.dumps(cleaned, ensure_ascii=False), actor)
    return cleaned


def render(answer: str, known: dict) -> str | None:
    """The answer with the shop's values; None when one of them is not set yet."""
    if any(not known.get(key) for key in _PLACEHOLDER.findall(answer)):
        return None
    return _PLACEHOLDER.sub(lambda m: known[m.group(1)], answer)


def answer(db: OwnDB, text: str) -> dict:
    """What the bot may say to ``text``: {"answer", "id", "needs_staff", "score"} or {}."""
    if not enabled(db):
        return {}
    match = find(text)
    if match is None or match.score < MIN_SCORE:
        return {}
    rendered = render(match.item["answer"], values(db))
    if rendered is None:
        return {}
    with db._lock:
        db._conn.execute("INSERT INTO faq_log (faq_id, query, score, created_at) VALUES (?,?,?,?)",
                         (match.item["id"], str(text)[:200], match.score, now_iso()))
        db._commit()
    return {"answer": rendered, "id": match.item["id"],
            "needs_staff": bool(match.item.get("needs_staff")), "score": match.score}


def report(db: OwnDB, limit: int = 100) -> list[dict]:
    with db._lock:
        return db._fetchall("SELECT id, faq_id, query, score, created_at FROM faq_log "
                            "ORDER BY id DESC LIMIT ?", (int(limit),))
