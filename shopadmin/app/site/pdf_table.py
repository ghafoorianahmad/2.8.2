"""v2.14.0: a supplier's accessory PDF that is a TABLE — one row = one item.

The columns are found by their headers (any order, repeated on every page):
«ردیف»، «کد کالا»، «عنوان کالا»، «تصویر کالا»، «قیمت»، «توضیحات».

* title = «عنوان کالا»; its bracketed parts become the colour(s) («(مشکی)»,
  «(مشکی و سبز)»), the warranty («(گارانتی ۱۲ ماهه …)») and the type
  («(پاوربانک)»); the rest is the name;
* brand = first line of «توضیحات»; ``key: value`` lines are specs, the other
  lines the description;
* «کد کالا» is kept (local only: for finding the same item in the next list);
* the picture is the one drawn inside the same row (35 rows -> 35 pictures);
* the price column is dropped: only its numbers are remembered, so the publish
  check can refuse a title or a text that shows one of them.

Nothing is saved from here: ``read_table_pdf`` returns rows for the preview.
The category is never guessed: it is the branch the manager picked.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from . import catalog as cat
from . import textfix as tf

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PAGES = 80
MAX_ROWS = 600
RESOLUTION = 150
MIN_IMAGE_SIDE = 12      # points

COLUMNS = {
    "row": ("ردیف",),
    "code": ("کد کالا", "کد"),
    "title": ("عنوان کالا", "عنوان", "نام کالا", "شرح کالا"),
    "image": ("تصویر کالا", "تصویر", "عکس"),
    "price": ("قیمت", "قیمت فروش", "مبلغ"),
    "description": ("توضیحات", "مشخصات"),
}
COLOR_HEX = {
    "مشکی": "#1f1f22", "سفید": "#f4f4f2", "نارنجی": "#f08a24", "سبز": "#3b8f4f",
    "آبی": "#2f6fd6", "سرمه‌ای": "#1f2a52", "قرمز": "#d23a3a", "صورتی": "#f1a7c0",
    "بنفش": "#7b4bc4", "طلایی": "#d4af37", "نقره‌ای": "#c0c3c8", "خاکستری": "#8a8d93",
    "زرد": "#f3cd3c", "کرم": "#efe4cc", "قهوه‌ای": "#7a4e2d", "یاسی": "#c3a6e0",
    "فیروزه‌ای": "#2bb3b1", "بژ": "#d9c7a7", "گرافیتی": "#45474c", "تیتانیومی": "#8f8a81",
    "شفاف": "", "رزگلد": "#e0a899", "زرشکی": "#7c1f2e", "لیمویی": "#d7e34a",
}
_COLOR_FORMS = {tf.plain(name).replace(" ", ""): name for name in COLOR_HEX}
_COLOR_FORMS.update({tf.plain(k).replace(" ", ""): v for k, v in {
    "سورمه ای": "سرمه‌ای", "طوسی": "خاکستری", "رز گلد": "رزگلد", "تیتانیوم": "تیتانیومی",
    "نقره ای": "نقره‌ای", "آبی نفتی": "سرمه‌ای"}.items()})
_WARRANTY = ("گارانتی", "گارنتی", "ضمانت")
_BRACKET = re.compile(r"\(([^()]{1,80})\)")
_SPEC = re.compile(r"^\s*([^:：]{1,40}?)\s*[:：]+\s*(.{1,160})\s*$")
_SECTION_WORDS = {"specification", "specifications", "features", "feature", "مشخصات",
                  "ویژگی‌ها", "ویژگی ها"}


@dataclass
class TableRow:
    """One item of the table, as the preview shows it."""
    page: int
    number: str = ""
    product_code: str = ""
    raw_title: str = ""
    name: str = ""
    colors: list[str] = field(default_factory=list)
    brand_name: str = ""
    specs: list[list[str]] = field(default_factory=list)
    description: str = ""
    image: bytes | None = None
    prices: list[str] = field(default_factory=list)   # never saved; only for the price check
    notes: list[str] = field(default_factory=list)

    def item(self, group: str, code: str, image_name: str = "") -> dict:
        """The «سایت» item of this row (no price, ever)."""
        return {"code": code, "category": cat.KIND_ACCESSORY, "name": self.name,
                "brand_name": self.brand_name, "group": group, "specs": self.specs[:cat.MAX_SPECS],
                "description": self.description, "product_code": self.product_code,
                "colors": [{"name": c, "hex": COLOR_HEX.get(c, "")} for c in self.colors],
                "image": image_name, "hidden": False}


def _cell_lines(value) -> list[str]:
    return [line for line in (tf.clean_line(x) for x in str(value or "").split("\n")) if line]


def _header_map(cells: list) -> dict[str, int]:
    found = {}
    for index, value in enumerate(cells):
        text = tf.plain(" ".join(_cell_lines(value)))
        for key, names in COLUMNS.items():
            if key not in found and any(text == tf.plain(n) for n in names):
                found[key] = index
    return found if "title" in found else {}


def color_of(part: str) -> list[str]:
    """«مشکی و سبز» -> [مشکی, سبز]; [] when the part is not only colours."""
    pieces = [p for p in re.split(r"\s+و\s+|\s*(?:،|,|/|\+|-)\s*",tf.fix_chars(part).strip()) if p]
    names = []
    for piece in pieces:
        name = _COLOR_FORMS.get(tf.plain(piece).replace(" ", ""))
        if not name:
            return []
        names.append(name)
    return names


def split_title(title: str) -> tuple[str, list[str], list[list[str]]]:
    """(name, colours, specs) of an «عنوان کالا»: the colour, warranty and type
    brackets come out; what is left is the name."""
    colors: list[str] = []
    specs: list[list[str]] = []
    kinds = []

    def take(match: re.Match) -> str:
        inner = " ".join(match.group(1).split())
        found = color_of(inner)
        if found:
            colors.extend(c for c in found if c not in colors)
        elif any(word in inner for word in _WARRANTY):
            specs.append(["گارانتی", re.sub(r"^(?:گارانتی|گارنتی|ضمانت)\s*", "", inner).strip()
                          or inner])
        else:
            kinds.append(inner)
        return " "

    rest = _BRACKET.sub(take, tf.fix_chars(title))
    rest = re.sub(r"\s*[()]\s*", " ", rest)
    name = " ".join(rest.split())
    if kinds:
        specs.insert(0, ["نوع", "، ".join(kinds)])
        if not re.search(r"[A-Za-z0-9]", name):
            name = " ".join((" ".join(kinds) + " " + name).split())
    return name or " ".join(kinds), colors, specs


def split_description(lines: list[str]) -> tuple[str, list[list[str]], str]:
    """(brand, specs, description) of an «توضیحات» cell."""
    if not lines:
        return "", [], ""
    brand = lines[0][:40]
    specs: list[list[str]] = []
    text: list[str] = []
    for line in lines[1:]:
        if tf.plain(line) in _SECTION_WORDS:
            continue
        spec = _SPEC.match(line)
        if spec and len(specs) < cat.MAX_SPECS:
            key, value = spec.group(1).strip(" \"'"), spec.group(2).strip(" \"'")
            if key and value:
                specs.append([key[:40], value[:160]])
                continue
        if specs and (specs[-1][1].endswith((",", "،", "/")) or len(line) < 8)                 and len(specs[-1][1]) < 150:
            specs[-1][1] = (specs[-1][1] + " " + line)[:160]   # a wrapped value
            continue
        text.append(line)
    return brand, specs, " • ".join(text)[:600]


def _picture(page, image: dict) -> bytes | None:
    x0, top, x1, bottom = (float(image.get(k, 0)) for k in ("x0", "top", "x1", "bottom"))
    if min(x1 - x0, bottom - top) < MIN_IMAGE_SIDE:
        return None
    try:
        bbox = (max(0.0, x0), max(0.0, top), min(float(page.width), x1),
                min(float(page.height), bottom))
        rendered = page.crop(bbox).to_image(resolution=RESOLUTION).original
        buffer = io.BytesIO()
        rendered.convert("RGB").save(buffer, "JPEG", quality=90)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - a picture that cannot be drawn is reported as missing
        return None


def _row_picture(page, images: list[dict], top: float, bottom: float,
                 x_range: tuple[float, float] | None) -> bytes | None:
    """The biggest picture whose middle lies inside this row (and its column)."""
    best, area = None, 0.0
    for image in images:
        middle = (float(image["top"]) + float(image["bottom"])) / 2
        if not top <= middle <= bottom:
            continue
        if x_range is not None:
            centre = (float(image["x0"]) + float(image["x1"])) / 2
            if not x_range[0] - 4 <= centre <= x_range[1] + 4:
                continue
        size = (float(image["x1"]) - float(image["x0"])) * (float(image["bottom"]) - float(image["top"]))
        if size > area:
            best, area = image, size
    return _picture(page, best) if best else None


def read_table_pdf(data: bytes) -> list[TableRow]:
    """Every item row of the PDF's tables. Raises ValueError (Persian) when the
    file is not a readable PDF or has no table with an «عنوان کالا» column."""
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("فایل PDF خالی یا بزرگ‌تر از ۳۰ مگابایت است")
    if not data.startswith(b"%PDF"):
        raise ValueError("این فایل PDF نیست")
    import pdfplumber  # local import: heavy

    rows: list[TableRow] = []
    columns: dict[str, int] = {}
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                images = list(page.images or [])
                for table in page.find_tables():
                    cells = table.extract()
                    for geometry, values in zip(table.rows, cells):
                        header = _header_map(values)
                        if header:
                            columns = header
                            continue
                        if not columns or len(values) <= max(columns.values()):
                            continue
                        row = _row(number, page, images, geometry, values, columns)
                        if row is not None:
                            rows.append(row)
                        if len(rows) >= MAX_ROWS:
                            return rows
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - pdfminer raises many kinds
        raise ValueError("خواندن این PDF ممکن نشد") from None
    if not columns:
        raise ValueError("در این PDF جدولی با ستون «عنوان کالا» پیدا نشد")
    return rows


def _row(number: int, page, images, geometry, values: list, columns: dict[str, int]):
    def cell(key: str) -> list[str]:
        index = columns.get(key)
        return _cell_lines(values[index]) if index is not None and index < len(values) else []

    title = " ".join(cell("title"))
    if not title:
        return None
    name, colors, title_specs = split_title(title)
    brand, specs, description = split_description(cell("description"))
    code = re.sub(r"\D", "", tf.ascii_digits(" ".join(cell("code"))))[:20]
    row = TableRow(page=number, number=tf.ascii_digits(" ".join(cell("row")))[:6],
                   product_code=code, raw_title=title[:200], name=name[:120], colors=colors,
                   brand_name=brand, specs=(title_specs + specs)[:cat.MAX_SPECS],
                   description=description,
                   prices=[p for p in cell("price") if re.search(r"\d|[٠-٩۰-۹]", p)])
    top, bottom = float(geometry.bbox[1]), float(geometry.bbox[3])
    x_range = None
    index = columns.get("image")
    if index is not None and index < len(geometry.cells) and geometry.cells[index]:
        box = geometry.cells[index]
        x_range = (float(box[0]), float(box[2]))
    row.image = _row_picture(page, images, top, bottom, x_range)
    if row.image is None:
        row.notes.append("عکس ندارد")
    return row
