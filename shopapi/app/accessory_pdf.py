"""v2.10.0: accessory catalogues (PDF from a supplier) -> site accessories.

The real PDFs are not here yet, so the reader is deliberately simple and
tested with generated placeholder PDFs; once the owner sends real ones, only
the heuristics below should need tuning:

* every text line ``عنوان: مقدار`` (``:`` / ``：``) is a spec of the current item;
* any other line starts a new item (its title), unless it is a page header /
  footer (``SKIP_LINE``) or too short;
* every picture on the page belongs to the item whose title is the nearest
  one above the picture's top (or the first item of the page).

Nothing is added from here: ``read_pdf`` only returns candidates; ShopAdmin
shows them and ``site_export``-side code adds the ones the manager ticks.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from .catalog_models import valid_slug

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 60
MAX_ITEMS = 300
MAX_IMAGES_PER_ITEM = 6
MIN_IMAGE_SIDE = 60          # points: smaller pictures are logos / icons
RESOLUTION = 150

_SPEC = re.compile(r"^\s*([^:：]{1,40}?)\s*[:：]\s*(.{1,160})\s*$")
SKIP_LINE = re.compile(r"^(?:صفحه|page)\s*\d+|^www\.|^https?://|^\d+$|^[-–—_=]+$", re.IGNORECASE)
_LATIN = re.compile(r"[A-Za-z0-9]+")

#: words of each accessory group (the site has an icon for each)
GROUP_WORDS = {
    "case": ("قاب", "کاور", "گارد", "case", "cover"),
    "charger": ("شارژر", "آداپتور", "کابل", "شارژ", "charger", "adapter", "cable"),
    "headphones": ("هدفون", "هندزفری", "هدست", "ایرپاد", "ایربادز", "headphone", "earbud",
                   "earphone", "airpods", "buds", "headset"),
    "powerbank": ("پاوربانک", "پاور بانک", "powerbank", "power bank"),
}


@dataclass
class AccessoryCandidate:
    name: str
    page: int
    top: float
    specs: list[list[str]] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    code: str = ""
    group: str = "other"
    brand_name: str = ""

    def public(self) -> dict:
        """What ShopAdmin shows (no picture bytes)."""
        return {"code": self.code, "name": self.name, "page": self.page, "group": self.group,
                "brand_name": self.brand_name, "specs": self.specs,
                "image_count": len(self.images)}


def guess_group(text: str) -> str:
    low = (text or "").lower()
    for group, words in GROUP_WORDS.items():
        if any(w in low for w in words):
            return group
    return "other"


def suggest_code(name: str, taken: set[str], page: int, n: int) -> str:
    """A site code from the Latin words of the name (``anker-737-powerbank``);
    ``acc-p<page>-<n>`` when the name has none. Never one in ``taken``."""
    words = [w.lower() for w in _LATIN.findall(name or "")]
    base = "-".join(words)[:50].strip("-")
    if not base or not base[0].isalpha():
        base = f"acc-{base}" if base else f"acc-p{page}-{n}"
    base = re.sub(r"-+", "-", base)[:56]
    code, k = base, 2
    while code in taken or not valid_slug(code):
        code = f"{base}-{k}"
        k += 1
        if k > 999:
            code = f"acc-p{page}-{n}"
            break
    taken.add(code)
    return code


def _brand_name(name: str) -> str:
    words = [w for w in _LATIN.findall(name or "") if w[:1].isalpha()]
    return words[0][:40].title() if words else ""


def _picture(page, image: dict) -> bytes | None:
    x0, top, x1, bottom = (float(image.get(k, 0)) for k in ("x0", "top", "x1", "bottom"))
    if min(x1 - x0, bottom - top) < MIN_IMAGE_SIDE:
        return None
    try:
        bbox = (max(0.0, x0), max(0.0, top), min(float(page.width), x1),
                min(float(page.height), bottom))
        rendered = page.crop(bbox).to_image(resolution=RESOLUTION).original
        buffer = io.BytesIO()
        rendered.convert("RGB").save(buffer, "JPEG", quality=88)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - a picture that cannot be rendered is skipped
        return None


def read_pdf(data: bytes, *, taken_codes: set[str] | None = None) -> list[AccessoryCandidate]:
    """Candidates of one accessory PDF. Raises ValueError (Persian reason) for a
    file that is not a readable PDF."""
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("فایل PDF خالی یا بزرگ‌تر از ۲۰ مگابایت است")
    if not data.startswith(b"%PDF"):
        raise ValueError("این فایل PDF نیست")
    import pdfplumber  # local import: only the server needs it

    taken = set(taken_codes or ())
    items: list[AccessoryCandidate] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                page_items: list[AccessoryCandidate] = []
                for line in page.extract_text_lines() or []:
                    text = " ".join(str(line.get("text") or "").split())
                    if not text or SKIP_LINE.search(text):
                        continue
                    spec = _SPEC.match(text)
                    if spec and page_items:
                        page_items[-1].specs.append([spec.group(1).strip(), spec.group(2).strip()])
                    elif not spec and len(text) >= 3:
                        page_items.append(AccessoryCandidate(name=text[:120], page=number,
                                                             top=float(line.get("top") or 0)))
                for image in page.images or []:
                    if not page_items:
                        break
                    top = float(image.get("top") or 0)
                    above = [it for it in page_items if it.top <= top + 2]
                    owner = (above[-1] if above else page_items[0])
                    if len(owner.images) < MAX_IMAGES_PER_ITEM:
                        picture = _picture(page, image)
                        if picture:
                            owner.images.append(picture)
                items.extend(page_items)
                if len(items) >= MAX_ITEMS:
                    break
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - pdfminer raises many kinds
        raise ValueError("خواندن این PDF ممکن نشد") from None
    # a line with neither specs nor a picture is a heading («کاتالوگ ۱۴۰۵»), not an item
    items = [item for item in items if item.specs or item.images]
    for n, item in enumerate(items[:MAX_ITEMS], start=1):
        item.group = guess_group(item.name + " " + " ".join(v for _k, v in item.specs))
        item.brand_name = _brand_name(item.name)
        item.code = suggest_code(item.name, taken, item.page, n)
    return items[:MAX_ITEMS]


def site_data_for(item: AccessoryCandidate, image_names: list[str]) -> dict:
    """site_data of a new accessory (the first picture is its card)."""
    return {"published": True, "tier": "", "price_state": "استعلام قیمت",
            "image": image_names[0] if image_names else "", "colors": [],
            "specs": item.specs[:20], "group": item.group, "brand_key": "",
            "brand_name": item.brand_name}
