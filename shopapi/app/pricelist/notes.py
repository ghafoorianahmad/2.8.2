"""Text posts of the price channel after the list (v2.9.1).

The distributor posts the PDF list and, later, short text posts:

* **corrections** («اصلاحیه»): one line per model, e.g. ::

      اصلاحیه
      A17 128-6 72.000
      A07 128-4 Small pack 48.500

  model, storage-RAM, an optional note, then the CASH («نقد») price in the PDF
  unit (thousand Toman; ``72.000`` = 72,000). No color: a line applies to every
  color (and type) of that model in the active list. It overrides the PDF until
  the next list. The «روال» price (what customers pay) = cash + the model's
  learned «روال − نقد» difference (``price_raval_diffs``, updated by every list);
  without history, the typical difference of the same brand at a similar price
  («روال تخمینی»). Lines that match no row are reported to the admin.
* **sales closed** («فروش بسته», «فروش موقتاً بسته است», …): phone sales close at
  once (until the next list) and the admin is alerted.

v2.18.0: real corrections rarely look like that. Every other post goes through
``price_message`` (formats, per-color prices, a brand header for the following posts):

* **applied**: the parser is sure and each item finds its rows (a color only its color);
* **uncertain**: nothing changes until a member of staff confirms (the 95% rule);
* **not recognized**: a date, a greeting, a post without a price. «اعمال دستی» can still use it.

Every changed row is kept in ``price_note_changes`` (old -> new) and staff are told.

Price guard (also for new lists, see ``importer``): a mapped row whose price
moves more than ``PRICE_GUARD_PCT`` (10 %) is not applied automatically; the old
price stays and the new one waits for a manager (``pending_*`` columns).
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field

from ..db_own import OwnDB
from ..util import now_iso
from . import price_message
from .matching import model_key
from .pricing import change_pct, customer_price_rial
from .repo import PriceListRepo

KIND_CORRECTION = "correction"
KIND_CLOSED = "sales_closed"
KIND_IGNORED = "ignored"
#: v2.18.0: a post that names prices but is not certain enough to change them by itself
KIND_UNCERTAIN = "uncertain"
#: a brand header («لیست قیمت محصولات برند TCH»): the brand of the posts that follow
CONTEXT_BRAND_KEY = "price_channel_brand"

FLAG_CORRECTION = "correction"
FLAG_HELD = "held"

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ـ": None, "‌": " ",
                          "‏": None, "‎": None})
#: brand words left out when models are compared ("Galaxy A17" = "A17")
BRAND_WORDS = frozenset({"galaxy", "samsung", "xiaomi", "apple", "iphone", "huawei", "honor",
                         "nokia", "tecno", "motorola", "mi"})
STORAGES = frozenset({8, 16, 32, 64, 128, 256, 512, 1024, 2048})

#: the header word of a correction post (اصلاحیه / اصلاح قیمت / اصلاحی)
_CORRECTION_HEADER = re.compile(r"اصلاحی|اصلاح\s*(?:قیمت|لیست)|تغییر\s*قیمت")
#: «فروش» near a closing word (on one line, a few words apart)
#: «بسته» as a word on its own (not «بسته‌های …» / «بسته‌بندی» / «بسته ۲ عددی» = a pack)
_SHUT = r"بسته(?!\s*(?:ها|های|ی\b|بندی|\d))"
_CLOSED = re.compile(
    r"فروش\s+(?:\S+\s+){0,3}?(?:" + _SHUT + r"|تعطیل|متوقف|قطع|نداریم|انجام\s*نمی)"
    r"|(?:" + _SHUT + r"|تعطیل|توقف|پایان)\s+(?:\S+\s+){0,2}?فروش"
    r"|(?:sale|sales)\s+(?:is\s+|are\s+)?closed",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"بسته\s+نیست|باز\s+است|باز\s+شد|فروش\s+ویژه")
#: a «sales closed» notice is short; a long post (an ad, a list as text) is not one
CLOSED_MAX_CHARS = 300
_PRICE_TOKEN = re.compile(r"^\d{1,3}(?:[.,٬٫]\d{1,3})+$|^\d{2,7}$")
_STORAGE_RAM = re.compile(r"^(\d{1,4})(?:gb|g|tb)?[-/_](\d{1,4})(?:gb|g)?$", re.IGNORECASE)
_STORAGE_ONLY = re.compile(r"^(\d{1,4})(gb|g|tb)?$", re.IGNORECASE)


def normalize(text: str) -> str:
    return str(text or "").translate(_DIGITS).translate(_LETTERS)


def classify(text: str) -> str:
    """correction / sales_closed / ignored."""
    value = normalize(text)
    if _CORRECTION_HEADER.search(value) and parse_correction(value)[0]:
        return KIND_CORRECTION
    if len(value.strip()) > CLOSED_MAX_CHARS:
        return KIND_IGNORED
    for line in value.splitlines():
        if _CLOSED.search(line) and not _NEGATED.search(line):
            return KIND_CLOSED
    return KIND_IGNORED


# --------------------------------------------------------------------------
# correction lines
# --------------------------------------------------------------------------
@dataclass
class CorrectionLine:
    line: str
    model: str            # compact, lower case, without brand words
    storage: int
    ram: int | None
    note: str             # lower case words between storage and price
    naghd: int            # PDF unit (thousand Toman)


def parse_price(token: str) -> int | None:
    """``72.000`` / ``72,000`` / ``72000`` -> 72000; ``72.5`` -> 72500."""
    value = normalize(token).strip()
    if not _PRICE_TOKEN.match(value):
        return None
    parts = re.split(r"[.,٬٫]", value)
    if len(parts) == 1:
        number = int(parts[0])
    else:
        tail = parts[-1]
        if len(parts) == 2 and len(tail) < 3:
            tail = tail.ljust(3, "0")             # 72.5 = 72,500
        number = int("".join(parts[:-1]) + tail)
    return number if 1_000 <= number <= 50_000_000 else None


def _is_storage(match) -> bool:
    """128 / 128GB / 1TB / 126GB (a typo with GB) - never 5G (a network)."""
    suffix = (match.group(2) or "").lower()
    return int(match.group(1)) in STORAGES or suffix in ("gb", "tb")


def _compact_model(words: list[str]) -> str:
    kept = [w for w in (w.lower().strip("()[]") for w in words) if w and w not in BRAND_WORDS]
    return "".join(kept)


def parse_line(line: str) -> CorrectionLine | None:
    tokens = normalize(line).replace("\t", " ").split()
    if len(tokens) < 3:
        return None
    naghd = parse_price(tokens[-1])
    if naghd is None:
        return None
    for index, token in enumerate(tokens[:-1]):
        if index == 0:
            continue                               # the model comes first
        storage, ram = None, None
        both = _STORAGE_RAM.match(token)
        if both:
            first, second = int(both.group(1)), int(both.group(2))
            if first in STORAGES:
                storage, ram = first, second
            elif second in STORAGES:               # RAM-storage written the other way
                storage, ram = second, first
        else:
            only = _STORAGE_ONLY.match(token)
            if only and _is_storage(only):
                storage = int(only.group(1)) * (1024 if (only.group(2) or "").lower() == "tb"
                                                 else 1)
        if storage is None:
            continue
        model = _compact_model(tokens[:index])
        if not model:
            return None
        note = " ".join(t.lower() for t in tokens[index + 1:-1])
        return CorrectionLine(line=line.strip(), model=model, storage=storage, ram=ram,
                              note=note, naghd=naghd)
    return None


def parse_correction(text: str) -> tuple[list[CorrectionLine], list[str]]:
    """(parsed lines, lines that look like a model line but could not be read)."""
    parsed: list[CorrectionLine] = []
    unreadable: list[str] = []
    for raw in normalize(text).splitlines():
        line = raw.strip()
        if not line or _CORRECTION_HEADER.search(line):
            continue
        item = parse_line(line)
        if item is not None:
            parsed.append(item)
        elif re.search(r"[A-Za-z]", line) and re.search(r"\d", line):
            unreadable.append(line)
    return parsed, unreadable


# --------------------------------------------------------------------------
# rows of the list
# --------------------------------------------------------------------------
@dataclass
class RowModel:
    model: str
    storage: int | None
    ram: int | None
    extras: frozenset = field(default_factory=frozenset)


_RAM_TOKEN = re.compile(r"^r(?:am)?(\d{1,2})$", re.IGNORECASE)
_SLASH = re.compile(r"^(\d{2,4})/(\d{1,2})$")


def row_model(description: str) -> RowModel:
    """``A07 (Full) 128GB Ram4`` -> model a07, 128, 4, extras {full};
    ``17 Promax 256 ZAA`` -> model 17promax, 256, None, {zaa};
    ``Tab A11 WIFI 128/8`` -> model taba11wifi, 128, 8."""
    tokens = normalize(description).replace("(", " (").replace(")", ") ").split()
    model_words: list[str] = []
    extras: set[str] = set()
    storage = ram = None
    for token in tokens:
        low = token.lower()
        if storage is None:
            slash = _SLASH.match(low)
            only = _STORAGE_ONLY.match(low)
            if slash and int(slash.group(1)) in STORAGES:
                storage, ram = int(slash.group(1)), int(slash.group(2))
                continue
            if only and model_words and _is_storage(only):
                storage = int(only.group(1)) * (1024 if (only.group(2) or "") == "tb" else 1)
                continue
            if low.startswith("(") or low.endswith(")"):
                extras.add(low.strip("()"))
                continue
            model_words.append(low)
            continue
        ram_match = _RAM_TOKEN.match(low)
        if ram_match and ram is None:
            ram = int(ram_match.group(1))
        elif low not in ("ram",):
            extras.add(low.strip("()"))
    return RowModel(_compact_model(model_words), storage, ram, frozenset(e for e in extras if e))


def match_rows(rows: list[dict], line: CorrectionLine) -> list[dict]:
    """The active-list rows a correction line applies to (empty = no clear match)."""
    def same_size(parsed: RowModel) -> bool:
        if parsed.storage != line.storage:
            return False
        return line.ram is None or parsed.ram is None or parsed.ram == line.ram
    parsed_rows = [(row, row_model(row["description"])) for row in rows]
    candidates = [(r, p) for r, p in parsed_rows if p.model == line.model and same_size(p)]
    if not candidates and len(line.model) >= 3:
        # "Note 15 Pro" for "Redmi Note 15 Pro": only when it names one model
        candidates = [(r, p) for r, p in parsed_rows
                      if p.model.endswith(line.model) and same_size(p)]
        if len({p.model for _, p in candidates}) > 1:
            return []
    if not candidates:
        return []
    rams = {p.ram for _, p in candidates}
    if line.ram is None and len(rams) > 1:
        return []                      # several RAM sizes and the line names none
    groups: dict[frozenset, list[dict]] = {}
    for row, parsed in candidates:
        groups.setdefault(parsed.extras, []).append(row)
    if len(groups) == 1:
        return next(iter(groups.values()))
    note = set(re.split(r"[\s()]+", line.note.lower())) - {""}
    fitting = [extras for extras in groups if extras <= note]
    if not fitting:
        return []
    best = max(len(e) for e in fitting)
    chosen = [e for e in fitting if len(e) == best]
    return groups[chosen[0]] if len(chosen) == 1 else []


# --------------------------------------------------------------------------
# «روال − نقد» differences
# --------------------------------------------------------------------------
def learn_diffs(db: OwnDB, list_id: int, rows: list[dict]) -> int:
    """Store each model's «روال − نقد» difference from a new list (median over its
    colors). Returns how many models were updated."""
    by_model: dict[str, list[tuple[int, int, str]]] = {}
    for row in rows:
        naghd, raval = row.get("naghd"), row.get("raval")
        if naghd and raval and raval >= naghd:
            key = model_key(row["section"], row["description"])
            by_model.setdefault(key, []).append((raval - naghd, naghd, row["section"]))
    ts = now_iso()
    with db._lock:
        for key, values in by_model.items():
            diff = int(statistics.median(v[0] for v in values))
            naghd = int(statistics.median(v[1] for v in values))
            db._conn.execute(
                "INSERT INTO price_raval_diffs (model_key, section, diff, naghd, list_id, "
                "updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(model_key) DO UPDATE SET "
                "section=excluded.section, diff=excluded.diff, naghd=excluded.naghd, "
                "list_id=excluded.list_id, updated_at=excluded.updated_at",
                (key, values[0][2], diff, naghd, int(list_id), ts))
        db._commit()
    return len(by_model)


def raval_for(db: OwnDB, row: dict, naghd: int, active_rows: list[dict],
              fallback_diff: int) -> tuple[int, bool]:
    """(روال, estimated): the model's learned difference, else the typical one of
    the same brand (section) at a similar price, else ``fallback_diff``."""
    key = model_key(row["section"], row["description"])
    with db._lock:
        found = db._fetchone("SELECT diff FROM price_raval_diffs WHERE model_key=?", (key,))
    if found is not None:
        return naghd + int(found["diff"]), False
    def diffs(rows):
        return [int(r["raval"]) - int(r["naghd"]) for r in rows
                if r.get("naghd") and r.get("raval") and r["raval"] >= r["naghd"]]
    same_brand = [r for r in active_rows if r["section"] == row["section"]]
    near = [r for r in same_brand if r.get("naghd") and abs(r["naghd"] - naghd) <= naghd * 0.25]
    for pool in (near, same_brand, active_rows):
        values = diffs(pool)
        if values:
            return naghd + int(statistics.median(values)), True
    return naghd + int(fallback_diff), True


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------
@dataclass
class NoteResult:
    kind: str
    note_id: int | None = None
    applied: list[str] = field(default_factory=list)       # row keys at the new price
    held: list[str] = field(default_factory=list)          # row keys waiting for approval
    unmatched: list[str] = field(default_factory=list)     # correction lines
    list_id: int | None = None
    #: v2.18.0: what the post says (for the staff member who confirms it)
    items: list[dict] = field(default_factory=list)
    #: what was changed: {row_key, section, description, color, old_*, new_*, held}
    changes: list[dict] = field(default_factory=list)
    brand_header: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "note_id": self.note_id, "applied": len(self.applied),
                "held": len(self.held), "unmatched": self.unmatched, "list_id": self.list_id,
                "items": self.items, "brand_header": self.brand_header}


def set_row_price(db: OwnDB, list_id: int, row: dict, naghd: int | None, raval: int | None,
                  price_rial: int | None, *, flag: str, note: str = "",
                  estimated: bool = False) -> None:
    """Sell a row at a new price (keeps the PDF values in orig_* once)."""
    with db._lock:
        db._conn.execute(
            "UPDATE price_list_rows SET orig_naghd=COALESCE(orig_naghd, naghd), "
            "orig_raval=COALESCE(orig_raval, raval), "
            "orig_price_rial=COALESCE(orig_price_rial, price_rial), "
            "naghd=?, raval=?, price_rial=?, price_flag=?, flag_note=?, raval_estimated=?, "
            "pending_naghd=NULL, pending_raval=NULL, pending_price_rial=NULL, "
            "pending_estimated=0, pending_source='' WHERE list_id=? AND row_key=?",
            (naghd, raval, price_rial, flag, note[:300], int(bool(estimated)), int(list_id),
             row["row_key"]))
        db._commit()


def hold_row_price(db: OwnDB, list_id: int, row: dict, naghd: int | None, raval: int | None,
                   price_rial: int | None, *, source: str, note: str = "",
                   estimated: bool = False) -> None:
    """Keep selling the current price; the new one waits for a manager."""
    with db._lock:
        db._conn.execute(
            "UPDATE price_list_rows SET pending_naghd=?, pending_raval=?, pending_price_rial=?, "
            "pending_estimated=?, pending_source=?, flag_note=?, "
            "price_flag=CASE WHEN price_flag='' THEN 'held' ELSE price_flag END "
            "WHERE list_id=? AND row_key=?",
            (naghd, raval, price_rial, int(bool(estimated)), source, note[:300], int(list_id),
             row["row_key"]))
        db._commit()


def apply_correction(db: OwnDB, settings, text: str, *, guard_pct: float,
                     result: NoteResult) -> NoteResult:
    repo = PriceListRepo(db)
    active = repo.active_list()
    lines, unreadable = parse_correction(text)
    result.unmatched.extend(unreadable)
    if active is None:
        result.unmatched.extend(line.line for line in lines)
        return result
    result.list_id = int(active["id"])
    rows = repo.rows(active["id"])
    fallback = settings.pricelist_cash_surcharge_rial // max(1, settings.pricelist_unit_rial)
    for line in lines:
        matched = match_rows(rows, line)
        if not matched:
            result.unmatched.append(line.line)
            continue
        for row in matched:
            _apply_price(db, settings, active["id"], row, rows, line.naghd, line.line,
                         guard_pct=guard_pct, fallback=fallback, result=result)
    return result


def _apply_price(db: OwnDB, settings, list_id: int, row: dict, rows: list[dict], naghd: int,
                 note: str, *, guard_pct: float, fallback: int, result: NoteResult) -> None:
    """One row at the new cash price (held when it moves more than the guard allows)."""
    raval, estimated = raval_for(db, row, naghd, rows, fallback)
    price = customer_price_rial(naghd, raval, unit_rial=settings.pricelist_unit_rial,
                                cash_surcharge_rial=settings.pricelist_cash_surcharge_rial)
    pct = change_pct(row.get("price_rial"), price)
    held = row.get("action") == "map" and pct is not None and pct > guard_pct
    if held:
        hold_row_price(db, list_id, row, naghd, raval, price, source=FLAG_CORRECTION, note=note,
                       estimated=estimated)
        result.held.append(row["row_key"])
    else:
        set_row_price(db, list_id, row, naghd, raval, price, flag=FLAG_CORRECTION, note=note,
                      estimated=estimated)
        result.applied.append(row["row_key"])
    result.changes.append({"row_key": row["row_key"], "section": row.get("section") or "",
                           "description": row.get("description") or "",
                           "color": row.get("color") or "", "old_naghd": row.get("naghd"),
                           "new_naghd": naghd, "old_price_rial": row.get("price_rial"),
                           "new_price_rial": price, "held": held})


# --------------------------------------------------------------------------
# v2.18.0: the other formats of the channel
# --------------------------------------------------------------------------
def rows_for_item(rows: list[dict], item: price_message.Item) -> list[dict]:
    """The rows a parsed price belongs to; empty unless that is certain: same model, storage,
    RAM and (when the post names one) color. A price for one color never touches the others."""
    if not item.model:
        return []
    model = _compact_model(item.model.split())
    storage = item.storage_gb
    if storage is None:
        # a flagship's colors without a storage: only if the model has a single storage
        sizes = {row_model(r["description"]).storage for r in rows
                 if row_model(r["description"]).model == model}
        if len(sizes) != 1:
            return []
        storage = next(iter(sizes))
        if storage is None:
            return []
    line = CorrectionLine(line="", model=model, storage=storage, ram=item.ram_gb, note="",
                          naghd=item.price)
    matched = match_rows(rows, line)
    if item.color:
        matched = [r for r in matched
                   if price_message.extract_color(str(r.get("color") or "")) == item.color]
    return matched


def _parsed_post(db: OwnDB, settings, text: str, *, guard_pct: float,
                 result: NoteResult) -> NoteResult:
    parsed = price_message.parse(text, db.get_state(CONTEXT_BRAND_KEY, "") or None)
    result.items = [item.as_dict() for item in parsed.items]
    if parsed.context_brand:
        db.set_state(CONTEXT_BRAND_KEY, parsed.context_brand, "worker")
        result.brand_header = parsed.context_brand
    if parsed.status == price_message.IGNORED:
        return result
    repo = PriceListRepo(db)
    active = repo.active_list()
    if active is None:
        result.kind = KIND_UNCERTAIN
        return result
    result.list_id = int(active["id"])
    rows = repo.rows(active["id"])
    # all or nothing: half a post applied is harder to check than none
    found = [rows_for_item(rows, item) for item in parsed.items]
    if parsed.status != price_message.APPLIED or not all(found):
        result.kind = KIND_UNCERTAIN
        result.unmatched = [_item_text(item) for item, hit in zip(parsed.items, found) if not hit]
        return result
    result.kind = KIND_CORRECTION
    fallback = settings.pricelist_cash_surcharge_rial // max(1, settings.pricelist_unit_rial)
    for item, matched in zip(parsed.items, found):
        for row in matched:
            _apply_price(db, settings, active["id"], row, rows, item.price, _item_text(item),
                         guard_pct=guard_pct, fallback=fallback, result=result)
    return result


def _item_text(item: price_message.Item) -> str:
    parts = [item.model or "؟"]
    if item.storage_gb:
        parts.append(str(item.storage_gb) + (f"-{item.ram_gb}" if item.ram_gb else ""))
    if item.color:
        parts.append(item.color)
    parts.append(str(item.price))
    return " ".join(parts)


def handle_post(db: OwnDB, settings, text: str, *, guard_pct: float) -> NoteResult:
    """A text post of the price channel: what it is, and what was done."""
    kind = classify(text)
    result = NoteResult(kind=kind)
    active = PriceListRepo(db).active_list()
    result.list_id = int(active["id"]) if active else None
    if kind == KIND_CORRECTION:
        apply_correction(db, settings, text, guard_pct=guard_pct, result=result)
    elif kind == KIND_IGNORED:
        _parsed_post(db, settings, text, guard_pct=guard_pct, result=result)
    return result


def record_changes(db: OwnDB, note_id: int, list_id: int | None, changes: list[dict],
                   actor: str) -> None:
    now = now_iso()
    with db._lock:
        for change in changes:
            db._conn.execute(
                "INSERT INTO price_note_changes (note_id, list_id, row_key, section, description, "
                "color, old_naghd, new_naghd, old_price_rial, new_price_rial, held, actor, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(note_id), list_id, change["row_key"], change["section"],
                 change["description"], change["color"], change["old_naghd"], change["new_naghd"],
                 change["old_price_rial"], change["new_price_rial"], int(bool(change["held"])),
                 actor, now))
        db._commit()


def note_changes(db: OwnDB, note_id: int) -> list[dict]:
    with db._lock:
        return db._fetchall("SELECT * FROM price_note_changes WHERE note_id=? ORDER BY id",
                            (int(note_id),))


def get_note(db: OwnDB, note_id: int) -> dict | None:
    with db._lock:
        row = db._fetchone("SELECT * FROM price_notes WHERE id=?", (int(note_id),))
    if row is None:
        return None
    try:
        row["result"] = json.loads(row["result"] or "{}")
    except ValueError:
        row["result"] = {}
    row["changes"] = note_changes(db, note_id)
    return row


def apply_manual(db: OwnDB, settings, note: dict, picks: list[tuple[str, int]], *, actor: str,
                 guard_pct: float) -> NoteResult:
    """«اعمال دستی»: staff chose the rows and prices of a post the parser left alone."""
    repo = PriceListRepo(db)
    active = repo.active_list()
    result = NoteResult(kind=KIND_CORRECTION)
    if active is None:
        return result
    result.list_id = int(active["id"])
    rows = repo.rows(active["id"])
    by_key = {row["row_key"]: row for row in rows}
    fallback = settings.pricelist_cash_surcharge_rial // max(1, settings.pricelist_unit_rial)
    for row_key, naghd in picks:
        row = by_key.get(row_key)
        if row is None:
            result.unmatched.append(row_key)
            continue
        _apply_price(db, settings, active["id"], row, rows, int(naghd),
                     str(note.get("text") or "")[:200], guard_pct=guard_pct, fallback=fallback,
                     result=result)
    saved = dict(note.get("result") or {})
    saved.update(applied=int(saved.get("applied") or 0) + len(result.applied),
                 held=int(saved.get("held") or 0) + len(result.held), manual_by=actor, unmatched=[])
    with db._lock:
        db._conn.execute("UPDATE price_notes SET kind=?, list_id=?, result=? WHERE id=?",
                         (KIND_CORRECTION, result.list_id,
                          json.dumps(saved, ensure_ascii=False)[:4000], int(note["id"])))
        db._commit()
    record_changes(db, int(note["id"]), result.list_id, result.changes, actor)
    return result


def store_note(db: OwnDB, kind: str, *, list_id: int | None, source_ref: str,
               posted_at: str | None, text: str, result: dict) -> int:
    with db._lock:
        cur = db._conn.execute(
            "INSERT INTO price_notes (list_id, kind, source_ref, posted_at, text, result, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (list_id, kind, source_ref[:200], posted_at, str(text or "")[:4000],
             json.dumps(result, ensure_ascii=False)[:4000], now_iso()))
        db._commit()
        return int(cur.lastrowid)


def list_notes(db: OwnDB, limit: int = 30) -> list[dict]:
    with db._lock:
        rows = db._fetchall("SELECT * FROM price_notes ORDER BY id DESC LIMIT ?", (int(limit),))
    for row in rows:
        try:
            row["result"] = json.loads(row["result"] or "{}")
        except ValueError:
            row["result"] = {}
        row["changes"] = note_changes(db, row["id"])
    return rows
