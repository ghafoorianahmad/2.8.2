"""v2.18.0: Persian product names: every test of the alias file, plus staff's teaching."""
from __future__ import annotations

import pytest

from app import product_aliases as pa

TESTS = pa.load_data()["tests"]


@pytest.mark.parametrize("case", TESTS, ids=[str(i) for i in range(len(TESTS))])
def test_file_case(case):
    assert pa.parse(case["input"]).formatted == case["expected"], case["input"]


def test_the_file_is_the_whole_one():
    data = pa.load_data()
    assert (len(data["brands"]), len(data["models"]), len(TESTS)) == (14, 122, 126)


@pytest.mark.parametrize("text", ["ايفون17پرومكس256", "آیفون ۱۷ پرومکس ۲۵۶", "iphone 17 pro max 256",
                                  "١٧ promax ٢٥٦"])
def test_spellings(text):
    parsed = pa.parse(text)
    assert (parsed.model, parsed.storage_gb) == ("iPhone 17 Pro Max", 256)


def test_nothing_known():
    assert pa.parse("سلام خوبید").formatted == pa.UNKNOWN and pa.parse("").confidence == "low"


def test_staff_teach_it(db):
    assert pa.parse("گوشی طلایی محسن").model is None
    pa.learn(db, "گوشی طلایی محسن", "iPhone 17 Pro Max", "boss")
    assert pa.parse("گوشی طلایی محسن", pa.load_learned(db)).model == "iPhone 17 Pro Max"
    with pytest.raises(ValueError):
        pa.learn(db, "x", "نه مدل", "boss")


def test_the_server_build_carries_the_data_files():
    from pathlib import Path

    build = (Path(__file__).resolve().parents[2] / "shopsystem" / "build_exe.bat").read_text(
        encoding="utf-8", errors="replace")
    assert "shopapi_app\\data;shopapi_app\\data" in build
    for name in ("product_aliases.json", "faq_fa.json"):
        assert (pa.DATA_FILE.parent / name).is_file(), name
