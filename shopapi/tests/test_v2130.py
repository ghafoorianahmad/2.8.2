"""v2.13.0: the 1405/08/05 price list (a sub-section with its own نقد/روال
header row) is read, a moved header still is a layout change, the PDF archive
(date + number, never deleted, reminders), «خواندن دوباره» and «دریافت لیست اکنون»."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.pricelist import parser
from app.pricelist.parser import ParseError, parse_pdf, parse_words

SAMPLE_0805 = Path(__file__).resolve().parents[2] / "samples" / "price_list_1405-08-05.pdf"


def _words(sub_header=None, rows=25):
    """Two blocks; ``sub_header`` = (x naghd, x raval, top) of a lower header pair."""
    words = [{"text": "1405/08/05", "x0": 450, "top": 20},
             {"text": "دقن", "x0": 150, "top": 40}, {"text": "لاور", "x0": 180, "top": 40},
             {"text": "دقن", "x0": 350, "top": 40}, {"text": "لاور", "x0": 380, "top": 40}]
    for i in range(rows):
        top = 52 + i * 11
        for base in (0, 200):
            words += [{"text": f"Model{base}{i}", "x0": base + 17, "top": top},
                      {"text": "تیکشر", "x0": base + 96, "top": top - 2},
                      {"text": "Black", "x0": base + 118, "top": top},
                      {"text": f"{100 + i},000", "x0": base + 145, "top": top - 1},
                      {"text": f"{101 + i},000", "x0": base + 174, "top": top - 1}]
    if sub_header:
        xn, xr, top = sub_header
        words += [{"text": "TABLET", "x0": 276, "top": top - 1},
                  {"text": "XIAOMI", "x0": 307, "top": top - 1},
                  {"text": "دقن", "x0": xn, "top": top}, {"text": "لاور", "x0": xr, "top": top}]
    return words


def test_sub_section_header_row_is_read():
    parsed = parse_words(_words(sub_header=(362, 389, 52 + 12 * 11 + 5)), 595)
    assert parsed.list_date == "1405/08/05"
    assert len(parsed.rows) == 50
    assert "TABLET XIAOMI" in parsed.sections
    # the rows below the sub-header belong to it
    below = [r for r in parsed.rows if r.block == 1 and r.top > 52 + 12 * 11 + 5]
    assert below and all(r.section == "TABLET XIAOMI" for r in below)


@pytest.mark.parametrize("sub_header", [
    (60, 389, 300),        # نقد far from the block's price column
    (362, 560, 300),       # the pair split over two blocks
])
def test_odd_lower_headers_are_still_a_layout_change(sub_header):
    with pytest.raises(ParseError, match="not on one line"):
        parse_words(_words(sub_header=sub_header), 595)


def test_a_single_lower_header_is_a_layout_change():
    words = _words() + [{"text": "دقن", "x0": 352, "top": 300}]
    with pytest.raises(ParseError, match="not on one line"):
        parse_words(words, 595)


@pytest.mark.skipif(not SAMPLE_0805.exists(), reason="samples/price_list_1405-08-05.pdf missing")
def test_real_list_of_1405_08_05():
    parsed = parse_pdf(SAMPLE_0805.read_bytes())
    assert parsed.list_date == "1405/08/05"
    assert len(parsed.rows) == 208
    assert parsed.warnings == []
    assert "TABLET XIAOMI" in parsed.sections
    pad = [r for r in parsed.rows if r.description == "Xiaomi Pad8 256GB Ram8"]
    assert pad and pad[0].section == "TABLET XIAOMI" and pad[0].naghd == 114500
    assert parser.decode_persian("تیکشر") == "شرکتی"
