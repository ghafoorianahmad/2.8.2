"""v2.11.0: the site's data as plain Python (no Qt, no network) — tested alone.

* **Working data** (``site_data.json`` in ShopAdmin's data folder): brands and
  items (phones and accessories) with colours, specs, photos and «پنهان».
* **Seed**: the site's own ``assets/products.js`` + the photo map of
  ``assets/site.js`` are read as data (a small JS-literal reader; nothing is
  ever executed).
* **catalog.json** (format ``asr-catalog`` version 1, read by ``site.js``): only
  visible items; never a price (the label must not hold a digit), an accounting
  code, a customer or a key.
* **Preview**: what the site would show differently compared with what was
  published last (or, before the first publish, with the site as it was read).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

FORMAT = "asr-catalog"
VERSION = 1
DATA_FORMAT = "shopadmin-site"
IMAGES_PREFIX = "images/"
#: where the site reads the file (inside the site repository)
SITE_CATALOG_DIR = "assets/catalog"

KIND_PHONE = "phone"
KIND_ACCESSORY = "accessory"
DEFAULT_PRICE_STATE = "استعلام قیمت"
DEFAULT_BRANDS = (
    {"key": "apple", "name": "Apple", "tagline": ""},
    {"key": "samsung", "name": "Samsung", "tagline": ""},
    {"key": "xiaomi", "name": "Xiaomi", "tagline": ""},
)
#: accessory groups the site has an icon for, with their Persian names
GROUPS = {"case": "قاب و کاور", "charger": "شارژر و کابل", "headphones": "هدفون و هندزفری",
          "powerbank": "پاوربانک", "other": "سایر لوازم جانبی"}
TIERS = ("پرچمدار", "میان‌رده", "اقتصادی", "پرفروش")

CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
CODE_MAX = 62
IMAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}\.(?:jpg|jpeg|png|webp)$")
BRAND_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DIGITS = re.compile(r"[0-9۰-۹٠-٩]")
MAX_SOURCE_CHARS = 3_000_000
MAX_COLORS = 12
MAX_SPECS = 20


def valid_code(code) -> bool:
    return isinstance(code, str) and len(code) <= CODE_MAX and bool(CODE_RE.match(code))


def code_from_name(name: str, taken: set[str] | None = None) -> str:
    """``Galaxy S26 Ultra`` -> ``galaxy-s26-ultra`` (never one in ``taken``)."""
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    base = "-".join(w.lower() for w in words)[:50].strip("-")
    if not base or not base[0].isalpha():
        base = "item-" + base if base else "item"
    taken = taken or set()
    code, n = base, 2
    while code in taken:
        code = f"{base}-{n}"
        n += 1
    return code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- reading the site's own files (data only) ------------------------------------------
class JsLiteralError(ValueError):
    """The text is not the plain object literal the site's files contain."""


_WS = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)+", re.S)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_ESCAPES = {"n": "\n", "t": "\t", "r": "", "\\": "\\", '"': '"', "'": "'", "/": "/", "\n": ""}


def _skip(text: str, i: int) -> int:
    match = _WS.match(text, i)
    return match.end() if match else i


def _string(text: str, i: int) -> tuple[str, int]:
    quote, out, i = text[i], [], i + 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            nxt = text[i + 1:i + 2]
            if nxt == "u":
                try:
                    out.append(chr(int(text[i + 2:i + 6], 16)))
                except ValueError:
                    raise JsLiteralError("bad escape") from None
                i += 6
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        if char == quote:
            return "".join(out), i + 1
        if char == "\n":
            break
        out.append(char)
        i += 1
    raise JsLiteralError("unterminated string")


def read_js_value(text: str, i: int = 0, depth: int = 0):
    """(value, end) of the JS object / array / string / number literal at ``i``.
    Only plain literals: anything else (a call, an expression) is refused."""
    if depth > 24:
        raise JsLiteralError("too deep")
    i = _skip(text, i)
    char = text[i:i + 1]
    if char in ("{", "["):
        closing = "}" if char == "{" else "]"
        result: dict | list = {} if char == "{" else []
        i += 1
        while True:
            i = _skip(text, i)
            if text[i:i + 1] == closing:
                return result, i + 1
            if isinstance(result, dict):
                if text[i:i + 1] in ("'", '"'):
                    key, i = _string(text, i)
                else:
                    match = _IDENT.match(text, i) or _NUMBER.match(text, i)
                    if not match:
                        raise JsLiteralError(f"bad key at {i}")
                    key, i = match.group(0), match.end()
                i = _skip(text, i)
                if text[i:i + 1] != ":":
                    raise JsLiteralError(f"':' expected at {i}")
                value, i = read_js_value(text, i + 1, depth + 1)
                result[key] = value
            else:
                value, i = read_js_value(text, i, depth + 1)
                result.append(value)
            i = _skip(text, i)
            if text[i:i + 1] == ",":
                i += 1
            elif text[i:i + 1] != closing:
                raise JsLiteralError(f"',' expected at {i}")
    if char in ("'", '"'):
        return _string(text, i)
    match = _NUMBER.match(text, i)
    if match:
        number = match.group(0)
        return (float(number) if "." in number else int(number)), match.end()
    match = _IDENT.match(text, i)
    if match and match.group(0) in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[match.group(0)], match.end()
    raise JsLiteralError(f"not a literal at {i}")


def extract_assignment(text: str, name: str):
    """The literal assigned to ``const|let|var <name> =`` in a script, or None."""
    match = re.search(r"(?:const|let|var)\s+" + re.escape(name) + r"\s*=\s*", text or "")
    if not match:
        return None
    value, _end = read_js_value(text, match.end())
    return value


def parse_site_files(products_js: str, site_js: str = "") -> dict:
    """The site's built-in catalogue as working data: ``{"brands", "items"}``.
    Photo file names follow the site's ``assets/products`` names."""
    if len(products_js or "") > MAX_SOURCE_CHARS or len(site_js or "") > MAX_SOURCE_CHARS:
        raise JsLiteralError("file too large")
    catalog = extract_assignment(products_js, "CATALOG")
    if not isinstance(catalog, dict):
        raise JsLiteralError("CATALOG not found")
    photos = swatch = None
    if site_js:
        try:
            photos = extract_assignment(site_js, "PRODUCTS_WITH_COLOR_PHOTOS")
            swatch = extract_assignment(site_js, "SWATCH")
        except JsLiteralError:
            photos = swatch = None
    photos = photos if isinstance(photos, dict) else {}
    swatch = swatch if isinstance(swatch, dict) else {}
    brands, items = [], []
    for key, brand in catalog.items():
        if not isinstance(brand, dict) or not BRAND_KEY_RE.match(str(key)):
            continue
        brands.append({"key": key, "name": text(brand.get("name"), 40) or key.title(),
                       "tagline": text(brand.get("tagline"), 120)})
        for raw in brand.get("items") or []:
            if not isinstance(raw, dict) or not valid_code(raw.get("id")):
                continue
            code = raw["id"]
            slugs = photos.get(code) if isinstance(photos.get(code), list) else []
            colors = []
            for n, name in enumerate(raw.get("colors") or []):
                photo = slugs[n] if n < len(slugs) and slugs[n] else ""
                colors.append({"name": name, "image": f"{code}-{photo}.jpg" if photo else "",
                               "hex": swatch.get(name, "") if isinstance(name, str) else ""})
            spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
            accessory = str(raw.get("kind") or raw.get("category") or "").lower().startswith(
                ("acc", "لوازم")) or key.startswith("acc")
            items.append(clean_item({
                "code": code, "category": KIND_ACCESSORY if accessory else KIND_PHONE,
                "brand": key, "name": raw.get("name"), "tier": raw.get("tier"),
                "release_year": raw.get("releaseYear"), "price_state": raw.get("priceState"),
                "aliases": raw.get("aliases") or [], "specs": [[k, v] for k, v in spec.items()],
                "colors": colors, "image": f"{code}.jpg", "group": raw.get("group"),
            }))
    return {"brands": brands, "items": [i for i in items if i["name"]]}


def items_from_catalog(catalog: dict) -> dict:
    """A published catalog.json back to working data (another computer, or
    after a restore): ``{"brands", "items"}``. Photo names lose ``images/``."""
    if not isinstance(catalog, dict) or catalog.get("format") != FORMAT:
        raise JsLiteralError("not a site catalog")

    def bare(path) -> str:
        path = str(path or "")
        return path[len(IMAGES_PREFIX):] if path.startswith(IMAGES_PREFIX) else ""

    items = []
    for raw in catalog.get("items") or []:
        if not isinstance(raw, dict):
            continue
        items.append(clean_item({**raw, "image": bare(raw.get("image")),
                                 "colors": [{**c, "image": bare(c.get("image"))}
                                            for c in raw.get("colors") or [] if isinstance(c, dict)]}))
    brands = [b for b in catalog.get("brands") or []
              if isinstance(b, dict) and BRAND_KEY_RE.match(str(b.get("key") or ""))]
    return {"brands": brands, "items": [i for i in items if i["code"] and i["name"]]}


# ---- one item ------------------------------------------------------------------------------
def text(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def image_name(value) -> str:
    name = str(value or "").strip().lower()
    return name if IMAGE_NAME_RE.match(name) else ""


def clean_item(raw: dict | None) -> dict:
    """A valid item (unknown fields dropped, lengths capped). A price label with
    a digit is replaced: the site never shows a price."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        year = int(raw.get("release_year") or 0)
    except (TypeError, ValueError):
        year = 0
    price_state = text(raw.get("price_state"), 30)
    if not price_state or _DIGITS.search(price_state):
        price_state = DEFAULT_PRICE_STATE
    colors = []
    for color in (raw.get("colors") or [])[:MAX_COLORS]:
        if not isinstance(color, dict) or not text(color.get("name"), 40):
            continue
        hex_value = str(color.get("hex") or "")
        colors.append({"name": text(color.get("name"), 40), "image": image_name(color.get("image")),
                       "hex": hex_value.lower() if HEX_RE.match(hex_value) else ""})
    specs = []
    for row in (raw.get("specs") or [])[:MAX_SPECS]:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            key, value = text(row[0], 40), text(row[1], 160)
            if key and value:
                specs.append([key, value])
    category = KIND_ACCESSORY if raw.get("category") == KIND_ACCESSORY else KIND_PHONE
    group = str(raw.get("group") or "")
    brand = str(raw.get("brand") or "").lower()
    code = str(raw.get("code") or "")
    return {
        "code": code if valid_code(code) else "",
        "category": category,
        "brand": brand if BRAND_KEY_RE.match(brand) else "",
        "brand_name": text(raw.get("brand_name"), 40),
        "name": text(raw.get("name"), 120),
        "tier": text(raw.get("tier"), 30),
        "release_year": year if 2000 <= year <= 2100 else None,
        "price_state": price_state,
        "aliases": [text(a, 80) for a in (raw.get("aliases") or []) if text(a, 80)][:30],
        "specs": specs,
        "colors": colors,
        "image": image_name(raw.get("image")),
        "group": (group if group in GROUPS else "other") if category == KIND_ACCESSORY else "",
        "description": text(raw.get("description"), 600) if category == KIND_ACCESSORY else "",
        "hidden": bool(raw.get("hidden")),
    }


def item_problems(item: dict, brand_keys: set[str]) -> list[str]:
    """Why an item cannot be saved (Persian, for the form)."""
    problems = []
    if not item["name"]:
        problems.append("نام را بنویسید.")
    if not item["code"]:
        problems.append("کد مدل فقط حروف کوچک انگلیسی، عدد و - است (مثلاً galaxy-a57).")
    if item["category"] == KIND_PHONE:
        if item["brand"] not in brand_keys:
            problems.append("برند را انتخاب کنید.")
        if not item["colors"]:
            problems.append("دست‌کم یک رنگ بنویسید.")
    return problems


def image_refs(item: dict) -> list[str]:
    names = [item.get("image") or ""] + [c.get("image") or "" for c in item.get("colors") or []]
    return [n for n in names if n]


# ---- catalog.json --------------------------------------------------------------------------
def build_catalog(data: dict, photos: dict[str, str], *, generator: str = "ShopAdmin") -> dict:
    """catalog.json of the visible items. ``photos``: file name -> sha256 of the
    photos that exist; a missing photo is left out (the site draws the phone)."""
    brand_list = data.get("brands") or list(DEFAULT_BRANDS)
    items, images = [], {}

    def photo(name: str) -> str:
        if not name or name not in photos:
            return ""
        images[IMAGES_PREFIX + name] = photos[name]
        return IMAGES_PREFIX + name

    for raw in data.get("items") or []:
        item = clean_item(raw)
        if item["hidden"] or not item["code"] or not item["name"]:
            continue
        colors = []
        for color in item["colors"]:
            entry = {"name": color["name"]}
            if photo(color["image"]):
                entry["image"] = IMAGES_PREFIX + color["image"]
            if color["hex"]:
                entry["hex"] = color["hex"]
            colors.append(entry)
        out = {"code": item["code"], "brand": item["brand"], "category": item["category"],
               "name": item["name"], "tier": item["tier"],
               "release_year": item["release_year"], "price_state": item["price_state"],
               "aliases": item["aliases"], "specs": item["specs"], "colors": colors}
        card = photo(item["image"])
        if card:
            out["image"] = card
        if item["category"] == KIND_ACCESSORY:
            out["group"] = item["group"]
            if item["brand_name"]:
                out["brand_name"] = item["brand_name"]
            if item["description"]:
                out["description"] = item["description"]
        items.append(out)
    # the time the data last changed: the same data always gives the same file,
    # so publishing twice without a change sends nothing
    return {"format": FORMAT, "version": VERSION,
            "generated_at": str(data.get("updated_at") or now_iso()),
            "generator": generator, "brands": brand_list, "items": items,
            "images": {path: {"sha256": sha} for path, sha in sorted(images.items())}}


def validate_catalog(catalog: dict) -> list[str]:
    """Problems that would make the site refuse the file (Persian; empty = fine).
    The site checks the same rules (``applyCatalog`` in site.js)."""
    problems = []
    if catalog.get("format") != FORMAT or catalog.get("version") != VERSION:
        problems.append("قالب فایل نادرست است")
    items = catalog.get("items") or []
    codes = [i.get("code") for i in items]
    if len(codes) != len(set(codes)):
        problems.append("کد مدل تکراری است")
    for item in items:
        if _DIGITS.search(str(item.get("price_state") or "")):
            problems.append(f"«{item.get('name')}» قیمت دارد")
        for path in [item.get("image")] + [c.get("image") for c in item.get("colors") or []]:
            if path and path not in catalog.get("images", {}):
                problems.append(f"عکس «{path}» نیست")
    brand_keys = {b.get("key") for b in catalog.get("brands") or []}
    if not any(i.get("category") == KIND_PHONE and i.get("brand") in brand_keys
               and i.get("colors") for i in items):
        problems.append("هیچ گوشیِ نمایشی‌ای نیست؛ سایت فهرست قبلی خودش را نشان می‌دهد")
    return problems


def catalog_bytes(catalog: dict) -> bytes:
    return json.dumps(catalog, ensure_ascii=False, indent=1).encode("utf-8")


# ---- preview -------------------------------------------------------------------------------
_FIELDS_FA = (("name", "نام"), ("colors", "رنگ‌ها"), ("specs", "مشخصات"), ("image", "عکس کارت"),
              ("tier", "رده"), ("release_year", "سال"), ("description", "توضیح"),
              ("group", "نوع"), ("aliases", "نام‌های دیگر"))


def snapshot(catalog: dict) -> dict:
    """What matters for the preview: each item and each photo's hash."""
    return {"items": {i["code"]: i for i in catalog.get("items") or []},
            "images": {p: v.get("sha256") for p, v in (catalog.get("images") or {}).items()},
            "brands": catalog.get("brands") or []}


def diff(old: dict | None, new: dict) -> dict:
    """``old`` / ``new``: snapshots. Lists of {code, name, category, fields}."""
    old = old or {"items": {}, "images": {}}
    before, after = old.get("items") or {}, new["items"]
    old_images = old.get("images") or {}
    added = [after[c] for c in after if c not in before]
    removed = [before[c] for c in before if c not in after]
    changed = []
    for code in after:
        if code not in before:
            continue
        fields = [fa for key, fa in _FIELDS_FA
                  if json.dumps(after[code].get(key), sort_keys=True, ensure_ascii=False)
                  != json.dumps(before[code].get(key), sort_keys=True, ensure_ascii=False)]
        photos_changed = any(old_images.get(p) != new["images"].get(p)
                             for p in [after[code].get("image")]
                             + [c.get("image") for c in after[code].get("colors") or []] if p)
        if photos_changed and "عکس‌ها" not in fields:
            fields.append("عکس‌ها")
        if fields:
            changed.append({**after[code], "fields": fields})

    def short(rows):
        return [{"code": r["code"], "name": r.get("name") or r["code"],
                 "category": r.get("category") or KIND_PHONE, "fields": r.get("fields", [])}
                for r in sorted(rows, key=lambda r: r.get("name") or r["code"])]

    new_images = sorted(p for p in new["images"] if p not in old_images)
    changed_images = sorted(p for p in new["images"]
                            if p in old_images and old_images[p] != new["images"][p])
    return {"added": short(added), "removed": short(removed), "changed": short(changed),
            "images_new": new_images, "images_changed": changed_images,
            # v2.12.0: a new brand order alone is a «ظاهر و چیدمان» change, not a text change
            "brands_changed": bool(old.get("brands")) and _by_key(old.get("brands"))
            != _by_key(new.get("brands"))}


def _by_key(brands) -> list:
    return sorted(brands or [], key=lambda b: str(b.get("key")) if isinstance(b, dict) else "")


def has_changes(change: dict) -> bool:
    return any(change[k] for k in ("added", "removed", "changed", "images_new",
                                   "images_changed", "brands_changed"))


def preview_lines(change: dict) -> list[str]:
    """The preview in short Persian lines."""
    def kind(row):
        return "گوشی" if row["category"] == KIND_PHONE else "لوازم جانبی"

    lines = []
    for row in change["added"]:
        lines.append(f"➕ {kind(row)} تازه در سایت: {row['name']}")
    for row in change["removed"]:
        lines.append(f"➖ از سایت برداشته می‌شود: {row['name']}")
    for row in change["changed"]:
        lines.append(f"✎ {row['name']}: {'، '.join(row['fields'])}")
    if change["images_new"] or change["images_changed"]:
        lines.append(f"🖼 عکس تازه: {len(change['images_new'])}، عکس عوض‌شده: "
                     f"{len(change['images_changed'])}")
    if change.get("brands_changed"):
        lines.append("متن برندها عوض می‌شود.")
    return lines or ["نسبت به آنچه اکنون در سایت است تغییری نیست."]


# ---- photos ----------------------------------------------------------------------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def photo_name(code: str, color: str = "", *, n: int = 0) -> str:
    """``iphone-17`` + «مشکی» -> ``iphone-17-c1a2b3.jpg`` (stable per colour)."""
    if not color and not n:
        return f"{code}.jpg"
    if color:
        return f"{code}-c{hashlib.sha1(color.encode('utf-8')).hexdigest()[:6]}.jpg"
    return f"{code}-{n}.jpg"

