"""v2.18.0: the channel's text posts: every case of the parser bundle's test data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pricelist import price_message as pm

CASES = json.loads((Path(__file__).parent / "data" / "price_messages_tests.json")
                   .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_case(case):
    parsed = pm.parse(case["message"], case["context_brand"])
    assert parsed.status == case["expected"]["status"], case["message"]
    assert [item.as_dict() for item in parsed.items] == case["expected"]["items"], case["message"]


def test_all_85_cases_are_there():
    assert len(CASES) == 85


def test_a_brand_header_carries_over():
    assert pm.parse("لیست قیمت محصولات برند TCH").context_brand == "TCH"
    parsed = pm.parse("تی سی اچ مدل One Pro / دو سیم کارت / ظرفیت 128 گیگابایت و رم 8 گیگابایت / قیمت : 48.000")
    assert parsed.status == pm.APPLIED and parsed.items[0].brand == "TCH"
    assert pm.parse("مدل One Pro / ظرفیت 128 گیگابایت / قیمت : 48.000", "TCH").items[0].brand == "TCH"


def test_a_date_stays_ignored():
    assert pm.parse("1405.08.12 / Tuesday").status == pm.IGNORED


# ---- the channel's posts on the active list --------------------------------------------------
from app.pricelist import notes as notes_mod  # noqa: E402
from app.pricelist.price_message import Item  # noqa: E402


def _rows():
    def row(key, description, color, naghd=95000):
        return {"row_key": key, "section": "SAMSUNG", "description": description, "color": color,
                "naghd": naghd, "raval": naghd + 2000, "price_rial": naghd * 10000, "action": ""}
    return [row("a", "A17 256GB Ram8", "Black"), row("b", "A17 256GB Ram8", "Blue"),
            row("c", "S25 FE 256GB", "Jetblack"), row("d", "S25 FE 256GB", "Navy"),
            row("e", "S25 FE 256GB", "Icyblue"), row("f", "A57 128GB Ram6", "Black"),
            row("g", "A57 256GB Ram8", "Black"), row("h", "A57 256GB Ram12", "Black")]


def test_rows_of_one_model_and_storage():
    keys = [r["row_key"] for r in notes_mod.rows_for_item(
        _rows(), Item("Samsung", "A17", 256, None, None, 95500))]
    assert keys == ["a", "b"]


def test_a_color_price_touches_only_that_color():
    keys = [r["row_key"] for r in notes_mod.rows_for_item(
        _rows(), Item("Samsung", "A17", 256, None, "Blue", 95500))]
    assert keys == ["b"]


def test_several_ram_sizes_and_none_named_is_not_certain():
    assert notes_mod.rows_for_item(_rows(), Item("Samsung", "A57", 256, None, None, 1)) == []
    keys = [r["row_key"] for r in notes_mod.rows_for_item(
        _rows(), Item("Samsung", "A57", 256, 12, None, 1))]
    assert keys == ["h"]


def test_a_different_storage_or_model_never_matches():
    assert notes_mod.rows_for_item(_rows(), Item("Samsung", "A17", 512, None, None, 1)) == []
    assert notes_mod.rows_for_item(_rows(), Item("Samsung", "A18", 256, None, None, 1)) == []
    assert notes_mod.rows_for_item(_rows(), Item("Samsung", None, 256, None, None, 1)) == []
