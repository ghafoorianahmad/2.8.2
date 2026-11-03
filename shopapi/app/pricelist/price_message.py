"""v2.18.0: what a text post of a price channel says (port of the reference parser, RULES.md of
the price parser bundle; all 85 cases of tests/data/price_messages_tests.json pass).

``parse(message, context_brand)`` -> status applied / uncertain / ignored, the items and, for a
brand header, the brand the following posts belong to. Pure text: no imports from the app.

Every pattern is ASCII-mode: JavaScript's ``\\b`` and ``\\d`` know only ASCII, and these rules
were written and tested with that meaning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

APPLIED = "applied"
UNCERTAIN = "uncertain"
IGNORED = "ignored"

VALID_STORAGE_GB = frozenset({32, 64, 128, 256, 512, 1024, 2048})
VALID_RAM_GB = frozenset({2, 3, 4, 6, 8, 12, 16, 24})
#: flagships posted as colors without a storage number
MULTI_COLOR_DEFAULT_MODELS = frozenset({"S23 FE", "S24 FE", "S25 FE", "S24 Ultra", "S25 Ultra",
                                        "S24", "S25", "Magic 6 Pro", "Magic 7 Pro"})


def _rx(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(pattern, re.ASCII | flags)


_I = re.IGNORECASE

COLORS = (
    ("Ice Blue", (r"\bice\s*blue\b", r"آبی\s*یخی", r"یخی")),
    ("Sky Blue", (r"\bsky\s*blue\b", r"آبی\s*آسمانی")),
    ("Jet", (r"\bjet(?:\s*black)?\b", r"مشکی\s*جت", r"\bجت\b")),
    ("Navy", (r"\bnavy(?:\s*blue)?\b", r"سرمه\s*ای", r"سرمه", r"\bناوی\b")),
    ("Desert", (r"\bdesert(?:\s*titanium)?\b", r"\bdesret\b", r"صحرایی", r"دیزرت", r"دزرت")),
    ("Natural", (r"\bnatural(?:\s*titanium)?\b", r"تیتانیوم\s*طبیعی", r"نچرال", r"طبیعی")),
    ("Titanium", (r"\btitani[uo]m\b", r"تیتانیوم")),
    ("Ultramarine", (r"\bultramarine\b", r"لاجوردی")),
    ("Starlight", (r"\bstarlight\b", r"استارلایت")),
    ("Midnight", (r"\bmidnight\b", r"میدنایت")),
    ("Graphite", (r"\bgraphite\b", r"نوک\s*مدادی", r"گرافیت")),
    ("Mint", (r"\bmint\b", r"سبز\s*نعنایی", r"نعنایی")),
    ("Teal", (r"\bteal\b", r"سبز\s*آبی", r"کله\s*غازی")),
    ("Lavender", (r"\blavender\b", r"یاسی")),
    ("Pink", (r"\brose\s*gold\b", r"\bpink\b", r"رز\s*گلد", r"رزگلد", r"صورتی")),
    ("Black", (r"\bblac?k\b", r"\bblk\b", r"مشکی", r"سیاه")),
    ("White", (r"\bwh?ite\b", r"سفید")),
    ("Blue", (r"\bblue\b", r"آبی", r"\bابی\b")),
    ("Green", (r"\bgreen\b", r"سبز")),
    ("Gold", (r"\bgold\b", r"طلایی")),
    ("Silver", (r"\bsilver\b", r"نقره\s*ای", r"سیلور")),
    ("Gray", (r"\bgr[ae]y\b", r"خاکستری", r"طوسی")),
    ("Purple", (r"\bpurple\b", r"\bviolet\b", r"بنفش")),
    ("Yellow", (r"\byellow\b", r"\blemon\b", r"لیمویی", r"زرد")),
    ("Orange", (r"\borange\b", r"نارنجی")),
    ("Red", (r"\bred\b", r"قرمز")),
    ("Bronze", (r"\bbronze\b", r"برنز", r"مسی")),
)
_COLOR_RX = tuple((name, tuple(_rx(p, _I) for p in patterns)) for name, patterns in COLORS)

_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "‌": " ", " ": " "})
_DECORATION = re.compile(
    "[\U0001f300-\U0001faff☀-➿︀-️‍•▪▫◾◽⬅⭐✅✔❌❎✨⚡⚫⚪⚠]+")
_DIVIDERS = _rx(r"[=*_~]{2,}")
_DASHES = _rx(r"-{2,}")
_SLASH_PAIR = _rx(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b(?!\s*\.\d)")
_PRICE = _rx(r"(?:^|[^\d.])(\d{1,3})\.(\d{3})(?!\.\d|\d)")
PRICE_MIN, PRICE_MAX = 5000, 999999


def _title(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def normalize_text(raw: str) -> str:
    value = str(raw or "").translate(_DIGITS).translate(_LETTERS)
    value = _DECORATION.sub(" ", value)
    value = _DIVIDERS.sub(" ", value)
    value = _DASHES.sub(" ", value)

    def pair(match: re.Match) -> str:
        a, b = int(match.group(1)), int(match.group(2))
        if a <= 2048 and b <= 2048 and (a in VALID_STORAGE_GB or b in VALID_STORAGE_GB
                                        or a in VALID_RAM_GB or b in VALID_RAM_GB):
            if 1400 <= a <= 1410:      # a year, not a capacity
                return match.group(0)
            return f"{a}-{b}"
        return match.group(0)

    value = _SLASH_PAIR.sub(pair, value)
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


_BRANDS = (
    ("Poco", _rx(r"\b(?:poco|poko)\b|پوکو|پکو", _I)),
    ("Redmi", _rx(r"\b(?:redmi|redmy|redmii)\b|ردمیی|ردمی", _I)),
    ("TCH", _rx(r"\b(?:tch|t\.c\.h)\b|تی\s*سی\s*اچ|تیسی\s*اچ", _I)),
    ("Samsung", _rx(r"\b(?:samsung|samsong|galaxy)\b|سامسونگ|سامسنگ|گلکسی", _I)),
    ("Apple", _rx(r"\b(?:apple|aple|iphone|iphon)\b|آیفون|ایفون|آیفن|\bاپل\b", _I)),
    ("Honor", _rx(r"\b(?:honor|honer|honnor)\b|آنر|هانر|\bانر\b", _I)),
    ("Xiaomi", _rx(r"\b(?:xiaomi|xiamo|xiomi|shiaomi)\b|شیائومی|شیاومی|شیامی", _I)),
)
CANONICAL_BRANDS = ("Samsung", "Apple", "Xiaomi", "Redmi", "Poco", "Honor", "TCH")


def detect_brand(text: str) -> str | None:
    for name, pattern in _BRANDS:
        if pattern.search(text):
            return name
    return None


def normalize_context_brand(brand: str | None) -> str | None:
    if not brand:
        return None
    found = detect_brand(normalize_text(brand))
    if found:
        return found
    trimmed = brand.strip().lower()
    return next((name for name in CANONICAL_BRANDS if name.lower() == trimmed), None)


_HEADER_CUE = _rx(r"لیست\s*قیمت|لیست\s*محصولات|محصولات\s*برند|برند|قیمت\s*روز|price\s*list|brand", _I)


def _brand_header(text: str) -> str | None:
    brand = detect_brand(text)
    if not brand or _PRICE.search(text):
        return None
    return brand if _HEADER_CUE.search(text) or len(text.split()) <= 5 else None


_DATE_MARKS = (
    _rx(r"\b140\d[./-]\d{1,2}[./-]\d{1,2}\b"), _rx(r"\b202\d[./-]\d{1,2}[./-]\d{1,2}\b"),
    _rx(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", _I),
    _rx(r"(?:یکشنبه|دوشنبه|سه\s*شنبه|چهارشنبه|پنجشنبه|جمعه|\bشنبه\b)"),
)


def _is_date(text: str) -> bool:
    return any(p.search(text) for p in _DATE_MARKS) and not _PRICE.search(text)


@dataclass
class _Model:
    brand: str | None
    model: str | None
    needs_context: bool
    ambiguous: bool
    rest: str


def _found(brand, model, working: str, match_text: str, *, needs_context: bool = False) -> _Model:
    return _Model(brand, model, needs_context, False, working.replace(match_text, " ", 1))


_SUFFIXES = (
    (_rx(r"پرو\s*مکس|پرومکس"), " Pro Max "), (_rx(r"\bpromax\b", _I), " Pro Max "),
    (_rx(r"پرو\s*پلاس"), " Pro Plus "), (_rx(r"\bpro\s*\+", _I), " Pro Plus "),
    (_rx(r"پرو"), " Pro "), (_rx(r"اولترا|الترا|\butra\b", _I), " Ultra "),
    (_rx(r"پلاس"), " Plus "), (_rx(r"اف\s*ای"), " FE "), (_rx(r"لایت"), " Lite "),
    (_rx(r"نوت"), " Note "), (_rx(r"مجیک"), " Magic "), (_rx(r"نرمال|عادی|\bnormal\b", _I), " "),
)
_BRAND_WORDS = (
    _rx(r"\b(?:samsung|samsong|galaxy|apple|aple|iphone|iphon|xiaomi|xiamo|xiomi|shiaomi|redmi|redmy"
        r"|redmii|poco|poko|honor|honer|honnor|tch|t\.c\.h)\b", _I),
    _rx(r"تی\s*سی\s*اچ|تیسی\s*اچ|سامسونگ|سامسنگ|گلکسی|آیفون|ایفون|آیفن|اپل|شیائومی|شیاومی|شیامی|ردمیی"
        r"|ردمی|پوکو|پکو|آنر|هانر|\bانر\b"),
    _rx(r"گوشی\s*موبایل|گوشی|موبایل|محصولات|محصول|مدل|\bmodel\b", _I),
)
_Z = _rx(r"\b(z\s*(?:fold|flip)\s*[456])\b", _I)
_S = _rx(r"\b(s\s*2[2345])(?:\s*(fe|ultra|plus|\+))?\b", _I)
_ONE = _rx(r"\b(one(?:\s*(?:pro|plus))?)\b", _I)
_Z1 = _rx(r"\b(z1(?:\s*pro)?|s1|t10|a10|a20)\b", _I)
_AM = _rx(r"\b([am]\s*[012357]\d\s*s?)(?:\s*5g|\s*4g)?\b", _I)
_POCO = _rx(r"\b([cmxf]\s*[567]\d?)(?:\s*(pro|plus|\+))?(?:\s*5g|\s*4g)?\b", _I)
_NOT_POCO = _rx(r"\bx[56789][abc]\b", _I)
_POCO_BASE = _rx(r"^(?:C65|C75|M5|M6|X5|X6|X7|F5|F6)$")
_HONOR_X = _rx(r"\b(x\s*[56789]\s*(?:[abc]|plus))\b", _I)
_MAGIC = _rx(r"\b(magic\s*(?:[567](?:\s*(?:pro|lite))?|v[23]))\b", _I)
_200 = _rx(r"\b(200)(?:\s*(pro|lite))?\b", _I)
_90 = _rx(r"\b(90)(?:\s*(lite|pro))?\b", _I)
_NOTE = _rx(r"\b(note\s*1[234]\s*s?)(?:\s*(pro(?:\s*plus|\s*\+)?))?(?:\s*(4g|5g))?"
            r"(?:\s*(pro(?:\s*plus|\s*\+)?))?\b", _I)
_REDMI = _rx(r"\b(1[234]\s*c|a3x?|turbo\s*3)\b", _I)
_T = _rx(r"\b(1[345]\s*t)(?:\s*(pro))?\b", _I)
_MIX = _rx(r"\b(mix\s*(?:flip|fold\s*\d))\b", _I)
_XI_ULTRA = _rx(r"\b(1[345])\s*ultra\b", _I)
_SE = _rx(r"\b(se(?:\s*202[024])?)\b", _I)
_NUM = _rx(r"\b(1[123456]\s*e?)(?:\s*(pro\s*max|pro|plus|\+))?(?!\s*-\s*\d)\b", _I)
_AFTER_DASH = _rx(r"-\s*$")
_APPLE_WORDS = _rx(r"iphone|آیفون|ایفون|اپل", _I)
_APPLE_REGION = _rx(r"\b(?:ch/a|ch|zaa|za/a|ja|ll/a|hn/a)\b", _I)
_HYPHEN_RAM = _rx(r"\b(?:128|256|512)\s*-\s*(?:8|12|16)\b")
_DANGLING = _rx(r"\b(?:pro\s*max|ultra|note(?:\s*pro)?|pro|plus|fe)\b", _I)


def _number_model(text: str) -> re.Match | None:
    """11..16: not the second half of a pair (the reference's ``(?<!-\\s*)``, which Python's
    fixed-width lookbehind cannot say)."""
    start = 0
    while True:
        match = _NUM.search(text, start)
        if match is None or not _AFTER_DASH.search(text[:match.start()]):
            return match
        start = match.start() + 1


def _extract_model(segment: str, explicit: str | None, context: str | None) -> _Model:
    working = segment
    for pattern, replacement in _SUFFIXES:
        working = pattern.sub(replacement, working)
    for pattern in _BRAND_WORDS:
        working = pattern.sub(" ", working)
    effective = explicit or context

    m = _Z.search(working)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        name = re.sub(r"^z", "Z", name, flags=_I)
        name = re.sub("fold", "Fold", name, count=1, flags=_I)
        name = re.sub("flip", "Flip", name, count=1, flags=_I)
        return _found("Samsung", name, working, m.group(0))

    m = _S.search(working)
    if m:
        base = re.sub(r"\s+", "", m.group(1)).upper()
        suffix = {"fe": " FE", "ultra": " Ultra", "plus": " Plus", "+": " Plus"}.get(
            (m.group(2) or "").lower(), "")
        return _found("Samsung", base + suffix, working, m.group(0))

    m = _ONE.search(working)
    if m:
        name = " ".join(_title(w) for w in m.group(1).split())
        return _found("TCH" if "TCH" in (effective, explicit) else None, name, working, m.group(0),
                      needs_context=True)
    m = _Z1.search(working)
    if m:
        name = " ".join(w.upper() if re.search(r"\d", w) else _title(w) for w in m.group(1).split())
        return _found("TCH" if "TCH" in (effective, explicit) else None, name, working, m.group(0),
                      needs_context=True)

    m = _AM.search(working)
    if m:
        clean = re.sub(r"\s+", "", m.group(1))
        return _found("Samsung", _title(clean), working, m.group(0))

    m = _POCO.search(working)
    if m and not _NOT_POCO.search(m.group(0)):
        base = re.sub(r"\s+", "", m.group(1)).upper()
        if _POCO_BASE.match(base):
            suffix = (" Pro" if m.group(2).lower() == "pro" else " Plus") if m.group(2) else ""
            return _found("Poco", base + suffix, working, m.group(0))

    m = _HONOR_X.search(working)
    if m:
        raw = m.group(1).strip()
        if re.search("plus", raw, _I):
            name = re.sub(r"^x", "X", re.sub(r"\s*plus", " Plus", raw, count=1, flags=_I), flags=_I)
        else:
            name = "X" + re.sub(r"\s+", "", raw)[1:].lower()
        return _found("Honor", name, working, m.group(0))
    m = _MAGIC.search(working)
    if m:
        name = " ".join(w.upper() if re.fullmatch(r"v\d", w, _I) else _title(w)
                        for w in m.group(1).split())
        return _found("Honor", name, working, m.group(0))
    m = _200.search(working)
    if m:
        return _found("Honor", "200" + (" " + _title(m.group(2)) if m.group(2) else ""), working,
                      m.group(0))
    m = _90.search(working)
    if m and (effective == "Honor" or m.group(2)):
        return _found("Honor", "90" + (" " + _title(m.group(2)) if m.group(2) else ""), working,
                      m.group(0), needs_context=not m.group(2))

    m = _NOTE.search(working)
    if m:
        number = re.sub(r"note\s*", "", m.group(1), flags=_I).strip().upper()
        pro_raw = m.group(2) or m.group(4) or ""
        pro = (" Pro Plus" if re.search(r"plus|\+", pro_raw, _I) else " Pro") if pro_raw else ""
        net = f" {m.group(3).upper()}" if m.group(3) else ""
        return _found("Redmi", f"Note {number}{pro}{net}", working, m.group(0))
    m = _REDMI.search(working)
    if m:
        raw = m.group(1).strip()
        if re.search("turbo", raw, _I):
            name = "Turbo 3"
        elif re.match("a3", raw, _I):
            name = "A3x" if raw.lower() == "a3x" else "A3"
        else:
            name = re.sub(r"\s+", "", raw).upper()
        return _found("Redmi", name, working, m.group(0))

    m = _T.search(working)
    if m:
        base = re.sub(r"\s+", "", m.group(1)).upper()
        return _found("Xiaomi", base + (" Pro" if m.group(2) else ""), working, m.group(0))
    m = _MIX.search(working)
    if m:
        return _found("Xiaomi", " ".join(_title(w) for w in m.group(1).split()), working, m.group(0))

    m = _XI_ULTRA.search(working)
    if m:
        return _found("Xiaomi", f"{m.group(1)} Ultra", working, m.group(0))
    m = _SE.search(working)
    if m and (effective == "Apple" or _APPLE_WORDS.search(segment)):
        return _found("Apple", "iPhone SE", working, m.group(0))

    m = _number_model(working)
    if m:
        number = re.sub(r"\s+", "", m.group(1)).lower()
        raw = re.sub(r"\s+", " ", m.group(2).lower()) if m.group(2) else ""
        suffix = {"pro max": " Pro Max", "pro": " Pro", "plus": " Plus", "+": " Plus"}.get(raw, "")
        apple_region = bool(_APPLE_REGION.search(segment))
        if (effective == "Xiaomi" and number in ("14", "15")
                and suffix not in (" Pro Max", " Plus")):
            return _found("Xiaomi", number + suffix, working, m.group(0))
        if effective == "Redmi" and number in ("12", "13") and not suffix:
            return _found("Redmi", number, working, m.group(0))
        if (effective == "Apple" or apple_region or number in ("16", "16e")
                or suffix in (" Pro Max", " Plus")
                or (number in ("13", "14", "15") and suffix == " Pro")):
            return _found("Apple", f"iPhone {number}{suffix}", working, m.group(0))
        if _HYPHEN_RAM.search(segment) and number in ("14", "15"):
            return _found("Xiaomi", number + suffix, working, m.group(0))
        return _found("Apple", f"iPhone {number}{suffix}", working, m.group(0))

    if _DANGLING.search(working):
        return _Model(effective, None, False, True, _DANGLING.sub(" ", working))
    return _Model(effective, None, False, False, working)


_NOT_CAPACITY = (
    (_rx(r"گارانتی\s*\d+\s*ماهه"), " "), (_rx(r"\b[12]\s*سیم(?:\s*کارت)?"), " "),
    (_rx(r"دو\s*سیم(?:\s*کارت)?|تک\s*سیم"), " "), (_rx(r"\b(?:5g|4g)\b", _I), " "),
)
_TB = _rx(r"\b([12])\s*(?:tb|ترابایت)\b", _I)
_ONE_TB = _rx(r"یک\s*ترابایت")
_RAM = _rx(r"(?:رم|\bram\b)\s*:?\s*(\d{1,3})(?:\s*(?:گیگابایت|گیگ|gb|g))?", _I)
_STORAGE = _rx(r"(?:ظرفیت|حافظه|\bstorage\b|\brom\b)\s*:?\s*(\d{1,4})(?:\s*(?:گیگابایت|گیگ|gb|g))?", _I)
_PAIR = _rx(r"\b(\d{1,4})\s*-\s*(\d{1,4})(?:\s*(?:gb|g|گیگابایت|گیگ))?\b", _I)
_ALONE = _rx(r"\b(\d{1,4})(?:\s*(?:gb|g|گیگابایت|گیگ))?\b", _I)


@dataclass
class _Capacity:
    storage: int | None = None
    ram: int | None = None
    bad: bool = False
    rest: str = ""


def _extract_capacity(text: str) -> _Capacity:
    out = _Capacity()
    working = text
    for pattern, replacement in _NOT_CAPACITY:
        working = pattern.sub(replacement, working)

    def terabyte(match: re.Match) -> str:
        out.storage = int(match.group(1)) * 1024
        return " "

    working = _TB.sub(terabyte, working)
    if _ONE_TB.search(working):
        out.storage = 1024
        working = _ONE_TB.sub(" ", working)

    m = _RAM.search(working)
    if m:
        value = int(m.group(1))
        if value in VALID_RAM_GB:
            out.ram = value
        else:
            out.bad = True
        working = working.replace(m.group(0), " ", 1)

    m = _STORAGE.search(working)
    if m:
        value = int(m.group(1))
        if value in VALID_STORAGE_GB:
            out.storage = value
        else:
            out.bad = True
        working = working.replace(m.group(0), " ", 1)

    m = _PAIR.search(working)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        a_store, b_store = a in VALID_STORAGE_GB, b in VALID_STORAGE_GB
        a_ram, b_ram = a in VALID_RAM_GB, b in VALID_RAM_GB
        if a_store and b_store:
            out.storage = None
            out.bad = True
        elif a_store and b_ram:
            out.storage, out.ram = a, b
        elif b_store and a_ram:
            out.storage, out.ram = b, a
        else:
            if a_store:
                out.storage = a
            if b_store:
                out.storage = b
            if a_ram:
                out.ram = a
            if b_ram:
                out.ram = b
            out.bad = True
        working = working.replace(m.group(0), " ", 1)

    alone = list(_ALONE.finditer(working))
    if alone:
        numbers = [int(m.group(1)) for m in alone]
        for m in alone:
            working = working.replace(m.group(0), " ", 1)
        if len(numbers) >= 2:
            n1, n2 = numbers[0], numbers[1]
            if n1 in VALID_STORAGE_GB and n2 in VALID_STORAGE_GB:
                out.storage = None
                out.bad = True
            elif n1 in VALID_STORAGE_GB and n2 in VALID_RAM_GB:
                out.storage = n1 if out.storage is None else out.storage
                out.ram = n2 if out.ram is None else out.ram
            elif n2 in VALID_STORAGE_GB and n1 in VALID_RAM_GB:
                out.storage = n2 if out.storage is None else out.storage
                out.ram = n1 if out.ram is None else out.ram
            else:
                out.bad = True
        else:
            n = numbers[0]
            if n in VALID_STORAGE_GB:
                if out.storage is not None and out.storage != n:
                    out.storage = None
                    out.bad = True
                else:
                    out.storage = n
            else:
                out.bad = True
    out.rest = working
    return out


def extract_color(text: str) -> str | None:
    """The canonical English color named in ``text`` (Persian or English), or None."""
    for name, patterns in _COLOR_RX:
        if any(p.search(text) for p in patterns):
            return name
    return None


@dataclass
class Item:
    brand: str | None
    model: str | None
    storage_gb: int | None
    ram_gb: int | None
    color: str | None
    price: int

    def as_dict(self) -> dict:
        return {"brand": self.brand, "model": self.model, "storage_gb": self.storage_gb,
                "ram_gb": self.ram_gb, "color": self.color, "price": self.price}


@dataclass
class Parsed:
    status: str
    items: list[Item] = field(default_factory=list)
    context_brand: str | None = None     # a brand header: the following posts are this brand's
    is_correction: bool = False


_HAS_TEXT = _rx("[a-zA-Z0-9؀-ۿ]")
_CORRECTION = _rx(r"اصلاحیه|ویرایش\s*قیمت")
_CORRECTION_WORDS = (
    _rx(r"#?\s*اصلاحیه(?:\s*قیمت)?(?:\s*جدید)?\s*:?"), _rx(r"ویرایش\s*قیمت\s*:?"),
    _rx(r"قیمت\s*جدید\s*:?"),
)
_TRAILING_LABEL = _rx(r"(?:قیمت(?:\s*جدید)?|فی)\s*:?\s*$")
_CURRENCY = _rx(r"(?:هزار\s*)?تومان|\bت\b")


def parse(message: str, context_brand: str | None = None) -> Parsed:
    context = normalize_context_brand(context_brand)
    norm = normalize_text(message)
    if not norm or not _HAS_TEXT.search(norm):
        return Parsed(IGNORED)

    is_correction = False
    content = norm
    if _CORRECTION.search(content):
        is_correction = True
        for pattern in _CORRECTION_WORDS:
            content = pattern.sub(" ", content)
        content = content.strip()

    header = _brand_header(content)
    if header:
        return Parsed(IGNORED, context_brand=header, is_correction=is_correction)
    if _is_date(content):
        return Parsed(IGNORED, is_correction=is_correction)

    prices = []
    for match in _PRICE.finditer(content):
        value = int(match.group(1) + match.group(2))
        if PRICE_MIN <= value <= PRICE_MAX:
            prices.append((match.start(1), match.end(), value))
    if not prices:
        return Parsed(IGNORED, is_correction=is_correction)

    message_brand = detect_brand(content)
    items: list[Item] = []
    uncertain = False
    shared_brand = message_brand or context
    shared_model = shared_storage = shared_ram = None
    shared_ambiguous = False
    cursor = 0
    for index, (start, end, price) in enumerate(prices):
        spec = content[cursor:start]
        cursor = end
        spec = _CURRENCY.sub(" ", _TRAILING_LABEL.sub(" ", spec)).strip()
        chunk_brand = detect_brand(spec)
        model = _extract_model(spec, chunk_brand or (message_brand if index == 0 else None),
                               shared_brand or context)
        capacity = _extract_capacity(model.rest)
        color = extract_color(capacity.rest)
        if model.model is not None:
            brand = model.brand
            if model.needs_context:
                brand = chunk_brand or message_brand or context
            shared_brand, shared_model = brand, model.model
            shared_storage, shared_ram = capacity.storage, capacity.ram
            shared_ambiguous = capacity.bad or model.ambiguous or brand is None
            items.append(Item(brand, shared_model, shared_storage, shared_ram, color, price))
            uncertain = uncertain or shared_ambiguous
        elif index > 0 and shared_model is not None and not model.ambiguous:
            storage = capacity.storage if capacity.storage is not None else shared_storage
            if capacity.storage is not None:
                ram = capacity.ram
            else:
                ram = capacity.ram if capacity.ram is not None else shared_ram
            items.append(Item(shared_brand, shared_model, storage, ram, color, price))
            uncertain = uncertain or shared_ambiguous or capacity.bad
        else:
            uncertain = True
            items.append(Item(chunk_brand or message_brand or context, None, capacity.storage,
                              capacity.ram, color, price))

    breakdown = len(items) >= 2 and all(
        it.color is not None and it.model is not None and it.model == items[0].model
        for it in items)
    for item in items:
        if item.brand is None or item.model is None:
            uncertain = True
        if item.storage_gb is None and not breakdown and not (
                item.model in MULTI_COLOR_DEFAULT_MODELS and item.color is not None):
            uncertain = True
    return Parsed(UNCERTAIN if uncertain else APPLIED, items, is_correction=is_correction)
