"""Parse the distributor's price-list PDF (channel AbrishamiiPhoneMashhad).

The PDF is Excel-generated, one A4 page, text based. Its layout (verified on
``samples/price_list.pdf``, 1405/07/19):

* a date at the top (``1405/07/19``);
* three side-by-side blocks (left: iPhone, AirPods, Watch, MacBook, …;
  middle: Xiaomi, POCO, iPad, Nokia, …; right: Samsung + Samsung tablets),
  each with its own ``نقد`` / ``روال`` header cells and sub-section titles;
* one row per variant: description (model, storage/RAM, region such as
  ZAA/CHA) | type (شرکتی/ویتنام/هند) | color | نقد | روال. Prices are in
  thousand Toman; ``...``/``…``/``Call`` = no price.

Persian text comes out of the PDF with its letters reordered (``تیکشر`` for
شرکتی), so Persian words are recognised by their *multiset of letters*, never
by spelling, and cells are assigned to columns by x position. Price cells sit
1–2 pt above or below their row, so rows are anchored on the description
cells and every other cell joins the nearest anchor.

Anything unexpected (no date, no ``نقد``/``روال`` headers, no type column, too
few rows, too few price cells) raises ``ParseError``: the caller then keeps the
last good prices (REQUIREMENTS §5 safety).
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field

#: Below this many data rows the file is not the price list we know.
MIN_ROWS = 20
#: Share of rows that must have a price cell (a number or "no price").
MIN_PRICED_SHARE = 0.8

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ـ": None})
_ARABIC_SCRIPT = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
_DATE = re.compile(r"(1[34]\d\d)/(\d{1,2})/(\d{1,2})")
_PRICE = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{1,7}$")
#: Cells that mean "no price" (unavailable).
NO_PRICE_MARKERS = frozenset({"...", "…", "..", "call", "-", "--", "—"})

#: Persian words we expect, recognised from their scrambled extraction.
KNOWN_WORDS = (
    "نقد", "روال", "شرکتی", "ویتنام", "هند", "چین", "امارات", "اروپا", "پک", "کارتن",
    "مونتاژ", "فارسی", "کیت", "خور", "بدون", "اکتیو", "نات", "ریجستر", "رجیستر",
)


def _clean(text: str) -> str:
    return text.translate(_LETTERS).replace("‌", "").replace("‏", "").replace(
        "‎", "").replace(" ", "")


def letter_signature(text: str) -> str:
    """Sorted letters: the same for شرکتی and its extracted form تیکشر."""
    return "".join(sorted(_clean(text)))


_KNOWN_BY_SIG = {letter_signature(w): w for w in KNOWN_WORDS}
_SIG_NAGHD = letter_signature("نقد")
_SIG_RAVAL = letter_signature("روال")
_KIND_SIGS = {letter_signature(w) for w in ("شرکتی", "ویتنام", "هند", "چین", "امارات", "اروپا")}


def is_persian(text: str) -> bool:
    return bool(_ARABIC_SCRIPT.search(text or ""))


def decode_persian(text: str) -> str:
    """Best effort: a known word from its scrambled letters, else the text as is."""
    return _KNOWN_BY_SIG.get(letter_signature(text), text)


def parse_price(text: str | None) -> int | None:
    """``535,000`` -> 535000 (thousand Toman). No number -> None."""
    value = (text or "").strip().translate(_PERSIAN_DIGITS).replace("٬", ",")
    if not value or not _PRICE.match(value):
        return None
    return int(value.replace(",", ""))


def normalize_key_part(text: str) -> str:
    value = (text or "").translate(_LETTERS).replace("‌", " ").lower()
    return " ".join(value.split())


def make_row_key(description: str, kind: str, color: str) -> str:
    """Stable identity of a PDF row across lists: description | type | color."""
    return "|".join(normalize_key_part(p) for p in (description, kind, color))


class ParseError(Exception):
    """The PDF does not look like the known price list (layout change)."""


@dataclass(frozen=True)
class PriceRow:
    block: int            # 0 = left, 1 = middle, 2 = right
    section: str          # brand / sub-section title (iPHONE, APPLE WATCH, …)
    description: str      # model, storage, RAM, region
    kind: str             # شرکتی / ویتنام / هند / ''
    color: str
    naghd: int | None     # thousand Toman, None = no price
    raval: int | None
    top: float = 0.0

    @property
    def key(self) -> str:
        return make_row_key(self.description, self.kind, self.color)


@dataclass
class ParsedList:
    list_date: str                       # Jalali, zero padded: 1405/07/19
    rows: list[PriceRow] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Block:
    left: float
    right: float
    naghd_x: float
    raval_x: float
    kind_x: float | None = None
    title: str = ""

    @property
    def price_left(self) -> float:
        return self.naghd_x - 14

    @property
    def price_split(self) -> float:
        return (self.naghd_x + self.raval_x) / 2 + 4

    @property
    def desc_right(self) -> float:
        return (self.kind_x - 8) if self.kind_x is not None else self.price_left - 40


def _lines(words: list[dict], tolerance: float = 1.5) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _find_date(words: list[dict]) -> str:
    for word in sorted(words, key=lambda w: w["top"]):
        match = _DATE.search(str(word["text"]).translate(_PERSIAN_DIGITS))
        if match:
            y, m, d = (int(g) for g in match.groups())
            if 1 <= m <= 12 and 1 <= d <= 31:
                return f"{y:04d}/{m:02d}/{d:02d}"
    raise ParseError("no date found")


def _header_words(words: list[dict]) -> list[dict]:
    return [w for w in words if letter_signature(w["text"]) in (_SIG_NAGHD, _SIG_RAVAL)]


def _find_blocks(words: list[dict], page_width: float) -> tuple[list[_Block], float]:
    headers = _header_words(words)
    if not headers:
        raise ParseError("price headers (نقد/روال) not found")
    header_top = min(w["top"] for w in headers)
    # The column headers are the top line. A sub-section lower down (e.g.
    # "XIAOMI TABLET", 1405/08/05) may repeat its own نقد/روال pair: those are
    # checked in parse_words and skipped, they never define new blocks.
    top_line = [w for w in headers if w["top"] - header_top <= 6]
    naghd = sorted((w for w in top_line if letter_signature(w["text"]) == _SIG_NAGHD),
                   key=lambda w: w["x0"])
    raval = sorted((w for w in top_line if letter_signature(w["text"]) == _SIG_RAVAL),
                   key=lambda w: w["x0"])
    if not naghd or len(naghd) != len(raval):
        raise ParseError("price headers (نقد/روال) not found")
    blocks: list[_Block] = []
    left = 0.0
    for n, r in zip(naghd, raval):
        if not n["x0"] < r["x0"]:
            raise ParseError("unexpected price header order")
        right = r["x0"] + 16
        blocks.append(_Block(left=left, right=right, naghd_x=n["x0"], raval_x=r["x0"]))
        left = right
    blocks[-1].right = max(blocks[-1].right, page_width)
    return blocks, header_top


def _check_sub_headers(blocks: list[_Block], header_top: float,
                       words: list[dict]) -> set[int]:
    """ids of نقد/روال cells below the top line, after checking they are a
    sub-section's header: a نقد then روال pair on one line, inside one block,
    over that block's price columns. Anything else is a different layout."""
    lower = [w for w in _header_words(words) if w["top"] - header_top > 6]
    found: set[int] = set()
    for line in _lines(lower, tolerance=3):
        if len(line) % 2:
            raise ParseError("price headers are not on one line")
        for n, r in zip(line[::2], line[1::2]):
            index = _block_of(blocks, n["x0"])
            if (letter_signature(n["text"]) != _SIG_NAGHD
                    or letter_signature(r["text"]) != _SIG_RAVAL
                    or index is None or _block_of(blocks, r["x0"]) != index
                    or abs(n["x0"] - blocks[index].naghd_x) > 20
                    or abs(r["x0"] - blocks[index].raval_x) > 20):
                raise ParseError("price headers are not on one line")
            found.update((id(n), id(r)))
    return found


def _block_of(blocks: list[_Block], x0: float) -> int | None:
    for index, block in enumerate(blocks):
        if block.left <= x0 < block.right:
            return index
    return None


def _kind_column(block_words: list[dict], block: _Block) -> float | None:
    """x of the type column: where words such as شرکتی/ویتنام sit (fragments too)."""
    xs = [round(w["x0"]) for w in block_words
          if w["x0"] < block.price_left and letter_signature(w["text"]) in _KIND_SIGS]
    if not xs:
        return None
    return float(Counter(xs).most_common(1)[0][0])


def _join(words: list[dict]) -> str:
    return " ".join(str(w["text"]).strip() for w in words if str(w["text"]).strip())


def _decode_words(words: list[dict]) -> str:
    return " ".join(decode_persian(t) if is_persian(t) else t
                    for t in (str(w["text"]).strip() for w in words) if t)


def parse_words(words: list[dict], page_width: float) -> ParsedList:
    """Parse pdfplumber words (dicts with text, x0, top). Separate for tests."""
    if not words:
        raise ParseError("the PDF has no text")
    list_date = _find_date(words)
    blocks, header_top = _find_blocks(words, page_width)
    sub_headers = _check_sub_headers(blocks, header_top, words)

    per_block: list[list[dict]] = [[] for _ in blocks]
    for word in words:
        if id(word) in sub_headers:
            continue                     # a sub-section's own نقد/روال cells
        index = _block_of(blocks, word["x0"])
        if index is None:
            continue
        if word["top"] < header_top - 6:
            continue                     # date, channel name
        if word["top"] < header_top - 0.5:
            # Block title on the line just above the headers.
            blocks[index].title = (blocks[index].title + " " + str(word["text"])).strip()
            continue
        sig = letter_signature(word["text"])
        if word["top"] <= header_top + 3 and sig in (_SIG_NAGHD, _SIG_RAVAL):
            continue                     # the header cells themselves
        per_block[index].append(word)

    parsed = ParsedList(list_date=list_date)
    priced_rows = 0
    for index, (block, block_words) in enumerate(zip(blocks, per_block)):
        block.kind_x = _kind_column(block_words, block)
        if block.kind_x is None:
            raise ParseError(f"block {index + 1}: no type column (شرکتی/ویتنام)")
        rows, headers, priced = _parse_block(index, block, block_words, parsed.warnings)
        priced_rows += priced
        parsed.rows.extend(rows)
        for title in [block.title, *headers]:
            if title and title not in parsed.sections:
                parsed.sections.append(title)

    if len(parsed.rows) < MIN_ROWS:
        raise ParseError(f"only {len(parsed.rows)} rows found")
    if priced_rows < MIN_PRICED_SHARE * len(parsed.rows):
        raise ParseError("too many rows without a price cell")
    # The same row twice in one list: keep the first, report the rest.
    seen: set[str] = set()
    unique: list[PriceRow] = []
    for row in parsed.rows:
        if row.key in seen:
            parsed.warnings.append(f"duplicate row: {row.description} {row.color}")
            continue
        seen.add(row.key)
        unique.append(row)
    parsed.rows = unique
    return parsed


def _parse_block(index: int, block: _Block, words: list[dict], warnings: list[str]):
    lines = _lines(words)
    anchors: list[dict] = []          # {"top", "desc", "kind", "color", "naghd", "raval"}
    orphans: list[tuple[float, list[dict]]] = []
    pending: list[list[dict]] = []

    def new_anchor(top: float) -> dict:
        return {"top": top, "desc": [], "kind": [], "color": [], "naghd": [], "raval": []}

    for line in lines:
        desc = [w for w in line if w["x0"] < block.desc_right]
        if desc:
            anchor = new_anchor(line[0]["top"])
            anchors.append(anchor)
            _distribute(block, anchor, line)
        else:
            pending.append(line)

    for line in pending:
        top = line[0]["top"]
        nearest = min(anchors, key=lambda a: abs(a["top"] - top), default=None)
        if nearest is not None and abs(nearest["top"] - top) <= 4.5:
            _distribute(block, nearest, line)
        else:
            orphans.append((top, line))

    # Section titles: description-only lines and stray Latin lines (e.g. OROD).
    headers: list[tuple[float, str]] = []
    data: list[dict] = []
    for anchor in anchors:
        # Every data row has a price cell (a number or "..."); a title such as
        # "APPLE WATCH" may reach into the color column but has no price/type.
        if not (anchor["kind"] or anchor["naghd"] or anchor["raval"]):
            headers.append((anchor["top"], _join(sorted(
                anchor["desc"] + anchor["color"], key=lambda w: w["x0"]))))
        else:
            data.append(anchor)
    for top, line in orphans:
        text = _join(line)
        if text and not is_persian(text) and all(parse_price(w["text"]) is None for w in line):
            headers.append((top, text))
        elif text:
            warnings.append(f"block {index + 1}: stray cell ignored")

    marks = sorted(headers)
    rows: list[PriceRow] = []
    priced = 0
    for anchor in sorted(data, key=lambda a: a["top"]):
        section = block.title
        for top, title in marks:
            if top < anchor["top"]:
                section = title
        naghd_cells = [str(w["text"]).strip() for w in anchor["naghd"]]
        raval_cells = [str(w["text"]).strip() for w in anchor["raval"]]
        if naghd_cells or raval_cells:
            priced += 1
        for cell in naghd_cells + raval_cells:
            if parse_price(cell) is None and cell.lower() not in NO_PRICE_MARKERS:
                warnings.append(f"unreadable price cell in block {index + 1}")
        rows.append(PriceRow(
            block=index,
            section=section,
            description=_decode_words(anchor["desc"]),
            kind=decode_persian("".join(str(w["text"]) for w in anchor["kind"]))
            if anchor["kind"] else "",
            color=_join(anchor["color"]).replace("‌", "").strip(),
            naghd=_first_price(naghd_cells),
            raval=_first_price(raval_cells),
            top=anchor["top"],
        ))
    return rows, [title for _, title in marks], priced


def _first_price(cells: list[str]) -> int | None:
    for cell in cells:
        value = parse_price(cell)
        if value is not None:
            return value
    return None


def _distribute(block: _Block, anchor: dict, line: list[dict]) -> None:
    for word in line:
        x0 = word["x0"]
        text = str(word["text"])
        if x0 < block.desc_right:
            anchor["desc"].append(word)
        elif x0 >= block.price_left:
            anchor["naghd" if x0 < block.price_split else "raval"].append(word)
        elif is_persian(text):
            anchor["kind"].append(word)
        else:
            anchor["color"].append(word)


def parse_pdf(data: bytes) -> ParsedList:
    """Parse the PDF bytes. Raises ParseError for anything not like the known list."""
    if not data.startswith(b"%PDF"):
        raise ParseError("not a PDF file")
    try:
        import pdfplumber  # local import: only the server needs it
    except ImportError as exc:  # pragma: no cover - deployment problem
        raise ParseError("pdfplumber is not installed") from exc
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) != 1:
                raise ParseError(f"expected 1 page, got {len(pdf.pages)}")
            page = pdf.pages[0]
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            width = float(page.width)
    except ParseError:
        raise
    except Exception as exc:  # pdfminer raises many types for broken files
        raise ParseError(f"unreadable PDF ({type(exc).__name__})") from exc
    return parse_words(
        [{"text": w["text"], "x0": float(w["x0"]), "top": float(w["top"])} for w in words],
        width,
    )
