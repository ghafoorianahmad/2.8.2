"""v2.11.0: the site's cart reaches the bot as ``/start c_<code>`` and becomes one
«درخواست خرید - استعلام قیمت» (item request kind ``purchase``) per line.

* **Code** (the same as ``site.js`` / ShopAdmin): ``c_`` + 7 characters per line,
  base64url: the model's 5-character hash (FNV-1a 32 bits of the model code,
  low 30 bits), the colour's position in that model's colour list on the site
  (63 = none) and the quantity (1-20). At most 8 lines (Bale / Telegram allow
  64 characters in the start parameter). The site stores nothing anywhere.
* **Which model / colour**: the site's own public files (``catalog.json`` when
  the site uses one, else ``products.js``), fetched by the server (outbound,
  read only), cached ``CACHE_MINUTES``; when a hash is unknown the files are read
  again (at most once a minute). Without the site, the site models the server
  already knows (``catalog_models``) give the name; the colour stays unknown.
* **Request**: product name «<model> — از سبد خرید سایت», the colour, the
  quantity; the «سازه حساب» product only when the model maps to exactly one
  product. Staff answer it like every other purchase request (product + price
  -> «تأیید و خرید» in the bot -> a normal order). Sending the same cart again
  within ``REPEAT_MINUTES`` creates nothing new.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .catalog_models import CatalogModelRepo, valid_slug
from .db_own import OwnDB
from .util import now_iso

logger = logging.getLogger(__name__)

B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
CODE_RE = re.compile(r"^c_((?:[A-Za-z0-9_-]{7}){1,8})$")
MAX_LINES = 8
MAX_QTY = 20
NO_COLOR = 63
CACHE_KEY = "site_cart:models"
CACHE_MINUTES = 15
REFETCH_SECONDS = 60
REPEAT_MINUTES = 60
MAX_BYTES = 3_000_000
SOURCE_TEXT = "از سبد خرید سایت"

_ITEM_RE = re.compile(r'\{\s*id:\s*"([^"]+)",\s*name:\s*"([^"]+)"')
_COLORS_RE = re.compile(r"colors:\s*\[([^\]]*)\]")
_STRING_RE = re.compile(r'"([^"]*)"')


def model_hash(code: str) -> str:
    value = 0x811C9DC5
    for byte in code.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    value &= (1 << 30) - 1
    return "".join(B64URL[(value >> shift) & 63] for shift in (24, 18, 12, 6, 0))


def looks_like_cart(text: str | None) -> bool:
    return bool(CODE_RE.match(str(text or "").strip()))


def decode(code: str) -> list[dict]:
    """``c_…`` -> [{hash, color (None = none), qty}]. Raises ValueError."""
    match = CODE_RE.match(str(code or "").strip())
    if not match:
        raise ValueError("not a cart code")
    body = match.group(1)
    lines = []
    for n in range(0, len(body), 7):
        part = body[n:n + 7]
        color = B64URL.index(part[5])
        qty = B64URL.index(part[6])
        if not 1 <= qty <= MAX_QTY:
            raise ValueError("bad quantity")
        lines.append({"hash": part[:5], "color": None if color == NO_COLOR else color, "qty": qty})
    return lines


# ---- the site's public model list ------------------------------------------------------
def parse_site(text: str) -> dict[str, dict]:
    """code -> {"name", "colors"} from the site's catalog.json or products.js
    (read as data, never executed). Empty when it is neither."""
    text = text or ""
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return {}
        if not isinstance(data, dict) or data.get("format") != "asr-catalog":
            return {}
        out = {}
        for item in data.get("items") or []:
            if isinstance(item, dict) and valid_slug(item.get("code")) and item.get("name"):
                out[item["code"]] = {
                    "name": " ".join(str(item["name"]).split())[:120],
                    "colors": [" ".join(str(c.get("name") or "").split())[:40]
                               for c in item.get("colors") or [] if isinstance(c, dict)]}
        return out
    out = {}
    items = list(_ITEM_RE.finditer(text))
    for n, match in enumerate(items):
        end = items[n + 1].start() if n + 1 < len(items) else len(text)
        if not valid_slug(match.group(1)):
            continue
        colors_match = _COLORS_RE.search(text[match.end():end])
        colors = _STRING_RE.findall(colors_match.group(1)) if colors_match else []
        out[match.group(1)] = {"name": " ".join(match.group(2).split())[:120],
                               "colors": [" ".join(c.split())[:40] for c in colors]}
    return out


def catalog_url(settings) -> str:
    """The public catalog.json next to the products.js the server already reads."""
    base = str(getattr(settings, "site_catalog_url", "") or "")
    if base.endswith("/products.js"):
        return base[: -len("products.js")] + "catalog/catalog.json"
    return ""


def fetch_text(url: str, *, client_factory: Callable | None = None, timeout: float = 20) -> str:
    """A public file of the site (text); RuntimeError with a short reason."""
    import httpx

    factory = client_factory or (lambda: httpx.Client(timeout=timeout, follow_redirects=True))
    try:
        with factory() as client:
            response = client.get(url, headers={"User-Agent": "ShopSystem site-cart"})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"site unreachable ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise RuntimeError(f"site answered HTTP {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise RuntimeError("site file too large")
    return response.text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cached(db: OwnDB) -> tuple[dict, Optional[datetime]]:
    try:
        value = json.loads(db.get_state(CACHE_KEY, "") or "{}")
        when = datetime.fromisoformat(value["at"])
        return value.get("models") or {}, when
    except (ValueError, KeyError, TypeError):
        return {}, None


def site_models(db: OwnDB, settings, *, fetch: Optional[Callable[[str], str]] = None,
                need: set[str] | None = None) -> dict[str, dict]:
    """code -> {"name", "colors"} of the live site; cached, read again when old
    or when a wanted hash is unknown (at most once a minute)."""
    fetch = fetch or fetch_text
    models, when = _cached(db)
    now = _now()
    stale = when is None or now - when > timedelta(minutes=CACHE_MINUTES)
    known = {model_hash(code) for code in models}
    missing = bool(need and not need <= known)
    may_refetch = when is None or now - when > timedelta(seconds=REFETCH_SECONDS)
    if stale or (missing and may_refetch):
        fresh: dict = {}
        for url in (catalog_url(settings), str(getattr(settings, "site_catalog_url", "") or "")):
            if not url:
                continue
            try:
                fresh = parse_site(fetch(url))
            except RuntimeError as exc:
                logger.info("site cart: %s not read (%s)", url.rsplit("/", 1)[-1], exc)
                continue
            if fresh:
                break
        if fresh:
            models = fresh
            db.set_state(CACHE_KEY, json.dumps({"at": now.isoformat(timespec="seconds"),
                                                "models": models}, ensure_ascii=False), "site")
    return models


# ---- the requests ------------------------------------------------------------------------
def resolve(db: OwnDB, settings, code: str, *, fetch: Optional[Callable[[str], str]] = None) -> dict:
    """{"lines": [{code, name, color, qty, kala_code}], "unknown": n}."""
    lines = decode(code)
    models = site_models(db, settings, fetch=fetch, need={line["hash"] for line in lines})
    repo = CatalogModelRepo(db)
    known = {model_hash(slug): (slug, info) for slug, info in models.items()}
    for model in repo.list_models():       # names the server already knows
        known.setdefault(model_hash(model["slug"]), (model["slug"], {"name": model["name"],
                                                                     "colors": []}))
    out, unknown = [], 0
    for line in lines:
        found = known.get(line["hash"])
        if found is None:
            unknown += 1
            continue
        slug, info = found
        colors = info.get("colors") or []
        color = colors[line["color"]] if line["color"] is not None and \
            line["color"] < len(colors) else ""
        kala_code = None
        model = repo.get_by_slug(slug)
        if model is not None and not model.get("hidden"):
            items = [i for i in repo.items(model["id"]) if i["state"] != "missing"]
            if len(items) == 1:
                kala_code = int(items[0]["kala_code"])
        out.append({"code": slug, "name": info.get("name") or slug, "color": color,
                    "color_index": line["color"], "qty": line["qty"], "kala_code": kala_code})
    return {"lines": out, "unknown": unknown}


def _repeat_key(user_id: int, code: str) -> str:
    return f"site_cart:sent:{int(user_id)}:{code}"


def create_requests(db: OwnDB, settings, user: dict, code: str, actor: str, *,
                    fetch: Optional[Callable[[str], str]] = None) -> dict:
    """One purchase request per cart line. The same cart again within an hour
    returns the earlier answer (a double tap, a re-opened link)."""
    key = _repeat_key(user["id"], code)
    try:
        earlier = json.loads(db.get_state(key, "") or "null")
    except ValueError:
        earlier = None
    if isinstance(earlier, dict):
        try:
            when = datetime.fromisoformat(earlier["at"])
        except (KeyError, ValueError):
            when = None
        if when is not None and _now() - when < timedelta(minutes=REPEAT_MINUTES):
            return {**earlier["result"], "repeated": True}
    resolved = resolve(db, settings, code, fetch=fetch)
    created = []
    for line in resolved["lines"]:
        request = db.add_item_request(
            user["id"], line["kala_code"], f"{line['name']} — {SOURCE_TEXT}",
            f"کد مدل سایت: {line['code']}", "purchase",
            accounting_db=settings.database_name(), color=line["color"], qty=line["qty"])
        db.add_event("item_request", request["id"], actor)
        created.append({"id": request["id"], "name": line["name"], "color": line["color"],
                        "qty": line["qty"]})
    if created:
        db.audit(actor, "site_cart_requests",
                 f"user id={user['id']} lines={len(created)} unknown={resolved['unknown']}")
    result = {"created": created, "unknown": resolved["unknown"], "repeated": False}
    db.set_state(key, json.dumps({"at": now_iso(), "result": result}, ensure_ascii=False), actor)
    return result
