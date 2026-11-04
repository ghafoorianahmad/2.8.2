"""v2.18.0 the bot's automatic answers (port of the FAQ bundle's matcher; ``data/faq_fa.json``).

``find(text)`` -> the best question of the bank with a score 0..100. Only a confident match is
answered; the answers hold no price, only placeholders, and an answer whose placeholder has no
value yet is not sent at all (nothing invented). ``needs_staff`` answers also tell staff.

v2.18.1: managers edit the bank in «پاسخ‌گوی خودکار»: an edit of a built-in item is kept apart from
the file (``faq_custom``), so a new version never overwrites it; staff replies to a customer's
question become suggestions (``faq_suggestions``) that are used only once approved.
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
#: v2.18.1: what a ``needs_staff`` answer always ends with
STAFF_NOTE = "یکی از همکاران پاسخ می‌دهد."
#: v2.18.1: a reply with a long number or a price is about one customer, not a general answer
_PERSONAL = re.compile(r"[0-9۰-۹٠-٩][0-9۰-۹٠-٩٬,]{5,}|\bتومان\b|\bریال\b")
#: a run of digits this long in what a customer typed may be a national code or a card
_LONG_DIGITS = re.compile(r"[0-9۰-۹٠-٩]{8,}")
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


def find(text: str | None, items: list[dict] | None = None) -> Match | None:
    """The best of ``items`` (default: the file's bank) for ``text``; None for an empty text."""
    if not str(text or "").strip():
        return None
    best: Match | None = None
    for item in load_data()["items"] if items is None else items:
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
    match = find(text, active_items(db))
    if match is None or match.score < MIN_SCORE:
        return {}
    needs_staff = bool(match.item.get("needs_staff"))
    rendered = render(match.item["answer"], values(db))
    if rendered is None and not needs_staff:
        return {}
    # v2.18.1: a question for a colleague always gets this much, whatever the rest says
    if needs_staff:
        rendered = f"{rendered}\n\n{STAFF_NOTE}" if rendered else STAFF_NOTE
    with db._lock:
        db._conn.execute("INSERT INTO faq_log (faq_id, query, score, created_at) VALUES (?,?,?,?)",
                         (match.item["id"], _LONG_DIGITS.sub("…", str(text))[:200], match.score,
                          now_iso()))
        db._commit()
    return {"answer": rendered, "id": match.item["id"], "needs_staff": needs_staff,
            "score": match.score}


# ---- v2.18.1: the bank as managers edit it --------------------------------------------------------
def _custom_rows(db: OwnDB) -> dict[str, dict]:
    with db._lock:
        return {row["id"]: row for row in db._fetchall("SELECT * FROM faq_custom")}


def _from_row(row: dict, source: str, edited: bool) -> dict:
    return {"id": row["id"], "category": row["category"], "questions": json.loads(row["questions"]),
            "answer": row["answer"], "needs_staff": bool(row["needs_staff"]),
            "enabled": bool(row["enabled"]), "source": source, "edited": edited}


def all_items(db: OwnDB) -> list[dict]:
    """The file's items (each with its edit, if any), then the managers' own, for the page."""
    custom = _custom_rows(db)
    out: list[dict] = []
    for item in load_data()["items"]:
        row = custom.pop(item["id"], None)
        out.append(_from_row(row, "builtin", True) if row else
                   {**item, "enabled": True, "source": "builtin", "edited": False})
    out.extend(_from_row(row, "custom", True) for row in custom.values())
    return out


def active_items(db: OwnDB) -> list[dict]:
    return [item for item in all_items(db) if item["enabled"]]


def item_problem(questions: list[str], answer_text: str) -> str:
    if not [q for q in questions if q.strip()]:
        return "دست‌کم یک پرسش بنویسید."
    if not answer_text.strip():
        return "متن پاسخ را بنویسید."
    unknown = [key for key in _PLACEHOLDER.findall(answer_text) if key not in PLACEHOLDERS]
    if unknown:
        return f"این جای‌خالی شناخته نشد: {{{unknown[0]}}}"
    return ""


def save_item(db: OwnDB, item_id: str | None, *, category: str, questions: list[str],
              answer_text: str, needs_staff: bool, enabled: bool, actor: str) -> dict:
    """A new item (no id) or an edit, also of a built-in one. ValueError = the Persian reason."""
    questions = [" ".join(q.split()) for q in questions if q.strip()]
    problem = item_problem(questions, answer_text)
    if problem:
        raise ValueError(problem)
    builtin = {item["id"] for item in load_data()["items"]}
    if item_id is None:
        with db._lock:
            number = 1 + int(db._fetchone(
                "SELECT COUNT(*) AS n FROM faq_custom WHERE id LIKE 'custom_%'")["n"])
        item_id = f"custom_{number}"
        while item_id in _custom_rows(db):
            number += 1
            item_id = f"custom_{number}"
    elif item_id not in builtin and item_id not in _custom_rows(db):
        raise KeyError(item_id)
    with db._lock:
        db._conn.execute(
            "INSERT INTO faq_custom (id, category, questions, answer, needs_staff, enabled, "
            "updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "category=excluded.category, questions=excluded.questions, answer=excluded.answer, "
            "needs_staff=excluded.needs_staff, enabled=excluded.enabled, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (item_id, " ".join(category.split())[:80], json.dumps(questions, ensure_ascii=False),
             answer_text.strip(), int(needs_staff), int(enabled), now_iso(), actor))
        db._commit()
    return next(item for item in all_items(db) if item["id"] == item_id)


def remove_item(db: OwnDB, item_id: str) -> None:
    """A manager's own item goes; a built-in one goes back to the file's words."""
    with db._lock:
        db._conn.execute("DELETE FROM faq_custom WHERE id=?", (item_id,))
        db._commit()


# ---- v2.18.1: learning from what staff answer -----------------------------------------------------
def suggest(db: OwnDB, question: str, reply: str, request_id: int, actor: str) -> dict | None:
    """A colleague answered a customer's question: a suggestion, used only after approval. Not
    for a text that holds a long number, a reply that names a price (about one customer) or a
    question the bank already answers."""
    question = " ".join(str(question or "").split())
    reply = " ".join(str(reply or "").split())
    if len(question) < 5 or len(reply) < 5 or _LONG_DIGITS.search(question) or _PERSONAL.search(reply):
        return None
    known = find(question, active_items(db))
    if known is not None and known.score >= MIN_SCORE and not known.item.get("needs_staff"):
        return None
    wanted = normalize(question)
    with db._lock:
        for row in db._fetchall("SELECT question FROM faq_suggestions WHERE status='pending'"):
            if normalize(row["question"]) == wanted:
                return None
        cursor = db._conn.execute(
            "INSERT INTO faq_suggestions (question, answer, request_id, created_at, created_by) "
            "VALUES (?,?,?,?,?)", (question[:300], reply[:1000], request_id, now_iso(), actor))
        db._commit()
        return db._fetchone("SELECT * FROM faq_suggestions WHERE id=?", (cursor.lastrowid,))


def suggestions(db: OwnDB, limit: int = 200) -> list[dict]:
    with db._lock:
        return db._fetchall("SELECT * FROM faq_suggestions WHERE status='pending' "
                            "ORDER BY id DESC LIMIT ?", (int(limit),))


def decide_suggestion(db: OwnDB, suggestion_id: int, status: str, actor: str) -> bool:
    with db._lock:
        cursor = db._conn.execute(
            "UPDATE faq_suggestions SET status=?, decided_at=?, decided_by=? "
            "WHERE id=? AND status='pending'", (status, now_iso(), actor, suggestion_id))
        db._commit()
        return cursor.rowcount > 0


def report(db: OwnDB, limit: int = 100) -> list[dict]:
    with db._lock:
        return db._fetchall("SELECT id, faq_id, query, score, created_at FROM faq_log "
                            "ORDER BY id DESC LIMIT ?", (int(limit),))
