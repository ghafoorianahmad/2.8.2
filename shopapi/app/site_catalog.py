"""v2.9.3: the site models read from the live public site, mapped automatically.

* **Read**: once a month (``SITE_CATALOG_DAYS``, 30) and with «خواندن از سایت
  اکنون» in ShopAdmin, the server reads ``SITE_CATALOG_URL`` (the public
  ``assets/products.js`` of the site, as text, never executed) and adds / updates
  the models by their permanent code (slug). No manual products.js import.
* **Phones**: the site names are the price-list names, so a model is mapped
  through *site model → price-list row → «سازه حساب» product*, with the mappings
  the price list already has. A row belongs to a model when the brand is the
  same, every model word of the site name is in the row («Galaxy» / «iPhone» /
  «Xiaomi» are optional) and the row has no other model word (``Pro``, ``Max``,
  ``FE``, ``Note``, ``14S``…). Every mapped row of the model gives its product.
* **Accessories** (a site item with ``kind: "accessory"``): by name against the
  «سازه حساب» products (``fuzzy``); their price is the bot's price level (3).
* Only an **uncertain** match waits for a manager (``auto_suggest`` on the model,
  accepted or dismissed in «مدل‌های سایت»); a sure one is mapped at once.
* New site models are announced in ShopAdmin (event ``site_models_new``).

Nothing is ever deleted: a model missing from the site stays (slugs are never
reused), and the owner's own mappings are never touched.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import fuzzy
from .catalog_models import CatalogModelRepo, valid_slug
from .db_own import OwnDB
from .phone_search import _QUALIFIERS, _close, row_tokens, search_tokens
from .util import now_iso

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://asrertebatat2.ir/assets/products.js"
DEFAULT_DAYS = 30
MAX_BYTES = 2_000_000
LAST_READ_KEY = "site_catalog:last_read"
#: the active price list the site phones were last mapped against
MAPPED_LIST_KEY = "site_catalog:mapped_list"
EVENT_NEW_MODELS = "site_models_new"
SOURCE_SITE = "site"
KIND_PHONE = "phone"
KIND_ACCESSORY = "accessory"

#: brand words that may be left out of a price-list row («Galaxy A56» = «A56»)
OPTIONAL_WORDS = frozenset({"apple", "iphone", "samsung", "galaxy", "xiaomi", "mi"})
#: words that make a different model: a row with one the site name lacks is not it
DISTINCT_WORDS = frozenset(_QUALIFIERS) | {"note", "redmi", "poco", "t", "tab", "pad",
                                           "watch", "airpod", "fold", "flip", "ipad",
                                           "macbook", "pencil", "mouse", "adapter"}
#: section / name words of each brand (a Samsung model never takes an iPhone row)
BRANDS = {
    "apple": {"apple", "iphone"},
    "samsung": {"samsung", "galaxy"},
    "xiaomi": {"xiaomi", "redmi", "poco", "mi"},
}
#: an accessory name match is sure from this score with this gap to the next
ACCESSORY_SURE = 0.9
ACCESSORY_GAP = 0.12
ACCESSORY_SUGGEST = 0.55

_BRAND_RE = re.compile(r'^\s*([a-z][a-z0-9_]*)\s*:\s*\{\s*$', re.MULTILINE)
_BRAND_NAME_RE = re.compile(r'^\s*name:\s*"([^"]+)",\s*mark:', re.MULTILINE)
_ITEM_RE = re.compile(r'\{\s*id:\s*"([^"]+)",\s*name:\s*"([^"]+)"')
_ALIASES_RE = re.compile(r'aliases:\s*\[([^\]]*)\]')
_KIND_RE = re.compile(r'\b(?:kind|category)\s*:\s*"([^"]+)"')
_STRING_RE = re.compile(r'"([^"]*)"')


# ---- reading the site ---------------------------------------------------------------
def parse_products_js(text: str) -> list[dict]:
    """Models of the site's ``products.js``: [{slug, name, brand, brand_key,
    aliases, kind}]. Read as text, never executed. Each item starts with
    ``{ id: "…", name: "…"``; its brand is the closest ``name: "…", mark:`` line
    above it (``brand_key`` = the catalog key, e.g. ``samsung``)."""
    brands = [(m.start(), m.group(1)) for m in _BRAND_NAME_RE.finditer(text)]
    keys = [(m.start(), m.group(1)) for m in _BRAND_RE.finditer(text)]
    items = list(_ITEM_RE.finditer(text))
    out = []
    for n, match in enumerate(items):
        end = items[n + 1].start() if n + 1 < len(items) else len(text)
        segment = text[match.end():end]
        aliases_match = _ALIASES_RE.search(segment)
        aliases = _STRING_RE.findall(aliases_match.group(1)) if aliases_match else []
        kind_match = _KIND_RE.search(segment.split("spec:")[0])
        brand = next((name for pos, name in reversed(brands) if pos < match.start()), "")
        key = next((name for pos, name in reversed(keys) if pos < match.start()), "")
        kind = KIND_ACCESSORY if (kind_match and kind_match.group(1).lower().startswith(
            ("acc", "لوازم"))) or key.startswith("acc") else KIND_PHONE
        slug = match.group(1)
        if not valid_slug(slug):
            continue
        out.append({"slug": slug, "name": " ".join(match.group(2).split())[:120],
                    "brand": brand[:60], "brand_key": key, "kind": kind,
                    "aliases": [" ".join(a.split())[:80] for a in aliases if a.strip()][:30]})
    return out


def fetch_site(url: str, *, client_factory: Callable | None = None, timeout: float = 30) -> str:
    """The public products.js (text). Raises RuntimeError with a short reason."""
    import httpx

    factory = client_factory or (lambda: httpx.Client(timeout=timeout, follow_redirects=True))
    try:
        with factory() as client:
            response = client.get(url, headers={"User-Agent": "ShopSystem site-catalog"})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"site unreachable ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise RuntimeError(f"site answered HTTP {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise RuntimeError("site catalog too large")
    text = response.text
    if "CATALOG" not in text or "id:" not in text:
        raise RuntimeError("not the site catalog (products.js)")
    return text


# ---- phones: site model -> price-list rows ----------------------------------------------
def _brand_of(tokens: set[str]) -> str:
    for brand, words in BRANDS.items():
        if tokens & words:
            return brand
    return ""


def model_words(name: str) -> list[str]:
    return list(dict.fromkeys(search_tokens(name)))


def row_matches(name: str, brand_key: str, row: dict) -> str:
    """'sure' / 'near' / '' for one price-list row and one site model."""
    query = model_words(name)
    pool = row_tokens(row)
    query_brand = brand_key if brand_key in BRANDS else _brand_of(set(query))
    # the row must be of the same brand (an iPhone never takes a MacBook / iPad row,
    # a Galaxy never an iPhone row); a row of an unknown brand never matches
    if query_brand and _brand_of(pool) != query_brand:
        return ""
    required = [t for t in query if t not in OPTIONAL_WORDS]
    if "note" in required and "redmi" in required:
        required.remove("redmi")         # «Note 15 Pro» rows leave «Redmi» out
    if not required:
        return ""
    described = set(search_tokens(f"{row.get('description') or ''}"))
    extra = (described & DISTINCT_WORDS) - set(query)
    if extra:
        return ""
    if all(t in pool for t in required):
        return "sure"
    # a spelling variant of a long word («Promax», a typo): a manager decides
    if all(t in pool or (not t.isdigit() and len(t) >= 4 and _close(t, pool))
           for t in required):
        return "near"
    return ""


def storage_label(name: str, row: dict) -> str:
    """«۲۵۶ گیگ / ۸ رم» style label from the row (numbers the model name lacks)."""
    model_digits = {t for t in model_words(name) if t.isdigit()}
    numbers = [t for t in search_tokens(row.get("description") or "")
               if t.isdigit() and t not in model_digits]
    if not numbers:
        return ""
    label = f"{numbers[0]} گیگ"
    if len(numbers) > 1:
        label += f" / {numbers[1]} رم"
    return label[:60]


def phone_matches(name: str, brand_key: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(sure rows, near rows) of the active price list for a site phone model."""
    sure, near = [], []
    for row in rows:
        if row.get("action") == "ignore":
            continue
        verdict = row_matches(name, brand_key, row)
        if verdict == "sure":
            sure.append(row)
        elif verdict == "near":
            near.append(row)
    return sure, near


# ---- the run ---------------------------------------------------------------------------
def _suggestion(code: int, name: str, label: str, why: str, score: float) -> dict:
    return {"kala_code": int(code), "name": name, "label": label, "why": why,
            "score": round(float(score), 3)}


def _set_meta(db: OwnDB, model_id: int, *, kind: str | None = None, source: str | None = None,
              suggest: list[dict] | None = None) -> None:
    sets, values = [], []
    if kind is not None:
        sets.append("kind=?")
        values.append(kind)
    if source is not None:
        sets.append("source=?")
        values.append(source)
    if suggest is not None:
        sets.append("auto_suggest=?")
        values.append(json.dumps(suggest, ensure_ascii=False) if suggest else "")
    if not sets:
        return
    with db._lock:
        db._conn.execute(f"UPDATE catalog_models SET {', '.join(sets)} WHERE id=?",
                         (*values, int(model_id)))
        db._commit()


def auto_map(db: OwnDB, reader, settings, *, actor: str = "site",
             price_rows: list[dict] | None = None) -> dict:
    """Map the site models. A phone gets every product of its price-list rows that
    is mapped already (new storage / colour rows join later too); an accessory
    without a product gets a sure name match. Uncertain matches become
    suggestions for a manager. The product name always comes from «سازه حساب»
    (the nightly check compares it). Returns the counts."""
    from .purchase import active_rows

    repo = CatalogModelRepo(db)
    if price_rows is None:
        _active, price_rows = active_rows(db, settings)
    names: dict[int, str] = reader.product_names() if reader is not None else {}
    stats = {"phones": 0, "phones_mapped": 0, "phones_suggested": 0, "phones_unmatched": 0,
             "phones_no_mapping": 0, "accessories": 0, "accessories_mapped": 0,
             "accessories_suggested": 0, "accessories_unmatched": 0, "items_added": 0}
    taken = repo.mapped_codes()
    for model in repo.list_models():
        kind = str(model.get("kind") or KIND_PHONE)
        prefix = "phones" if kind == KIND_PHONE else "accessories"
        stats[prefix] += 1
        has_items = bool(model.get("item_count"))
        found: list[tuple[int, str]] = []
        suggest: list[dict] = []
        if kind == KIND_PHONE:
            brand_key = str(model.get("brand") or "").lower()
            sure, near = phone_matches(model["name"], brand_key, price_rows)
            mapped = [r for r in sure if r.get("action") == "map" and r.get("kala_code")]
            for row in mapped:
                code = int(row["kala_code"])
                if code not in taken and code in names and code not in (c for c, _ in found):
                    found.append((code, storage_label(model["name"], row)))
            if sure and not mapped and not has_items:
                stats["phones_no_mapping"] += 1
            if not has_items:
                for row in near:
                    code = int(row.get("kala_code") or 0)
                    if row.get("action") == "map" and code and code not in taken:
                        suggest.append(_suggestion(code, names.get(code) or
                                                   str(row.get("description")),
                                                   storage_label(model["name"], row),
                                                   "pricelist", 0.8))
        elif not has_items:
            pool = {c: n for c, n in names.items() if c not in taken}
            ranked = fuzzy.rank(model["name"], pool, limit=5, min_score=ACCESSORY_SUGGEST)
            if ranked:
                top = ranked[0]
                second = ranked[1]["score"] if len(ranked) > 1 else 0.0
                if top["score"] >= ACCESSORY_SURE and top["score"] - second >= ACCESSORY_GAP:
                    found.append((int(top["code"]), ""))
                else:
                    suggest = [_suggestion(r["code"], r["name"], "", "name", r["score"])
                               for r in ranked]
        for code, label in found:
            repo.add_item(model["id"], code, names[code], label, actor)
            taken[code] = model["slug"]
            stats["items_added"] += 1
        if found and model.get("auto_suggest"):
            _set_meta(db, model["id"], suggest=[])
        if has_items or found:
            stats[f"{prefix}_mapped"] += 1
        elif suggest:
            _set_meta(db, model["id"], suggest=suggest)
            stats[f"{prefix}_suggested"] += 1
        else:
            stats[f"{prefix}_unmatched"] += 1
    return stats


def import_site(db: OwnDB, models: list[dict], actor: str = "site") -> dict:
    """Add / update the site's models (never removes one). Returns the counts
    and the new slugs."""
    repo = CatalogModelRepo(db)
    before = {m["slug"] for m in repo.list_models()}
    result = repo.import_models(models, actor)
    for m in models:
        row = repo.get_by_slug(m["slug"])
        if row is not None:
            _set_meta(db, row["id"], kind=m.get("kind") or KIND_PHONE, source=SOURCE_SITE)
    new = [m["slug"] for m in models if m["slug"] not in before]
    return {**result, "new": new}


def read_site(db: OwnDB, reader, settings, *, actor: str = "site",
              fetch: Callable[[str], str] | None = None) -> dict:
    """Read the live site now, import, map and remember the summary."""
    url = str(getattr(settings, "site_catalog_url", "") or DEFAULT_URL)
    summary: dict = {"at": now_iso(), "url": url}
    try:
        text = (fetch or fetch_site)(url)
        models = parse_products_js(text)
        if not models:
            raise RuntimeError("no models in the site catalog")
    except RuntimeError as exc:
        summary.update(ok=False, error=str(exc)[:200])
        db.set_state(LAST_READ_KEY, json.dumps(summary, ensure_ascii=False), actor)
        raise
    imported = import_site(db, models, actor)
    try:
        mapped = auto_map(db, reader, settings, actor=actor)
    except Exception as exc:  # noqa: BLE001 - the models are in; mapping next time
        logger.warning("site catalog: mapping failed (%s)", type(exc).__name__)
        mapped = {"error": type(exc).__name__}
    summary.update(ok=True, found=len(models), added=imported["added"],
                   updated=imported["updated"], new=imported["new"][:50], mapping=mapped)
    db.set_state(LAST_READ_KEY, json.dumps(summary, ensure_ascii=False), actor)
    db.audit(actor, "site_catalog_read",
             f"found={len(models)} added={imported['added']} updated={imported['updated']}")
    if imported["new"]:
        db.add_event(EVENT_NEW_MODELS, len(imported["new"]), actor)
    return summary


def last_read(db: OwnDB) -> dict | None:
    raw = db.get_state(LAST_READ_KEY, "")
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def due(db: OwnDB, settings, now: datetime | None = None) -> bool:
    days = int(getattr(settings, "site_catalog_days", DEFAULT_DAYS) or 0)
    if days <= 0:
        return False
    last = last_read(db) or {}
    try:
        when = datetime.fromisoformat(str(last.get("at")))
    except (TypeError, ValueError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    # a failed read is tried again a day later, a good one a month later
    wait = timedelta(days=days) if last.get("ok") else timedelta(days=1)
    return now - when >= wait


def remap_if_list_changed(db: OwnDB, reader, settings) -> dict | None:
    """A new price list may bring rows of site phones: map them (once per list)."""
    from .pricelist.repo import PriceListRepo

    active = PriceListRepo(db).active_list()
    if active is None or not any(m.get("source") == SOURCE_SITE
                                 for m in CatalogModelRepo(db).list_models()):
        return None
    if db.get_state(MAPPED_LIST_KEY, "") == str(active["id"]):
        return None
    stats = auto_map(db, reader, settings)
    db.set_state(MAPPED_LIST_KEY, str(active["id"]), "site")
    return stats


async def monthly_loop(settings, db_factory, reader_factory, *, poll_seconds: int = 3600,
                       first_delay: int = 300) -> None:
    """Background loop started with the API: reads the site when it is due (a
    month after the last good read) and maps the site phones again after every new
    price list. Never raises."""
    if int(getattr(settings, "site_catalog_days", DEFAULT_DAYS) or 0) <= 0:
        return
    await asyncio.sleep(first_delay)
    while True:
        try:
            db = db_factory()
            if due(db, settings):
                await asyncio.to_thread(read_site, db, reader_factory(), settings)
            else:
                await asyncio.to_thread(remap_if_list_changed, db, reader_factory(), settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - tried again on the next poll
            logger.warning("site catalog read failed, will retry (%s)", type(exc).__name__)
        await asyncio.sleep(poll_seconds)


# ---- a manager's answer to a suggestion -----------------------------------------------
def suggestions(model: dict) -> list[dict]:
    try:
        value = json.loads(model.get("auto_suggest") or "[]")
    except ValueError:
        return []
    return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []


def accept_suggestion(db: OwnDB, reader, settings, model_id: int, codes: list[int],
                      actor: str) -> int:
    """Add the chosen suggested products to the model; the suggestion is closed."""
    repo = CatalogModelRepo(db)
    model = repo.get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    offered = {int(s["kala_code"]): s for s in suggestions(model)}
    added = 0
    names = reader.product_names() if reader is not None else {}
    for code in codes:
        if int(code) not in offered or repo.item_for_code(int(code)) is not None:
            continue
        item = offered[int(code)]
        repo.add_item(model_id, int(code), names.get(int(code)) or item.get("name") or str(code),
                      str(item.get("label") or ""), actor)
        added += 1
    _set_meta(db, model_id, suggest=[])
    return added


def dismiss_suggestion(db: OwnDB, model_id: int) -> None:
    _set_meta(db, model_id, suggest=[])

