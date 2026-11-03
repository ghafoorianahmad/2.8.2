"""v2.18.0: what a customer means by «ایفون17پرومکس256 مشکی» (port of the alias bundle's reference
parser; every test of ``data/product_aliases.json`` passes).

``parse(text)`` -> brand, model, accessory type, storage, RAM, color and
``formatted`` = ``"iPhone 17 Pro Max | 256GB | Black"``.

Staff teach it: ``learn(db, text, model)`` keeps an alias the data file does not know;
``parse(text, learned=load_learned(db))`` then understands it too.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .util import now_iso

DATA_FILE = Path(__file__).with_name("data") / "product_aliases.json"

_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "آ": "ا", "أ": "ا", "إ": "ا",
                          "ٱ": "ا", "ة": "ه", "ؤ": "و", "‌": " ", "‏": " ", "‎": " "})

VALID_STORAGE = frozenset({"32", "64", "128", "256", "512", "1024"})
VALID_RAM = frozenset({"2", "3", "4", "6", "8", "12", "16", "18", "24"})
ACCESSORY_MODELS = frozenset({
    "AirPods Pro 2", "AirPods 4", "Apple Watch Ultra 2", "Apple Watch Series 10",
    "Apple 20W USB-C Power Adapter", "Galaxy Buds 3 Pro", "Galaxy Buds FE", "Galaxy Watch 7",
    "Galaxy Watch Ultra", "Samsung 25W Super Fast Charger", "Samsung 45W Super Fast Charger",
    "Xiaomi Redmi Buds 5 Pro", "Xiaomi 20000mAh Power Bank", "Xiaomi Smart Band 9",
})
_TOKEN_MAP = {
    "پرومکس": "پرو مکس", "پرومگس": "پرو مکس", "مگس": "مکس", "پروپلاس": "پرو پلاس",
    "promax": "pro max", "proplus": "pro plus", "اولترا": "الترا", "اولتر": "الترا",
    "التراا": "الترا", "ultera": "ultra", "پاوربانک": "پاور بانک", "powerbank": "power bank",
    "ایرپادز": "ایرپاد", "airpod": "airpods", "هنسفری": "هندزفری", "هنزفری": "هندزفری",
    "ایفن": "ایفون", "iphon": "iphone", "سمسونگ": "سامسونگ", "سمسنگ": "سامسونگ",
    "سامسونگگ": "سامسونگ", "samsong": "samsung", "گالکسی": "گلکسی", "شیایومی": "شیاومی",
    "شیامی": "شیاومی", "شایومی": "شیاومی", "شاومی": "شیاومی", "xiami": "xiaomi",
    "shiaomi": "xiaomi", "پکو": "پوکو", "poko": "poco",
    "redme": "redmi", "هانر": "انر", "هونر": "انر", "انور": "انر", "honer": "honor",
    "مترولا": "موتورولا", "متورولا": "موتورولا", "motorolla": "motorola", "realmi": "realme",
    "rilmi": "realme", "اینفنیکس": "اینفینیکس", "انفینیکس": "اینفینیکس", "infnix": "infinix",
    "تکنوفون": "تکنو", "tekno": "tecno", "techno": "tecno", "nating": "nothing",
    "تیسیاچ": "تی سی اچ",
}
_PUNCT = re.compile(r"[-_،,;؛:()\[\]{}+]")
_A = "ا-ی"
_SLASH = re.compile(r"^([0-9]+)/([0-9]+)$")
UNKNOWN = "نامشخص (مدل یافت نشد)"


def normalize(text: str | None) -> str:
    if not text:
        return ""
    value = str(text).strip().lower().translate(_DIGITS).translate(_LETTERS)
    value = _PUNCT.sub(lambda m: " پلاس " if m.group(0) == "+" else " ", value)
    value = re.sub(f"([{_A}])([a-z0-9])", r"\1 \2", value)
    value = re.sub(f"([a-z0-9])([{_A}])", r"\1 \2", value)
    value = re.sub(r"([a-z])([0-9])", r"\1 \2", value)
    value = re.sub(r"([0-9])([a-z])", r"\1 \2", value)
    value = re.sub(r"ریل\s+می", "ریلمی", value)
    value = re.sub(r"رد\s+می", "ردمی", value)
    out: list[str] = []
    for token in value.split():
        out.extend(part for part in _TOKEN_MAP.get(token, token).split(" ") if part)
    return " ".join(out)


@dataclass(frozen=True)
class _Alias:
    model: str
    brand: str
    tokens: tuple[str, ...]
    length: int


@dataclass(frozen=True)
class _Key:
    value: str
    tokens: tuple[str, ...]


@dataclass
class Parsed:
    brand: str | None = None
    model: str | None = None
    accessory: str | None = None
    storage: str | None = None
    ram: str | None = None
    color: str | None = None
    formatted: str = UNKNOWN
    confidence: str = "low"
    words: list[str] = field(default_factory=list)

    @property
    def storage_gb(self) -> int | None:
        if not self.storage:
            return None
        number = int(re.sub(r"\D", "", self.storage))
        return number * 1024 if self.storage.endswith("TB") else number

    @property
    def ram_gb(self) -> int | None:
        return int(re.sub(r"\D", "", self.ram)) if self.ram else None


@dataclass(frozen=True)
class Index:
    aliases: tuple[_Alias, ...]
    accessories: tuple[_Key, ...]
    colors: tuple[_Key, ...]
    brands: tuple[tuple[str, frozenset[str], tuple[tuple[str, ...], ...]], ...]
    ram_words: frozenset[str]
    storage: dict
    by_model: dict


def _keys(table: dict) -> tuple[_Key, ...]:
    keys = [(normalize(key), value) for key, value in table.items()]
    keys.sort(key=lambda item: (-len(item[0].split()), -len(item[0])))
    return tuple(_Key(value, tuple(norm.split())) for norm, value in keys if norm)


@lru_cache(maxsize=1)
def load_data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def index() -> Index:
    data = load_data()
    aliases: list[_Alias] = []
    by_model: dict = {}
    for entry in data["models"]:
        by_model[entry["canonical"]] = entry["brand"]
        seen: set[str] = set()
        for raw in [entry["canonical"], *entry["aliases"]]:
            norm = normalize(raw)
            if norm and norm not in seen:
                seen.add(norm)
                aliases.append(_Alias(entry["canonical"], entry["brand"], tuple(norm.split()),
                                      len(norm.replace(" ", ""))))
    brands = []
    for brand in data["brands"]:
        names = [normalize(a) for a in [brand["canonical"], *brand["aliases"]]]
        brands.append((brand["canonical"], frozenset(names),
                       tuple(tuple(n.split()) for n in names if n)))
    return Index(tuple(aliases), _keys(data["accessory_types"]), _keys(data["colors"]),
                 tuple(brands), frozenset(normalize(w) for w in data["ram_words"]),
                 {normalize(k): v for k, v in data["storage"].items()}, by_model)


def _at(tokens: list[str], needle: tuple[str, ...], start: int) -> bool:
    return tuple(tokens[start:start + len(needle)]) == needle


def _find_free(tokens: list[str], used: list[bool], needle: tuple[str, ...]) -> int | None:
    for start in range(len(tokens) - len(needle) + 1):
        if not any(used[start:start + len(needle)]) and _at(tokens, needle, start):
            return start
    return None


def _storage_text(number: str) -> str:
    return "1TB" if number == "1024" else f"{number}GB"


def parse(text: str | None, learned: tuple[_Alias, ...] = ()) -> Parsed:
    idx = index()
    tokens = normalize(text).split()
    used = [False] * len(tokens)
    out = Parsed()

    best: tuple[_Alias, int] | None = None
    for alias in (*idx.aliases, *learned):
        size = len(alias.tokens)
        if size == 0 or size > len(tokens):
            continue
        for start in range(len(tokens) - size + 1):
            if _at(tokens, alias.tokens, start) and (
                    best is None or size > len(best[0].tokens)
                    or (size == len(best[0].tokens) and alias.length > best[0].length)):
                best = (alias, start)
    if best is not None:
        alias, start = best
        out.model, out.brand = alias.model, alias.brand
        for n in range(start, start + len(alias.tokens)):
            used[n] = True
        if start > 0:
            names = next((names for name, names, _t in idx.brands if name == alias.brand), ())
            if tokens[start - 1] in names:
                used[start - 1] = True

    for key in idx.accessories:
        start = _find_free(tokens, used, key.tokens)
        if start is not None:
            out.accessory = key.value
            for n in range(start, start + len(key.tokens)):
                used[n] = True
            break
    if out.model in ACCESSORY_MODELS and out.accessory not in (None, "Case", "Screen Protector"):
        out.accessory = None

    if out.brand is None:
        for name, _names, alias_tokens in idx.brands:
            hit = None
            for needle in alias_tokens:
                for start in range(len(tokens) - len(needle) + 1):
                    if not used[start] and _at(tokens, needle, start):
                        hit = (start, needle)
                        break
                if hit:
                    break
            if hit:
                out.brand = name
                for n in range(hit[0], hit[0] + len(hit[1])):
                    used[n] = True
                break

    for n, token in enumerate(tokens):
        if used[n]:
            continue
        slash = _SLASH.match(token)
        if slash:
            first, second = slash.groups()
            if first in VALID_STORAGE and second in VALID_RAM:
                out.storage, out.ram = _storage_text(first), f"RAM {second}GB"
                used[n] = True
            elif first in VALID_RAM and second in VALID_STORAGE:
                out.storage, out.ram = _storage_text(second), f"RAM {first}GB"
                used[n] = True

    for n, token in enumerate(tokens):
        if used[n] or token not in idx.ram_words:
            continue
        if n + 1 < len(tokens) and not used[n + 1] and tokens[n + 1] in VALID_RAM:
            out.ram = f"RAM {tokens[n + 1]}GB"
            used[n] = used[n + 1] = True
            if n + 2 < len(tokens) and not used[n + 2] and tokens[n + 2] in idx.storage:
                used[n + 2] = True

    for n, token in enumerate(tokens):
        if used[n]:
            continue
        if token in ("1", "2") and n + 1 < len(tokens) and not used[n + 1]:
            following = tokens[n + 1]
            if idx.storage.get(following) == "TB" or following in ("tb", "ترا", "ترابایت"):
                out.storage = f"{token}TB"
                used[n] = used[n + 1] = True
                continue
        if not out.storage and token in VALID_STORAGE:
            out.storage = _storage_text(token)
            used[n] = True
            if n + 1 < len(tokens) and not used[n + 1] and tokens[n + 1] in idx.storage:
                used[n + 1] = True

    for key in idx.colors:
        start = _find_free(tokens, used, key.tokens)
        if start is not None:
            out.color = key.value
            for n in range(start, start + len(key.tokens)):
                used[n] = True
            break

    parts = [p for p in (out.accessory, out.model or out.brand, out.storage, out.ram, out.color)
             if p]
    out.formatted = " | ".join(parts) if parts else UNKNOWN
    out.confidence = "high" if out.model else "medium" if out.accessory or out.brand else "low"
    return out


# ---- what staff taught it ---------------------------------------------------------------------
def load_learned(db) -> tuple[_Alias, ...]:
    with db._lock:
        rows = db._fetchall("SELECT alias, model, brand FROM product_alias_learned")
    out = []
    for row in rows:
        tokens = tuple(str(row["alias"]).split())
        if tokens:
            out.append(_Alias(str(row["model"]), str(row["brand"]), tokens,
                              len(str(row["alias"]).replace(" ", ""))))
    return tuple(out)


def learn(db, text: str, model: str, actor: str) -> dict:
    """Keep ``text`` as another name of ``model``. ValueError: unknown model or an empty text."""
    brand = index().by_model.get(model)
    alias = normalize(text)
    if brand is None or not alias:
        raise ValueError("unknown model or empty text")
    with db._lock:
        db._conn.execute(
            "INSERT INTO product_alias_learned (alias, model, brand, created_by, created_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(alias) DO UPDATE SET model=excluded.model, "
            "brand=excluded.brand, created_by=excluded.created_by, created_at=excluded.created_at",
            (alias, model, brand, actor[:100], now_iso()))
        db._commit()
    return {"alias": alias, "model": model, "brand": brand}


def model_names() -> list[str]:
    return sorted(index().by_model)
