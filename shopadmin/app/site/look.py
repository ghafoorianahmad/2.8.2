"""v2.12.0 «ظاهر و چیدمان»: the site's look and layout as plain data (no Qt, no
network) — tested alone.

Only safe presets and plain text: never HTML, CSS or a script. The site reads
the published ``assets/catalog/site.json`` (format ``asr-site-look`` version 1),
checks every field again (``applyLook`` in site.js) and keeps its own built-in
value for anything missing or invalid.

* **Arrangement**: brand order (the order of ``brands`` in the working data),
  phone order (``auto`` = newest first, as the site always did, or ``manual`` =
  the order of the items in the working data), accessories in the order of the
  working data, the phones of «تازه‌ترین گوشی‌ها» (empty = the 4 newest).
* **Appearance**: a colour preset, a logo, the home banner (texts, 3 badges, up
  to 3 pictures), the order and visibility of the home sections, store info
  (address, phone, hours, about text, bot / channel / map links).

The defaults are the texts the site shows today, so an untouched look changes
nothing on the site.
"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import urlsplit

FORMAT = "asr-site-look"
VERSION = 1
#: inside ``assets/catalog/`` of the site repository
LOOK_FILE = "site.json"
LOOK_PREFIX = "look/"
LOOK_IMAGE_RE = re.compile(r"^(?:logo|banner)-[0-9a-f]{8,16}\.(?:png|jpg)$")

#: (key, Persian name, (main, second, third)) — the site's --t-violet / --t-cyan / --t-rose
PALETTES = (
    ("violet", "بنفش و فیروزه‌ای (فعلی)", ("#7c6cff", "#38d6ff", "#ff5fa2")),
    ("ocean", "آبی اقیانوسی", ("#2f6bff", "#22c3ee", "#5b8cff")),
    ("emerald", "سبز زمردی", ("#12a37a", "#3dd6b0", "#8bd450")),
    ("sunset", "نارنجی غروب", ("#f2622e", "#ffb340", "#ff4f7a")),
    ("ruby", "قرمز یاقوتی", ("#d6304f", "#ff7a59", "#ff4fa0")),
    ("graphite", "طوسی گرافیتی", ("#5d6b82", "#9aa8bd", "#7c8aa3")),
)
PALETTE_KEYS = tuple(p[0] for p in PALETTES)
PALETTE_NAMES = {p[0]: p[1] for p in PALETTES}

#: the home page sections that can be moved / hidden (the banner stays first)
SECTIONS = (
    ("brands", "برندها"),
    ("featured", "تازه‌ترین گوشی‌ها"),
    ("accessories", "لوازم جانبی"),
    ("order", "ثبت سفارش در ربات"),
    ("store", "فروشگاه حضوری"),
    ("faq", "سؤالات پرتکرار"),
)
SECTION_KEYS = tuple(s[0] for s in SECTIONS)
SECTION_NAMES = dict(SECTIONS)

PHONE_ORDER_AUTO = "auto"
PHONE_ORDER_MANUAL = "manual"
FEATURED_MAX = 8
BANNER_MAX = 3
BADGES = 3
HOURS_MAX = 4

#: text limits (the site caps the same)
LIMITS = {"eyebrow": 60, "title": 60, "highlight": 60, "lede": 400, "badge_title": 40,
          "badge_text": 90, "address": 200, "address_short": 80, "hours_label": 40,
          "hours_value": 40, "about": 600}

STORE_LINKS = ("bale", "telegram", "telegram_channel", "map")
LINK_NAMES = {"bale": "ربات بله", "telegram": "ربات تلگرام", "telegram_channel": "کانال تلگرام",
              "map": "مسیریابی روی نقشه"}
MAP_HOSTS = ("nshn.ir", "neshan.org", "www.neshan.org", "balad.ir", "maps.google.com",
             "www.google.com", "google.com", "goo.gl", "maps.app.goo.gl")

DEFAULT_LOOK = {
    "palette": "violet",
    "logo": "",
    "hero": {
        "eyebrow": "عصر ارتباطات ۲ · مشهد",
        "title": "گوشی بعدی‌تان را",
        "highlight": "ساده‌تر انتخاب کنید.",
        "lede": ("گوشی‌های Apple، Samsung و Xiaomi را با مشخصات فارسی و رنگ‌های واقعی کنار هم "
                 "گذاشته‌ایم تا بدون سردرگمی، گوشی‌ای را انتخاب کنید که واقعاً به کارتان می‌آید."),
        "badges": [
            {"title": "اصل و با گارانتی", "text": "همراه با فاکتور رسمی و بررسی سلامت هنگام تحویل"},
            {"title": "ارسال رایگان همان روز", "text": "در سراسر مشهد، درِ منزل شما"},
            {"title": "اقساط با چک صیادی", "text": "بدون نیاز به ضامن"},
        ],
        "images": [],
    },
    "sections": [{"key": key, "show": True} for key in SECTION_KEYS],
    "phone_order": PHONE_ORDER_AUTO,
    "featured": [],
    "store": {
        "address": "۱۷ شهریور شمالی ۶، ابتدای کوچه آیت‌الله صدوقی، فروشگاه سوم سمت راست",
        "address_short": "۱۷ شهریور شمالی ۶، مشهد",
        "phone": "09155000432",
        "hours": [["شنبه تا پنج‌شنبه · صبح", "۹:۳۰ تا ۱۴"],
                  ["شنبه تا پنج‌شنبه · عصر", "۱۶:۳۰ تا ۲۱:۳۰"],
                  ["جمعه", "تعطیل"]],
        "about": ("در مشهد گوشی می‌فروشیم و کارمان این است که مدل درست را به دستتان برسانیم. "
                  "قیمت روز هر مدل را از ربات ما بپرسید؛ اگر مدلی به کارتان نمی‌خورد، همان اول "
                  "به شما می‌گوییم."),
        "bale": "https://ble.ir/asrertebatat2_bot",
        "telegram": "https://t.me/asrertebatat2_bot",
        "telegram_channel": "",
        "map": "",
    },
}

_TAG = re.compile(r"[<>]")
_PHONE_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_BALE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,63}$")
_TG_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def default_look() -> dict:
    return copy.deepcopy(DEFAULT_LOOK)


def text(value, limit: int, *, multiline: bool = False) -> str:
    """Plain text: no ``<`` / ``>``, spaces collapsed (lines kept when asked)."""
    if not isinstance(value, (str, int, float)):
        return ""
    value = _TAG.sub("", str(value))
    if multiline:
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line)[:limit]
    return " ".join(value.split())[:limit]


def image_name(value) -> str:
    name = str(value or "")
    return name if LOOK_IMAGE_RE.match(name) else ""


# ---- links and phone -------------------------------------------------------------------
def normalize_phone(value) -> str:
    """``۰۹۱۵ ۵۰۰ ۰۴۳۲`` -> ``09155000432``; "" when it is not a phone number."""
    digits = re.sub(r"[\s\-‌()]", "", str(value or "").translate(_PHONE_DIGITS))
    if digits.startswith("+98"):
        digits = "0" + digits[3:]
    return digits if re.fullmatch(r"0\d{9,10}", digits) else ""


def normalize_link(kind: str, value) -> tuple[str, str]:
    """(link, Persian problem). ``@name`` / ``name`` / ``t.me/name`` / a full link
    -> ``https://t.me/name``; an empty value is fine (the site keeps its own)."""
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if kind == "map":
        url = raw if raw.startswith("https://") else ""
        parts = urlsplit(url) if url else None
        host = (parts.hostname or "").lower() if parts else ""
        if (not parts or host not in MAP_HOSTS or len(url) > 300
                or any(c in url for c in " \"'<>\\")
                or (host in ("www.google.com", "google.com", "goo.gl")
                    and not parts.path.startswith("/maps"))):
            return "", ("پیوند نقشه باید پیوند «اشتراک‌گذاری» نشان، بلد یا گوگل‌مپ باشد "
                        "(با https:// شروع شود).")
        return url, ""
    domain = "ble.ir" if kind == "bale" else "t.me"
    name = raw.lstrip("@")
    for prefix in ("https://", "http://"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for host in ((domain, "www." + domain) if kind == "bale"
                 else ("t.me", "telegram.me", "www.t.me", "www.telegram.me")):
        if name.lower().startswith(host + "/"):
            name = name[len(host) + 1:]
            break
    name = name.split("?")[0].strip("/")
    pattern = _BALE_NAME if kind == "bale" else _TG_NAME
    if not pattern.match(name):
        return "", (f"نام کاربری {LINK_NAMES.get(kind, kind)} درست نیست "
                    f"(مثلاً @asrertebatat2_bot یا https://{domain}/asrertebatat2_bot).")
    return f"https://{domain}/{name}", ""


# ---- one look ----------------------------------------------------------------------------
def clean_look(raw) -> dict:
    """A complete, valid look: missing or invalid parts get the default."""
    raw = raw if isinstance(raw, dict) else {}
    look = default_look()
    if raw.get("palette") in PALETTE_KEYS:
        look["palette"] = raw["palette"]
    look["logo"] = image_name(raw.get("logo"))
    hero_raw = raw.get("hero") if isinstance(raw.get("hero"), dict) else {}
    hero = look["hero"]
    # v2.16.0: an empty text = the page's own text (= the default), never a blank
    for key in ("eyebrow", "title", "highlight", "lede"):
        if text(hero_raw.get(key), LIMITS[key]):
            hero[key] = text(hero_raw.get(key), LIMITS[key])
    badges = hero_raw.get("badges")
    if isinstance(badges, list):
        for n in range(BADGES):
            badge = badges[n] if n < len(badges) and isinstance(badges[n], dict) else {}
            if badge:
                base = hero["badges"][n]
                hero["badges"][n] = {
                    "title": text(badge.get("title"), LIMITS["badge_title"]) or base["title"],
                    "text": text(badge.get("text"), LIMITS["badge_text"]) or base["text"]}
    images = [image_name(n) for n in hero_raw.get("images") or [] if image_name(n)]
    hero["images"] = list(dict.fromkeys(images))[:BANNER_MAX]
    sections, seen = [], set()
    for row in raw.get("sections") or []:
        key = row.get("key") if isinstance(row, dict) else None
        if key in SECTION_KEYS and key not in seen:
            sections.append({"key": key, "show": bool(row.get("show", True))})
            seen.add(key)
    sections += [{"key": k, "show": True} for k in SECTION_KEYS if k not in seen]
    look["sections"] = sections
    if raw.get("phone_order") == PHONE_ORDER_MANUAL:
        look["phone_order"] = PHONE_ORDER_MANUAL
    featured = [c for c in raw.get("featured") or [] if isinstance(c, str)
                and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", c) and len(c) <= 62]
    look["featured"] = list(dict.fromkeys(featured))[:FEATURED_MAX]
    store_raw = raw.get("store") if isinstance(raw.get("store"), dict) else {}
    store = look["store"]
    for key in ("address", "address_short"):
        if text(store_raw.get(key), LIMITS[key]):
            store[key] = text(store_raw.get(key), LIMITS[key])
    if text(store_raw.get("about"), LIMITS["about"], multiline=True):
        store["about"] = text(store_raw.get("about"), LIMITS["about"], multiline=True)
    if "phone" in store_raw:
        store["phone"] = normalize_phone(store_raw.get("phone"))
    if isinstance(store_raw.get("hours"), list):
        hours = []
        for row in store_raw["hours"][:HOURS_MAX]:
            if isinstance(row, (list, tuple)) and len(row) == 2:
                label = text(row[0], LIMITS["hours_label"])
                value = text(row[1], LIMITS["hours_value"])
                if label or value:
                    hours.append([label, value])
        if hours:
            store["hours"] = hours
    for key in STORE_LINKS:
        if key in store_raw:
            store[key] = normalize_link(key, store_raw.get(key))[0]
    return look


def look_problems(look: dict) -> list[str]:
    """What the owner should fix before publishing (Persian; empty = fine).
    Never blocks the catalogue: the site keeps its own value for an empty field."""
    problems = []
    hero = look["hero"]
    if not hero["title"] and not hero["highlight"]:
        problems.append("عنوان بنر صفحهٔ اصلی خالی است.")
    if not any(s["show"] for s in look["sections"]):
        problems.append("همهٔ بخش‌های صفحهٔ اصلی پنهان‌اند.")
    return problems


def image_refs(look: dict) -> list[str]:
    return [n for n in [look.get("logo") or ""] + list(look["hero"]["images"]) if n]


# ---- site.json ---------------------------------------------------------------------------
def build_site_json(look: dict, brand_keys: list[str], visible_phones: list[str],
                    photos: dict[str, str], *, generated_at: str,
                    generator: str = "ShopAdmin") -> dict:
    """``photos``: look image name -> sha256 of the files that exist (a missing
    one is left out: the site keeps its own picture). ``visible_phones``: the
    codes of the phones shown on the site, in the working order."""
    look = clean_look(look)
    images = {}

    def photo(name: str) -> str:
        if not name or name not in photos:
            return ""
        images[LOOK_PREFIX + name] = photos[name]
        return LOOK_PREFIX + name

    visible = set(visible_phones)
    hero = dict(look["hero"])
    hero["images"] = [p for p in (photo(n) for n in hero["images"]) if p]
    # v2.16.0: a text the manager did not change goes out empty, so every page keeps
    # its own wording exactly as on the live site (the pages word the same address
    # a little differently: «، مشهد» / «· مشهد» / «— مشهد.»)
    base_hero, base_store = DEFAULT_LOOK["hero"], DEFAULT_LOOK["store"]
    for key in ("eyebrow", "title", "highlight", "lede"):
        if hero.get(key) == base_hero[key]:
            hero[key] = ""
    hero["badges"] = [{k: ("" if b.get(k) == base.get(k) else b.get(k, "")) for k in ("title", "text")}
                      for b, base in zip(hero.get("badges") or [], base_hero["badges"])]
    store = dict(look["store"])
    for key in ("address", "address_short", "about"):
        if store.get(key) == base_store[key]:
            store[key] = ""
    if store.get("hours") == base_store["hours"]:
        store["hours"] = []
    out = {"format": FORMAT, "version": VERSION, "generated_at": generated_at,
           "generator": generator, "palette": look["palette"]}
    logo = photo(look["logo"])
    if logo:
        out["logo"] = logo
    out.update({
        "hero": hero,
        "sections": look["sections"],
        "brand_order": list(brand_keys),
        "phone_order": look["phone_order"],
        "featured": [c for c in look["featured"] if c in visible],
        "store": store,
        "images": {path: {"sha256": sha} for path, sha in sorted(images.items())},
    })
    return out


def site_json_bytes(site: dict) -> bytes:
    return json.dumps(site, ensure_ascii=False, indent=1).encode("utf-8")


# ---- preview -----------------------------------------------------------------------------
def snapshot(site: dict | None) -> dict:
    """What the preview compares: the file without its time and generator."""
    if not isinstance(site, dict):
        return {}
    return {k: v for k, v in site.items() if k not in ("generated_at", "generator")}


def diff_lines(old: dict | None, new: dict, names: dict[str, str] | None = None, *,
               old_brand_order: list[str] | None = None) -> list[str]:
    """Short Persian lines of what changes in the look (``old`` / ``new``:
    snapshots; ``old`` empty = never published -> compared with the defaults and
    ``old_brand_order``, the brand order the site has now)."""
    names = names or {}
    if not old:
        base = build_site_json(default_look(), old_brand_order or new.get("brand_order") or [],
                               [], {}, generated_at="")
        old = snapshot(base)

    def same(key: str) -> bool:
        return json.dumps(old.get(key), sort_keys=True, ensure_ascii=False) == json.dumps(
            new.get(key), sort_keys=True, ensure_ascii=False)

    lines = []
    if not same("palette"):
        lines.append(f"🎨 رنگ‌بندی سایت: {PALETTE_NAMES.get(new.get('palette'), '')}")
    if not same("logo"):
        lines.append("🖼 لوگو " + ("عوض می‌شود" if new.get("logo") else "برداشته می‌شود (نشان «۲»)"))
    old_hero, new_hero = old.get("hero") or {}, new.get("hero") or {}
    changed = [fa for key, fa in (("eyebrow", "برچسب بالا"), ("title", "عنوان"),
                                  ("highlight", "بخش رنگی عنوان"), ("lede", "توضیح"),
                                  ("badges", "سه نشان"))
               if old_hero.get(key) != new_hero.get(key)]
    if changed:
        lines.append("✎ بنر صفحهٔ اصلی: " + "، ".join(changed))
    if old_hero.get("images") != new_hero.get("images"):
        lines.append(f"🖼 عکس‌های بنر: {len(new_hero.get('images') or [])} عکس"
                     if new_hero.get("images") else "🖼 عکس‌های بنر: همان عکس‌های برندها")
    if not same("sections"):
        shown = [SECTION_NAMES.get(s["key"], s["key"]) for s in new.get("sections") or []
                 if s.get("show")]
        hidden = [SECTION_NAMES.get(s["key"], s["key"]) for s in new.get("sections") or []
                  if not s.get("show")]
        line = "↕ بخش‌های صفحهٔ اصلی: " + " ← ".join(shown)
        if hidden:
            line += f" (پنهان: {'، '.join(hidden)})"
        lines.append(line)
    if not same("brand_order"):
        lines.append("↕ ترتیب برندها: " + "، ".join(names.get(k, k)
                                                   for k in new.get("brand_order") or []))
    if not same("phone_order"):
        lines.append("↕ ترتیب گوشی‌ها: " + ("دستی (همان ترتیب «چیدمان کالاها»)"
                                           if new.get("phone_order") == PHONE_ORDER_MANUAL
                                           else "خودکار (جدیدترین اول)"))
    if not same("featured"):
        lines.append("⭐ تازه‌ترین گوشی‌ها: " + ("، ".join(names.get(c, c)
                                                        for c in new.get("featured") or [])
                                                or "خودکار (۴ گوشی جدیدتر)"))
    old_store, new_store = old.get("store") or {}, new.get("store") or {}
    fields = [fa for key, fa in (("address", "آدرس"), ("address_short", "آدرس کوتاه"),
                                 ("phone", "تلفن"), ("hours", "ساعت کاری"), ("about", "درباره ما"),
                                 ("bale", "ربات بله"), ("telegram", "ربات تلگرام"),
                                 ("telegram_channel", "کانال تلگرام"), ("map", "نقشه"))
              if old_store.get(key) != new_store.get(key)]
    if fields:
        lines.append("✎ اطلاعات فروشگاه: " + "، ".join(fields))
    return lines
