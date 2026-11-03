"""v2.18.0: the customer form's rules and the name matcher (the bundles' own test data)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import name_match, validators as v

DATA = Path(__file__).parent / "data"
PAIRS = json.loads((DATA / "name_match_tests.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PAIRS, ids=[c["id"] for c in PAIRS])
def test_name_match_cases(case):
    new, old = case["new"], case["existing"]
    result = name_match.match(new["first"], new["last"], new["national_code"], old["name"],
                              old["national_code"])
    assert result.verdict == case["expected_verdict"], result
    bands = {"same": (95, 100), "similar": (70, 94), "different": (0, 69)}
    low, high = bands[result.verdict]
    assert low <= result.score <= high


def test_name_match_has_all_the_bundles_cases():
    assert len(PAIRS) == 88


# ---- validators.test.js, case by case ------------------------------------------------------
def test_normalize_digits():
    assert v.normalize_digits("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert v.normalize_digits("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert v.normalize_digits("۰۰۸۴۵۷۵948") == "0084575948"
    assert v.normalize_digits("۱۲۳٤٥6") == "123456"
    assert v.normalize_digits("") == ""


@pytest.mark.parametrize("code,ok", [
    ("0084575948", True), ("0067749828", True), ("0499370899", True), ("0001001000", True),
    ("0010001001", True), ("۰۰۸۴۵۷۵۹۴۸", True), ("٠٠٦٧٧٤٩٨٢٨", True),
    ("0084575949", False), ("0067749821", False), ("1234567890", False),
    ("0000000000", False), ("1111111111", False), ("۹۹۹۹۹۹۹۹۹۹", False),
])
def test_iranian_code(code, ok):
    assert v.is_valid_iranian_national_code(code) is ok


def test_validate_national_code():
    check = v.validate_national_code("۰۰۸۴۵۷۵۹۴۸")
    assert (check.valid, check.normalized, check.kind, check.error) == (
        True, "0084575948", "iranian_10", "")
    check = v.validate_national_code("۹۸۷۶۵۴۳۲۱۰۱")
    assert (check.valid, check.normalized, check.kind) == (True, "98765432101", "foreign_11")
    check = v.validate_national_code("١٢٣٤٥٦٧٨٩٠١")
    assert (check.valid, check.normalized, check.kind) == (True, "12345678901", "foreign_11")
    assert not v.validate_national_code("۱۱۱۱۱۱۱۱۱۱۱").valid
    assert not v.is_valid_foreign_national_id("11111111111")
    for bad in ("12345", "123456789012", "008457594a", ""):
        assert not v.validate_national_code(bad).valid


def test_names():
    assert v.validate_first_name("علی").valid
    assert v.validate_first_name("محمد‌رضا").valid
    assert v.validate_last_name("طباطبایی نژاد").valid
    assert v.validate_first_name("علئ و کريم".replace("ک", "ك")).valid
    assert v.normalize_persian_letters("علي كريمي") == "علی کریمی"
    for bad in ("Ali", "علی۲", "علی 2", "ع", "   "):
        assert not v.validate_first_name(bad).valid
    assert not v.validate_last_name("احمدی-نژاد").valid
    assert v.validate_first_name("الف").valid


def test_addresses():
    assert v.validate_address("تهران، خیابان ولیعصر، کوچه بهار ۱۲ - پلاک ۴/۲.").valid
    assert v.validate_address("اصفهان، میدان نقش جهان، پلاک 15 - واحد 3/1.").valid
    for bad in ("تهران، خیابان Valiasr پلاک ۱۰", "تهران, خیابان آزادی", "تهران، پلاک ۱۰ @ واحد ۲",
                "تهران، پلاک ۱۰ (واحد ۲)", "تهران: خیابان آزادی", "۱۲۳۴۵ - ۶۷۸ / ۹۰.", ""):
        assert not v.validate_address(bad).valid, bad


def test_form_payload():
    check = v.validate_customer_form({
        "first_name": "  سارا ", "last_name": "کریمي", "national_code": "۰۰۸۴۵۷۵۹۴۸",
        "address": "شیراز، بلوار زند، کوچه ۱۰ - پلاک ۴/۲."})
    assert check["valid"]
    assert check["payload"] == {
        "v": 1, "type": "customer", "first_name": "سارا", "last_name": "کریمی",
        "national_code": "0084575948", "address": "شیراز، بلوار زند، کوچه ۱۰ - پلاک ۴/۲."}
