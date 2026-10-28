"""v2.14.0: a price list that is a PICTURE (PNG / JPG from a price channel).

The text comes from the OCR built into Windows (``ocr_windows.ps1``, nothing to
install; English recogniser: model names, colours and prices are Latin / ASCII
digits). The reader then finds the tables of the picture by their price columns
(several tables per picture), the brand / series headings (big text above a
table), and one row per line:

    name ("A 57 5G 8/256 vietnam"), colour, price (``228000`` or a range
    ``228000-229000`` / two columns ``475,000  476,000``), ``CALL`` / ``***``

A row is **doubtful** (never used, only shown) when anything is unsure: no
name, no price read (``***`` is drawn but often not read), a price that is not
a clean number, a range that goes down. Every row keeps its box, so the preview
shows the cropped picture of the row next to the values.

Image lists are never compared with the main (Abrishami) list and become the
price basis only after the owner's approval (``channels``).
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

OCR_SCRIPT = Path(__file__).with_name("ocr_windows.ps1")
OCR_TIMEOUT = 120
MIN_PRICE, MAX_PRICE = 1000, 50_000_000

_NUM = r"\d{1,3}(?:,\d{3})+|\d{3,8}"
PRICE_RE = re.compile(rf"^(?:{_NUM})$")
RANGE_RE = re.compile(rf"^({_NUM})\s*[-–]\s*(\d{{1,8}}(?:,\d{{3}})*)$")
CALL_RE = re.compile(r"^(?:CALL|cALL|Call|call)$")
STARS_RE = re.compile(r"^\*{3,}$")
PHONE_RE = re.compile(r"^0\d{9,11}$|^\d{3,4}[_-]\d{6,8}$")
DATE_RE = re.compile(r"^1[34]\d\d/\d\d/\d\d$")
COLORS = {"black", "white", "blue", "navy", "gray", "grey", "green", "gold", "silver", "pink",
          "purple", "purpel", "violet", "orange", "orang", "red", "yellow", "lime", "olive",
          "graphite", "graphit", "lavender", "cream", "teal", "brown", "mix", "jet", "titanium",
          "natural", "desert", "starlight", "midnight", "burgundy", "glacier", "sage", "mist",
          "skyblue", "icyblue", "icy", "light", "dark", "rose", "mint", "coral", "beige",
          "champagne", "copper", "bronze", "aqua", "cyan", "magenta", "charcoal", "jetblack"}


#: lower-case words that are normal in a model name
KNOWN_LOWER = {"vietnam", "india", "not", "pro", "max", "plus", "ultra", "lite", "mini", "and",
               "with", "new", "global", "dual", "sim", "wifi", "cellular", "fe"}


def is_color(text: str) -> bool:
    """«BLACK», «Icyblue», «Black/vietnam» …"""
    low = text.lower().strip(".,;:")
    return low in COLORS or any(c in low for c in COLORS if len(c) >= 4)


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> int:
        return self.x + self.w


@dataclass
class ImageRow:
    table: int
    brand: str = ""
    name: str = ""
    color: str = ""
    price_min: int | None = None
    price_max: int | None = None
    state: str = "ok"            # ok | call | unavailable | doubtful
    reasons: list[str] = field(default_factory=list)
    box: tuple[int, int, int, int] = (0, 0, 0, 0)   # x, y, w, h in the picture

    @property
    def usable(self) -> bool:
        return self.state == "ok"

    def public(self) -> dict:
        return {"table": self.table, "brand": self.brand, "name": self.name,
                "color": self.color, "price_min": self.price_min, "price_max": self.price_max,
                "state": self.state, "reasons": self.reasons, "box": list(self.box)}


class OcrUnavailable(RuntimeError):
    """This computer has no Windows OCR (not Windows, or no English recogniser)."""


def run_ocr(path: Path, scale: float = 2.0) -> dict:
    """The JSON of ``ocr_windows.ps1`` for one picture (raises OcrUnavailable)."""
    if sys.platform != "win32":
        raise OcrUnavailable("Windows OCR needs Windows")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(OCR_SCRIPT), str(path), str(scale)],
            capture_output=True, timeout=OCR_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise OcrUnavailable(f"OCR did not run: {type(exc).__name__}") from None
    try:
        data = json.loads(done.stdout.decode("utf-8-sig", "replace") or "{}")
    except ValueError:
        raise OcrUnavailable("OCR gave no result") from None
    if done.returncode != 0 or data.get("error"):
        raise OcrUnavailable(str(data.get("error") or "OCR failed"))
    return data


def words_of(ocr: dict) -> list[Word]:
    out = []
    for line in ocr.get("lines") or []:
        for word in line.get("words") or []:
            text = str(word.get("t") or "").strip()
            if text:
                out.append(Word(text, int(word["x"]), int(word["y"]), int(word["w"]),
                                int(word["h"])))
    return out


def _price_kind(text: str) -> str:
    """price | range | call | stars | '' (not a price)."""
    if PHONE_RE.match(text) or DATE_RE.match(text):
        return ""
    if PRICE_RE.match(text):
        return "price"
    if RANGE_RE.match(text):
        return "range"
    if CALL_RE.match(text):
        return "call"
    if STARS_RE.match(text):
        return "stars"
    return ""


def _number(text: str) -> int:
    return int(text.replace(",", ""))


def parse_range(text: str) -> tuple[int, int] | None:
    """``209000-210`` -> (209000, 210000): the short end keeps the long one's size."""
    match = RANGE_RE.match(text)
    if not match:
        return None
    low = _number(match.group(1))
    high_text = match.group(2).replace(",", "")
    width = len(str(low))
    high = int(high_text) * (10 ** (width - len(high_text))) if len(high_text) < width \
        else int(high_text)
    return low, high


def _clusters(values: list[float], tolerance: float) -> list[list[float]]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def read_words(words: list[Word], ink=None) -> list[ImageRow]:
    """The rows of the tables in these OCR words. ``ink(x0, y0, x1, y1)``: the
    share of dark pixels in a box of the picture (None = not checked)."""
    if not words:
        return []
    heights = [w.h for w in words if any(c.isdigit() for c in w.text)] or [w.h for w in words]
    unit = max(8.0, statistics.median(heights))
    # a number in big type is part of a heading («NOKIA 3210»), never a price
    prices = [w for w in words if _price_kind(w.text) and w.h <= 1.35 * unit]
    # price columns: x positions where many prices stand one under the other
    columns = [g for g in _clusters([w.cx for w in prices], 2.2 * unit) if len(g) >= 3]
    if not columns:
        return []
    centres = [statistics.median(g) for g in columns]
    # two columns close together on the same lines = one price range (min / max)
    tables: list[list[float]] = []
    for centre in centres:
        if tables and centre - tables[-1][-1] < 7 * unit:
            tables[-1].append(centre)
        else:
            tables.append([centre])
    headings = [w for w in words if w.h > 1.7 * unit and not _price_kind(w.text)]
    rows: list[ImageRow] = []
    left_edge = 0.0
    for index, cols in enumerate(tables):
        right_edge = (tables[index + 1][0] if index + 1 < len(tables) else 10 ** 9)
        lo, hi = cols[0] - 1.6 * unit, cols[-1] + 1.6 * unit
        mine = [w for w in prices if lo <= w.cx <= hi]
        # the words of this table: from the previous price column to this one, plus
        # colour words just right of it (a table with the colour after the price)
        body = [w for w in words if left_edge < w.cx < lo and w.h <= 1.7 * unit
                and not _price_kind(w.text)]
        after = [w for w in words if hi < w.cx < right_edge and w.cx - hi < 9 * unit
                 and w.h <= 1.7 * unit and not _price_kind(w.text)
                 and (is_color(w.text) or w.text.lower() in ("vietnam", "india", "global"))]
        lines = _clusters([w.cy for w in mine + body], 0.55 * unit)
        for line in lines:
            top, bottom = min(line) - 0.6 * unit, max(line) + 0.6 * unit
            row_prices = sorted((w for w in mine if top <= w.cy <= bottom), key=lambda w: w.x)
            row_words = sorted((w for w in body + after if top <= w.cy <= bottom),
                               key=lambda w: w.x)
            if not row_words and not row_prices:
                continue
            rows.append(_row(index, row_words, row_prices, unit, ink))
        heads = sorted((w for w in headings if left_edge - 2 * unit < w.cx < hi + 2 * unit),
                       key=lambda w: w.y)
        coloured = [r for r in rows if r.table == index and r.color]
        for row in rows:
            if row.table != index:
                continue
            if not row.color and len(coloured) * 2 >= sum(1 for r in rows if r.table == index):
                row.reasons.append("رنگ خوانده نشد")
                row.state = "doubtful"
            above = [h for h in heads if h.y < row.box[1]]
            if above:
                last = above[-1]
                row.brand = " ".join(h.text for h in heads if abs(h.cy - last.cy) < unit)
        left_edge = hi
    return rows


def _row(table: int, words: list[Word], prices: list[Word], unit: float, ink=None) -> ImageRow:
    price_x = min((p.x for p in prices), default=10 ** 9)
    # a word right of the price is the colour column («Icyblue vietnam»)
    colors = [w for w in words if is_color(w.text) or w.x > price_x]
    names = [w for w in words if w not in colors]
    every = words + prices
    x0 = min(w.x for w in every)
    y0 = min(w.y for w in every)
    x1 = max(w.right for w in every)
    y1 = max(w.y + w.h for w in every)
    row = ImageRow(table=table, name=" ".join(w.text for w in names),
                   color=" ".join(w.text for w in colors),
                   box=(x0, int(y0 - 0.2 * unit), x1 - x0, int(y1 - y0 + 0.4 * unit)))
    kinds = [_price_kind(w.text) for w in prices]
    numbers: list[int] = []
    for word, kind in zip(prices, kinds):
        if kind == "price":
            numbers.append(_number(word.text))
        elif kind == "range":
            numbers.extend(parse_range(word.text) or ())
    if not row.name:
        row.reasons.append("نام خوانده نشد")
    if names and prices:
        last = max(names, key=lambda w: w.right)
        first_after = min((w.x for w in colors + prices if w.x > last.right), default=None)
        # a price glued to the name («Iphone 16 128» read as a price) is not a price
        if any(0 <= p.x - last.right < 0.8 * unit for p in prices):
            row.reasons.append("عدد قیمت چسبیده به نام است")
        # dark text the English OCR did not read (a Persian word such as «شارژر»
        # inside the name) means the name is not complete
        if ink is not None and first_after is not None and first_after - last.right > unit:
            share = ink(last.right + 3, row.box[1] + 2, first_after - 3,
                        row.box[1] + row.box[3] - 2)
            if share > 0.05:
                row.reasons.append("متن خوانده‌نشده (فارسی) کنار نام")
        # the same between two words of the name («45W شرکتی Original»)
        ordered = sorted(names, key=lambda w: w.x)
        for a, b in zip(ordered, ordered[1:]):
            if ink is not None and b.x - a.right > 1.2 * unit and \
                    ink(a.right + 3, row.box[1] + 2, b.x - 3, row.box[1] + row.box[3] - 2) > 0.05:
                row.reasons.append("متن خوانده‌نشده (فارسی) میان نام")
                break
    if "call" in kinds and not numbers:
        row.state = "call"
    elif "stars" in kinds and not numbers:
        row.state = "unavailable"
    elif not numbers:
        row.reasons.append("قیمت خوانده نشد (*** یا ناخوانا)")
    elif len(numbers) > 2:
        row.reasons.append("بیش از دو عدد قیمت")
    else:
        row.price_min, row.price_max = min(numbers), max(numbers)
        if len(numbers) == 2 and numbers[1] < numbers[0]:
            row.reasons.append("بازهٔ قیمت رو به پایین است")
        if not all(MIN_PRICE <= n <= MAX_PRICE for n in numbers):
            row.reasons.append("قیمت بیرون از بازهٔ معمول")
    tokens = row.name.split()
    if tokens and not any(re.search(r"[A-Za-z]", t) and t.upper() not in ("5G", "4G")
                          for t in tokens):
        row.reasons.append("نام کامل خوانده نشد")
    if any(re.match(r"^\d+/\d+$", t) and not re.match(r"^\d{1,2}/\d{2,4}$", t) for t in tokens) \
            or any("II" in t or "Il" in t or "lI" in t for t in tokens) \
            or any(re.match(r"^[a-z]$", t) for t in tokens):
        row.reasons.append("بخشی از نام نامطمئن خوانده شد (حافظه / I و 1)")
    if any(re.match(r"^[A-Z][SOIZB]$", t) for t in tokens):
        row.reasons.append("حرف یا عدد نامطمئن (S/5، O/0، I/1…)")
    if re.search(r"[^\w\s/+().\-&]", row.name):
        row.reasons.append("نویسهٔ نامعلوم در نام")
    # a lower-case piece in a name written in capitals («POCO cn 4/128») is a misreading
    caps = [t for t in row.name.split() if t.isalpha() and t.isupper()]
    odd = [t for t in row.name.split() if t.isalpha() and t.islower() and t not in KNOWN_LOWER]
    if caps and odd:
        row.reasons.append("بخشی از نام نامطمئن خوانده شد")
    if row.reasons:
        row.state = "doubtful"
    return row


def _key(row: ImageRow) -> tuple:
    return (" ".join(row.name.upper().split()), row.color.upper(), row.price_min, row.price_max)


def agree(first: list[ImageRow], second: list[ImageRow], unit: float = 12.0) -> list[ImageRow]:
    """Two readings of the same picture (different scales): a row is usable only
    when the other reading has the same row (same place) with the same values."""
    for row in first:
        if row.state != "ok":
            continue
        cx, cy = row.box[0] + row.box[2] / 2, row.box[1] + row.box[3] / 2
        twin = min(second, default=None, key=lambda r: abs(r.box[1] + r.box[3] / 2 - cy)
                   + abs(r.box[0] + r.box[2] / 2 - cx))
        if twin is None or abs(twin.box[1] + twin.box[3] / 2 - cy) > unit                 or _key(twin) != _key(row):
            row.state = "doubtful"
            row.reasons.append("دو بار خواندن یکسان نبود")
    return first


def ink_meter(path: Path):
    """``ink(x0, y0, x1, y1)`` -> share of dark pixels (text) in that box."""
    from PIL import Image

    gray = Image.open(path).convert("L")

    def ink(x0, y0, x1, y1) -> float:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(gray.width, int(x1)), min(gray.height, int(y1))
        if x1 - x0 < 3 or y1 - y0 < 3:
            return 0.0
        box = gray.crop((x0, y0, x1, y1))
        dark = sum(box.histogram()[:96])
        return dark / max(1, box.width * box.height)
    return ink


def read_image(path: Path, *, scales: tuple[float, ...] = (2.0, 3.0)) -> list[ImageRow]:
    ink = ink_meter(path)
    readings = [read_words(words_of(run_ocr(path, scale)), ink) for scale in scales]
    rows = readings[0]
    for other in readings[1:]:
        rows = agree(rows, other)
    return rows
