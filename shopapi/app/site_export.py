"""v2.10.0 «خروجی کاتالوگ برای سایت»: the site's models, colours, specs and photos
come from ShopSystem as one versioned file (``catalog.json`` + ``images/``).

* **Format** ``asr-catalog`` version 1 (``FORMAT`` / ``VERSION``; the site reads
  only versions it knows and keeps its built-in ``products.js`` otherwise)::

      {"format": "asr-catalog", "version": 1, "generated_at": "...",
       "generator": "ShopSystem 2.10.0",
       "brands": [{"key": "apple", "name": "Apple", "tagline": "..."}],
       "items": [{"code": "iphone-17", "brand": "apple", "category": "phone",
                  "name": "iPhone 17", "tier": "...", "release_year": 2025,
                  "price_state": "استعلام قیمت", "aliases": [...],
                  "specs": [["نمایشگر", "..."]],
                  "colors": [{"name": "مشکی", "image": "images/iphone-17-black.jpg",
                              "hex": "#1b1d22"}],
                  "image": "images/iphone-17.jpg", "group": ""}],
       "images": {"images/iphone-17.jpg": {"sha256": "...", "bytes": 123}}}

  Never in it: prices (``price_state`` is a fixed public label, never a number),
  accounting codes, customers, keys or server addresses.
* **Stored** per model in ``catalog_models.site_data`` (JSON) and the photos in
  ``Settings.site_images_path()``. Seeded once from the site's own files
  (``import_site_files``: ``products.js`` + the photo map of ``site.js``, read as
  data, never executed); afterwards ShopAdmin edits it.
* **Preview** compares the catalogue with the last export (added / changed /
  removed models, new / changed photos, warnings) before anything is written.
* **Export** as a zip (ShopAdmin saves it) or into a folder on the server
  (optional daily schedule, ``export_loop``). Nothing is published from here:
  delivering the files to the live site is the owner's step.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .catalog_models import CatalogModelRepo, split_aliases, valid_slug
from .db_own import OwnDB
from .util import now_iso

logger = logging.getLogger(__name__)

FORMAT = "asr-catalog"
VERSION = 1
IMAGES_PREFIX = "images/"

BRANDS_KEY = "site_export:brands"
SNAPSHOT_KEY = "site_export:snapshot"
LAST_KEY = "site_export:last"
SCHEDULE_KEY = "site_export:schedule"
AUTO_DATE_KEY = "site_export:auto_date"

#: the site's brand pages (a phone of another brand has nowhere to be shown)
DEFAULT_BRANDS = (
    {"key": "apple", "name": "Apple", "tagline": ""},
    {"key": "samsung", "name": "Samsung", "tagline": ""},
    {"key": "xiaomi", "name": "Xiaomi", "tagline": ""},
)
#: accessory groups the site has an icon for
GROUPS = ("case", "charger", "headphones", "powerbank", "other")
KIND_PHONE = "phone"
KIND_ACCESSORY = "accessory"
DEFAULT_PRICE_STATE = "استعلام قیمت"

IMAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}\.(?:jpg|jpeg|png|webp)$")
BRAND_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DIGITS = re.compile(r"[0-9۰-۹٠-٩]")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 6000
MAX_SOURCE_BYTES = 3_000_000
_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


# ---- reading the site's own files (data only) -----------------------------------------
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


def _kind_of(brand_key: str, raw: dict) -> str:
    marker = str(raw.get("kind") or raw.get("category") or "").lower()
    if marker.startswith(("acc", "لوازم")) or brand_key.startswith("acc"):
        return KIND_ACCESSORY
    return KIND_PHONE


def parse_site_files(products_js: str, site_js: str = "") -> dict:
    """The site's own catalogue as data: ``{"brands": [...], "models": [{slug,
    name, brand, brand_key, kind, aliases, site}]}``. ``site`` is the site_data
    of the model (photo file names follow the site's ``assets/products`` names)."""
    if len(products_js or "") > MAX_SOURCE_BYTES or len(site_js or "") > MAX_SOURCE_BYTES:
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
    brands, models = [], []
    for key, brand in catalog.items():
        if not isinstance(brand, dict) or not BRAND_KEY_RE.match(str(key)):
            continue
        brands.append({"key": key, "name": _text(brand.get("name"), 40) or key.title(),
                       "tagline": _text(brand.get("tagline"), 120)})
        for raw in brand.get("items") or []:
            if not isinstance(raw, dict) or not valid_slug(raw.get("id")):
                continue
            slug = raw["id"]
            slugs = photos.get(slug) if isinstance(photos.get(slug), list) else []
            colors = []
            for n, name in enumerate(raw.get("colors") or []):
                photo = slugs[n] if n < len(slugs) and slugs[n] else ""
                colors.append({"name": name, "image": f"{slug}-{photo}.jpg" if photo else "",
                               "hex": swatch.get(name, "") if isinstance(name, str) else ""})
            spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
            kind = _kind_of(key, raw)
            site = clean_site_data({
                "published": True, "tier": raw.get("tier"),
                "release_year": raw.get("releaseYear"), "price_state": raw.get("priceState"),
                "image": f"{slug}.jpg", "colors": colors,
                "specs": [[k, v] for k, v in spec.items()],
                "group": raw.get("group") if kind == KIND_ACCESSORY else "",
                "brand_key": key,
            })
            models.append({"slug": slug, "name": _text(raw.get("name"), 120),
                           "brand": _text(brand.get("name"), 60), "brand_key": key,
                           "kind": kind,
                           "aliases": [_text(a, 80) for a in raw.get("aliases") or []
                                       if _text(a, 80)][:30],
                           "site": site})
    return {"brands": brands, "models": [m for m in models if m["name"]]}


# ---- site data of one model ------------------------------------------------------------
def _text(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _image_name(value) -> str:
    name = str(value or "").strip().lower()
    return name if IMAGE_NAME_RE.match(name) else ""


def clean_site_data(raw: dict | None) -> dict:
    """A valid site_data dict (unknown fields dropped, lengths capped). A price
    label with a digit in it is replaced: the site never shows a price."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        year = int(raw.get("release_year") or 0)
    except (TypeError, ValueError):
        year = 0
    price_state = _text(raw.get("price_state"), 30)
    if not price_state or _DIGITS.search(price_state):
        price_state = DEFAULT_PRICE_STATE
    colors = []
    for color in (raw.get("colors") or [])[:12]:
        if not isinstance(color, dict) or not _text(color.get("name"), 40):
            continue
        hex_value = str(color.get("hex") or "")
        colors.append({"name": _text(color.get("name"), 40), "image": _image_name(color.get("image")),
                       "hex": hex_value.lower() if HEX_RE.match(hex_value) else ""})
    specs = []
    for row in (raw.get("specs") or [])[:20]:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            key, value = _text(row[0], 40), _text(row[1], 160)
            if key and value:
                specs.append([key, value])
    group = str(raw.get("group") or "")
    brand_key = str(raw.get("brand_key") or "").lower()
    return {
        "published": raw.get("published", True) is not False,
        "tier": _text(raw.get("tier"), 30),
        "release_year": year if 2000 <= year <= 2100 else None,
        "price_state": price_state,
        "image": _image_name(raw.get("image")),
        "colors": colors,
        "specs": specs,
        "group": group if group in GROUPS else "",
        "brand_key": brand_key if BRAND_KEY_RE.match(brand_key) else "",
        "brand_name": _text(raw.get("brand_name"), 40),
    }


def _load(value: str | None) -> dict | None:
    try:
        data = json.loads(value) if value else None
    except ValueError:
        return None
    return clean_site_data(data) if isinstance(data, dict) else None


def site_rows(db: OwnDB) -> list[dict]:
    with db._lock:
        rows = db._fetchall(
            "SELECT id, slug, name, brand, aliases, kind, hidden, site_data FROM catalog_models "
            "ORDER BY brand, slug")
    for row in rows:
        row["site"] = _load(row.pop("site_data"))
    return rows


def get_site_data(db: OwnDB, model_id: int) -> dict | None:
    with db._lock:
        row = db._fetchone("SELECT site_data FROM catalog_models WHERE id=?", (int(model_id),))
    return _load(row["site_data"]) if row else None


def set_site_data(db: OwnDB, model_id: int, data: dict, actor: str) -> dict:
    clean = clean_site_data(data)
    with db._lock:
        db._conn.execute(
            "UPDATE catalog_models SET site_data=?, updated_at=?, updated_by=? WHERE id=?",
            (json.dumps(clean, ensure_ascii=False), now_iso(), actor, int(model_id)))
        db._commit()
    return clean


def brands(db: OwnDB) -> list[dict]:
    try:
        stored = json.loads(db.get_state(BRANDS_KEY, "") or "[]")
    except ValueError:
        stored = []
    by_key = {b["key"]: dict(b) for b in DEFAULT_BRANDS}
    for b in stored if isinstance(stored, list) else []:
        if isinstance(b, dict) and BRAND_KEY_RE.match(str(b.get("key") or "")):
            by_key[b["key"]] = {"key": b["key"], "name": _text(b.get("name"), 40) or b["key"],
                                "tagline": _text(b.get("tagline"), 120)}
    return list(by_key.values())


def import_site_files(db: OwnDB, settings, products_js: str, site_js: str = "", *,
                      actor: str, overwrite: bool = False) -> dict:
    """Seed ShopSystem from the site's own files: models are added / updated by
    code (as «خواندن از سایت»), site_data is filled where it is still empty (or
    everywhere with ``overwrite``). Returns counts and the photo files the server
    still needs (ShopAdmin uploads those from the same folder)."""
    from .site_catalog import import_site

    parsed = parse_site_files(products_js, site_js)
    if not parsed["models"]:
        raise JsLiteralError("no models in products.js")
    imported = import_site(db, [{k: m[k] for k in ("slug", "name", "brand", "kind", "aliases")}
                                for m in parsed["models"]], actor)
    filled = kept = 0
    repo = CatalogModelRepo(db)
    for m in parsed["models"]:
        row = repo.get_by_slug(m["slug"])
        if row is None:
            continue
        if get_site_data(db, row["id"]) is not None and not overwrite:
            kept += 1
            continue
        set_site_data(db, row["id"], m["site"], actor)
        filled += 1
    db.set_state(BRANDS_KEY, json.dumps(parsed["brands"], ensure_ascii=False), actor)
    have = set(list_images(settings))
    wanted = sorted({name for m in parsed["models"] for name in _image_refs(m["site"])} - have)
    db.audit(actor, "site_catalog_seed", f"models={len(parsed['models'])} filled={filled} "
                                         f"kept={kept} images_needed={len(wanted)}")
    return {"models": len(parsed["models"]), "added": imported["added"],
            "updated": imported["updated"], "filled": filled, "kept": kept,
            "images_needed": wanted}


def _image_refs(site: dict) -> list[str]:
    names = [site.get("image") or ""] + [c.get("image") or "" for c in site.get("colors") or []]
    return [n for n in names if n]


# ---- photos ------------------------------------------------------------------------------
def _images_dir(settings) -> Path | None:
    return settings.site_images_path()


def list_images(settings) -> dict[str, dict]:
    """name -> {bytes, sha256} of the stored site photos."""
    folder = _images_dir(settings)
    if folder is None or not folder.is_dir():
        return {}
    out = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and IMAGE_NAME_RE.match(path.name):
            data = path.read_bytes()
            out[path.name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def check_image(name: str, data: bytes) -> str:
    """'' when the bytes are a real photo of the type its name says, else the
    reason (Persian, for ShopAdmin)."""
    if not IMAGE_NAME_RE.match(name or ""):
        return "نام فایل عکس فقط حروف کوچک انگلیسی، عدد، - و . با پسوند jpg / png / webp"
    if not data:
        return "فایل عکس خالی است"
    if len(data) > MAX_IMAGE_BYTES:
        return "حجم عکس بیش از ۵ مگابایت است"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            fmt, size = image.format, image.size
    except Exception:  # noqa: BLE001 - any decoder failure = not a photo
        return "این فایل عکس سالم نیست"
    if fmt != _FORMATS[name.rsplit(".", 1)[1]]:
        return "نوع عکس با پسوند نامش جور نیست"
    if max(size) > MAX_IMAGE_SIDE or min(size) < 16:
        return "اندازهٔ عکس مناسب نیست"
    return ""


def save_image(settings, name: str, data: bytes) -> dict:
    """Store one photo (atomically). Raises ValueError with a Persian reason."""
    name = (name or "").strip().lower()
    reason = check_image(name, data)
    if reason:
        raise ValueError(reason)
    folder = _images_dir(settings)
    if folder is None:
        raise ValueError("پوشهٔ عکس‌ها در دسترس نیست")
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / name)
    return {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def add_accessories(db: OwnDB, settings, candidates: list, codes: list[str], *,
                    actor: str) -> dict:
    """Add the accessories a manager ticked (from ``accessory_pdf.read_pdf``):
    a site model each (kind accessory), its pictures as ``<code>.jpg``,
    ``<code>-2.jpg``… and its site_data. An existing code is updated."""
    from .accessory_pdf import site_data_for
    from .site_catalog import _set_meta

    wanted = set(codes)
    repo = CatalogModelRepo(db)
    added = updated = images = 0
    for item in candidates:
        if item.code not in wanted:
            continue
        existed = repo.get_by_slug(item.code) is not None
        repo.import_models([{"slug": item.code, "name": item.name, "brand": item.brand_name,
                             "aliases": []}], actor)
        row = repo.get_by_slug(item.code)
        _set_meta(db, row["id"], kind=KIND_ACCESSORY, source="pdf")
        names = []
        for n, picture in enumerate(item.images):
            name = f"{item.code}.jpg" if n == 0 else f"{item.code}-{n + 1}.jpg"
            try:
                save_image(settings, name, picture)
            except ValueError:
                continue
            names.append(name)
        set_site_data(db, row["id"], site_data_for(item, names), actor)
        images += len(names)
        updated += existed
        added += not existed
    db.audit(actor, "site_accessories_pdf", f"added={added} updated={updated} images={images}")
    return {"added": added, "updated": updated, "images": images}


# ---- building the catalogue --------------------------------------------------------------
def _warning(code: str, slug: str, text: str) -> dict:
    return {"code": code, "slug": slug, "text": text}


def build(db: OwnDB, settings, *, generator: str = "") -> dict:
    """{"catalog": dict, "files": {path in zip: Path}, "warnings": [...],
    "skipped": n} - nothing is written."""
    stored = list_images(settings)
    folder = _images_dir(settings)
    brand_list = brands(db)
    page_brands = {b["key"] for b in brand_list}
    items, files, warnings, skipped = [], {}, [], 0

    def photo(name: str, slug: str) -> str:
        if not name:
            return ""
        if name not in stored:
            warnings.append(_warning("missing_image", slug, f"عکس «{name}» روی سرور نیست"))
            return ""
        path = IMAGES_PREFIX + name
        files[path] = folder / name
        return path

    for row in site_rows(db):
        site = row["site"]
        if site is None:
            skipped += 1        # never prepared for the site (e.g. only for the bot)
            continue
        if not site["published"]:
            continue
        kind = KIND_ACCESSORY if row.get("kind") == KIND_ACCESSORY else KIND_PHONE
        brand_key = site["brand_key"] or str(row.get("brand") or "").strip().lower()
        if kind == KIND_PHONE and brand_key not in page_brands:
            warnings.append(_warning("no_brand_page", row["slug"],
                                     f"برند «{row.get('brand') or brand_key}» در سایت صفحه ندارد؛ "
                                     "این گوشی در سایت دیده نمی‌شود"))
        colors = []
        for color in site["colors"]:
            entry = {"name": color["name"]}
            image = photo(color["image"], row["slug"])
            if image:
                entry["image"] = image
            if color["hex"]:
                entry["hex"] = color["hex"]
            colors.append(entry)
        card = photo(site["image"], row["slug"])
        if not card and not any("image" in c for c in colors):
            warnings.append(_warning("no_photo", row["slug"],
                                     f"«{row['name']}» هیچ عکسی ندارد (نقاشی گوشی نشان داده می‌شود)"))
        if kind == KIND_PHONE and not site["specs"]:
            warnings.append(_warning("no_specs", row["slug"], f"«{row['name']}» مشخصات ندارد"))
        if kind == KIND_PHONE and not colors:
            warnings.append(_warning("no_colors", row["slug"],
                                     f"«{row['name']}» رنگ ندارد؛ سایت گوشی بی‌رنگ را نشان نمی‌دهد"))
        item = {"code": row["slug"], "brand": brand_key, "category": kind,
                "name": row["name"], "tier": site["tier"],
                "release_year": site["release_year"], "price_state": site["price_state"],
                "aliases": split_aliases(row.get("aliases"))[:30],
                "specs": site["specs"], "colors": colors}
        if card:
            item["image"] = card
        if kind == KIND_ACCESSORY:
            item["group"] = site["group"] or "other"
            if site["brand_name"]:
                item["brand_name"] = site["brand_name"]
        items.append(item)
    catalog = {
        "format": FORMAT, "version": VERSION, "generated_at": now_iso(),
        "generator": generator or "ShopSystem",
        "brands": brand_list,
        "items": items,
        "images": {path: {"sha256": stored[path[len(IMAGES_PREFIX):]]["sha256"],
                          "bytes": stored[path[len(IMAGES_PREFIX):]]["bytes"]}
                   for path in sorted(files)},
    }
    return {"catalog": catalog, "files": files, "warnings": warnings, "skipped": skipped}


def validate_catalog(catalog: dict) -> list[str]:
    """Problems that would make the site refuse the file (empty = fine). The
    site checks the same rules (``applyCatalog`` in site.js)."""
    problems = []
    if catalog.get("format") != FORMAT or catalog.get("version") != VERSION:
        problems.append("قالب یا نسخهٔ فایل نادرست است")
    items = catalog.get("items")
    if not isinstance(items, list):
        return problems + ["فهرست مدل‌ها نیست"]
    codes = [i.get("code") for i in items]
    if len(codes) != len(set(codes)):
        problems.append("کد مدل تکراری")
    for item in items:
        if not valid_slug(item.get("code")) or not item.get("name"):
            problems.append(f"مدل نادرست «{item.get('code')}»")
        for path in [item.get("image")] + [c.get("image") for c in item.get("colors") or []]:
            if path and (not path.startswith(IMAGES_PREFIX)
                         or not IMAGE_NAME_RE.match(path[len(IMAGES_PREFIX):])
                         or path not in catalog.get("images", {})):
                problems.append(f"عکس نادرست «{path}»")
        if _DIGITS.search(str(item.get("price_state") or "")):
            problems.append(f"قیمت در «{item.get('code')}»")
    if not any(i.get("category") == KIND_PHONE for i in items):
        problems.append("هیچ گوشی‌ای برای سایت آماده نیست (اول «خواندن از پوشهٔ سایت» را بزنید)")
    return problems


def _item_hash(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()


def snapshot_of(catalog: dict) -> dict:
    return {"items": {i["code"]: _item_hash(i) for i in catalog["items"]},
            "names": {i["code"]: i["name"] for i in catalog["items"]},
            "images": {p: v["sha256"] for p, v in catalog["images"].items()},
            "brands": _item_hash({"b": catalog["brands"]})}


def _snapshot(db: OwnDB) -> dict:
    try:
        value = json.loads(db.get_state(SNAPSHOT_KEY, "") or "{}")
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def diff(old: dict, new: dict) -> dict:
    old_items, new_items = old.get("items") or {}, new["items"]
    names = {**(old.get("names") or {}), **new["names"]}

    def named(codes) -> list[dict]:
        return [{"code": c, "name": names.get(c, c)} for c in sorted(codes)]

    old_images = old.get("images") or {}
    return {
        "first": not old_items,
        "added": named(set(new_items) - set(old_items)),
        "removed": named(set(old_items) - set(new_items)),
        "changed": named(c for c in set(new_items) & set(old_items) if new_items[c] != old_items[c]),
        "images_new": sorted(set(new["images"]) - set(old_images)),
        "images_changed": sorted(p for p in set(new["images"]) & set(old_images)
                                 if new["images"][p] != old_images[p]),
        "brands_changed": bool(old) and old.get("brands") != new["brands"],
    }


def has_changes(change: dict) -> bool:
    return bool(change["first"] or change["added"] or change["removed"] or change["changed"]
                or change["images_new"] or change["images_changed"] or change["brands_changed"])


def preview(db: OwnDB, settings, *, generator: str = "") -> dict:
    built = build(db, settings, generator=generator)
    catalog = built["catalog"]
    change = diff(_snapshot(db), snapshot_of(catalog))
    phones = sum(1 for i in catalog["items"] if i["category"] == KIND_PHONE)
    return {"counts": {"phones": phones, "accessories": len(catalog["items"]) - phones,
                       "images": len(catalog["images"]), "skipped": built["skipped"]},
            "changes": change, "has_changes": has_changes(change),
            "warnings": built["warnings"][:300], "problems": validate_catalog(catalog),
            "last": last_export(db), "schedule": get_schedule(db)}


# ---- writing -----------------------------------------------------------------------------
def catalog_bytes(catalog: dict) -> bytes:
    return json.dumps(catalog, ensure_ascii=False, indent=1).encode("utf-8")


def to_zip(built: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, source in sorted(built["files"].items()):
            archive.write(source, path, compress_type=zipfile.ZIP_STORED)  # photos are compressed
        archive.writestr("catalog.json", catalog_bytes(built["catalog"]))
    return buffer.getvalue()


def check_folder(folder: str) -> Path:
    """The export folder on the server: an existing folder, never a drive root.
    Raises ValueError with a Persian reason."""
    if not folder or not folder.strip():
        raise ValueError("پوشهٔ خروجی خالی است")
    path = Path(folder.strip())
    if not path.is_absolute():
        raise ValueError("نشانی کامل پوشه را بنویسید (مثلاً D:\\SiteCatalog)")
    if path == Path(path.anchor):
        raise ValueError("ریشهٔ درایو انتخاب نشود؛ یک پوشه بسازید و آن را انتخاب کنید")
    if not path.is_dir():
        raise ValueError("این پوشه روی سرور وجود ندارد")
    return path


def to_folder(built: dict, folder: str) -> dict:
    """Write ``images/*`` (only new or changed photos) and then ``catalog.json``
    (atomically, last, so the file never names a photo that is not there yet).
    Nothing else in the folder is touched or deleted."""
    target = check_folder(folder)
    images = target / "images"
    images.mkdir(exist_ok=True)
    written = unchanged = 0
    for path, source in sorted(built["files"].items()):
        dest = target / path
        data = source.read_bytes()
        if dest.is_file() and dest.read_bytes() == data:
            unchanged += 1
            continue
        tmp = dest.with_name(f".{dest.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        written += 1
    tmp = target / ".catalog.json.tmp"
    tmp.write_bytes(catalog_bytes(built["catalog"]))
    os.replace(tmp, target / "catalog.json")
    return {"folder": str(target), "images_written": written, "images_unchanged": unchanged}


def record(db: OwnDB, built: dict, *, actor: str, where: str, detail: dict | None = None) -> dict:
    """Remember what was exported (the next preview compares with it)."""
    catalog = built["catalog"]
    snap = snapshot_of(catalog)
    change = diff(_snapshot(db), snap)
    db.set_state(SNAPSHOT_KEY, json.dumps(snap, ensure_ascii=False), actor)
    summary = {"ok": True, "at": now_iso(), "by": actor, "where": where,
               "items": len(catalog["items"]), "images": len(catalog["images"]),
               "added": len(change["added"]), "changed": len(change["changed"]),
               "removed": len(change["removed"]), **(detail or {})}
    db.set_state(LAST_KEY, json.dumps(summary, ensure_ascii=False), actor)
    db.audit(actor, "site_catalog_export",
             f"where={where} items={summary['items']} images={summary['images']} "
             f"added={summary['added']} changed={summary['changed']} removed={summary['removed']}")
    return summary


def last_export(db: OwnDB) -> dict | None:
    try:
        value = json.loads(db.get_state(LAST_KEY, "") or "null")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ---- daily export into a server folder (optional) -----------------------------------------
def get_schedule(db: OwnDB) -> dict:
    try:
        value = json.loads(db.get_state(SCHEDULE_KEY, "") or "{}")
    except ValueError:
        value = {}
    value = value if isinstance(value, dict) else {}
    hour = value.get("hour")
    return {"enabled": bool(value.get("enabled")),
            "hour": hour if isinstance(hour, int) and 0 <= hour <= 23 else 6,
            "folder": str(value.get("folder") or "")}


def set_schedule(db: OwnDB, *, enabled: bool, hour: int, folder: str, actor: str) -> dict:
    if not 0 <= int(hour) <= 23:
        raise ValueError("ساعت باید بین ۰ و ۲۳ باشد")
    folder = folder.strip()
    if enabled:
        check_folder(folder)
    value = {"enabled": bool(enabled), "hour": int(hour), "folder": folder}
    db.set_state(SCHEDULE_KEY, json.dumps(value, ensure_ascii=False), actor)
    db.audit(actor, "site_catalog_schedule", f"enabled={enabled} hour={hour}")
    return value


def run_scheduled(db: OwnDB, settings, now: datetime, *, generator: str = "") -> dict | None:
    """One daily export after the chosen hour; only when something changed.
    Returns the summary, or None when it was not due."""
    schedule = get_schedule(db)
    if not schedule["enabled"] or now.hour < schedule["hour"]:
        return None
    today = now.date().isoformat()
    if db.get_state(AUTO_DATE_KEY, "") == today:
        return None
    db.set_state(AUTO_DATE_KEY, today, "schedule")
    built = build(db, settings, generator=generator)
    problems = validate_catalog(built["catalog"])
    if problems:
        summary = {"ok": False, "at": now_iso(), "by": "schedule", "where": "folder",
                   "error": "خروجی ساخته نشد: " + "، ".join(problems[:3])}
        db.set_state(LAST_KEY, json.dumps(summary, ensure_ascii=False), "schedule")
        return summary
    if not has_changes(diff(_snapshot(db), snapshot_of(built["catalog"]))):
        return {"ok": True, "unchanged": True}
    try:
        written = to_folder(built, schedule["folder"])
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "نوشتن در پوشه ممکن نشد"
        summary = {"ok": False, "at": now_iso(), "by": "schedule", "where": "folder",
                   "error": reason}
        db.set_state(LAST_KEY, json.dumps(summary, ensure_ascii=False), "schedule")
        logger.warning("site catalog export failed (%s)", type(exc).__name__)
        return summary
    return record(db, built, actor="schedule", where="folder", detail=written)


async def export_loop(settings, db_factory, *, generator: str = "", poll_seconds: int = 600,
                      clock: Callable[[], datetime] = datetime.now) -> None:
    """Background loop started with the API (server local time). Never raises."""
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            await asyncio.to_thread(run_scheduled, db_factory(), settings, clock(),
                                    generator=generator)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - tried again on the next poll
            logger.warning("site catalog schedule failed, will retry (%s)", type(exc).__name__)
