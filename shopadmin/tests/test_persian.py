"""Tests for Persian digits and the Shamsi (Jalali) calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.persian import (
    PERSIAN_DIGITS,
    coerce_datetime,
    format_datetime_shamsi,
    format_int,
    format_money,
    format_qty,
    format_shamsi,
    format_shamsi_long,
    gregorian_to_jalali,
    jalali_to_gregorian,
    normalize_fa,
    relative_fa,
    shamsi_to_date,
    to_english_digits,
    to_persian_digits,
)


# ---- digits ---------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (123, "۱۲۳"),
        ("۰", "۰"),
        (1000000, "۱۰۰۰۰۰۰"),
        ("abc", "abc"),
        ("", ""),
    ],
)
def test_to_persian_digits(value, expected):
    assert to_persian_digits(value) == expected


def test_no_ascii_digit_survives_conversion():
    text = to_persian_digits("order 12345 total 6789.5")
    assert not any(ch.isascii() and ch.isdigit() for ch in text)
    assert "۱۲۳۴۵" in text


def test_to_english_digits_roundtrip():
    for raw in ("0123456789", "۹۸۷۶۵۴۳۲۱۰٠١٢٣٤٥٦٧٨٩"):
        assert to_english_digits(to_persian_digits(raw)) == to_english_digits(raw)
    assert to_english_digits("۱۲۳") == "123"
    assert to_english_digits("٤٥٦") == "456"  # Arabic-Indic


def test_persian_digits_constant_is_ten_chars():
    assert len(PERSIAN_DIGITS) == 10


# ---- number formatting ----------------------------------------------------
def test_format_int_uses_persian_digits_and_separator():
    text = format_int(1234567)
    assert text == "۱٬۲۳۴٬۵۶۷"
    assert "," not in text


def test_format_money_includes_toman():
    assert format_money(50000) == "۵۰٬۰۰۰ ریال"
    assert format_money(50000, with_unit=False) == "۵۰٬۰۰۰"


def test_format_qty_drops_trailing_zero_and_uses_persian_marks():
    assert format_qty(3.0) == "۳"
    assert format_qty(1234) == "۱٬۲۳۴"
    assert format_qty(2.5) == "۲٫۵"
    assert format_qty(1250.75) == "۱٬۲۵۰٫۷۵"
    text = format_qty(2.5)
    assert "." not in text and "," not in text


# ---- normalization --------------------------------------------------------
def test_normalize_fa_unifies_arabic_and_persian_letters():
    assert normalize_fa("كيان") == normalize_fa("کیان")
    assert normalize_fa("۰۹۱۲") == "0912"


# ---- Shamsi calendar ------------------------------------------------------
@pytest.mark.parametrize(
    "gregorian,jalali",
    [
        ((2025, 1, 1), (1403, 10, 12)),
        ((2025, 3, 21), (1404, 1, 1)),      # Nowruz
        ((2025, 4, 4), (1404, 1, 15)),
        ((2026, 3, 21), (1405, 1, 1)),
        ((2024, 12, 31), (1403, 10, 11)),
        ((2000, 1, 1), (1378, 10, 11)),
        ((1980, 6, 15), (1359, 3, 25)),
    ],
)
def test_gregorian_to_jalali_known_dates(gregorian, jalali):
    assert gregorian_to_jalali(*gregorian) == jalali


def test_jalali_roundtrip_across_many_days():
    current = date(1990, 1, 1)
    for _ in range(0, 20000, 7):
        jy, jm, jd = gregorian_to_jalali(current.year, current.month, current.day)
        assert jalali_to_gregorian(jy, jm, jd) == (current.year, current.month, current.day)
        current += timedelta(days=7)


def test_nowruz_maps_to_first_of_farwardin():
    # Nowruz falls on 20 or 21 March depending on the year; both are 1/1.
    for year, day in ((2020, 20), (2021, 21), (2022, 21), (2023, 21),
                      (2024, 20), (2025, 21), (2026, 21)):
        jy, jm, jd = gregorian_to_jalali(year, 3, day)
        assert (jm, jd) == (1, 1), year
        assert jy == year - 621


def test_the_day_before_nowruz_is_end_of_the_previous_year():
    jy, jm, jd = gregorian_to_jalali(2025, 3, 20)
    assert (jy, jm) == (1403, 12)
    assert jd in (29, 30)


def test_shamsi_year_lengths_are_sane():
    # Six 31-day months, five 30-day months, then Esfand.
    for jy in (1403, 1404, 1405):
        lengths = []
        for jm in range(1, 13):
            start = shamsi_to_date(jy, jm, 1)
            if jm == 12:
                lengths.append(29)
                continue
            nxt = shamsi_to_date(jy, jm + 1, 1)
            lengths.append((nxt - start).days)
        assert lengths[:6] == [31] * 6
        assert lengths[6:11] == [30] * 5


# ---- date formatting ------------------------------------------------------
def test_format_shamsi_uses_persian_digits_and_slashes():
    assert format_shamsi(date(2025, 1, 1)) == "۱۴۰۳/۱۰/۱۲"


def test_format_shamsi_accepts_iso_string_as_utc():
    text = format_shamsi("2025-01-01T10:00:00+00:00")
    assert text.startswith("۱۴۰۳/۱۰/")
    assert not any(ch.isascii() and ch.isdigit() for ch in text)


def test_format_shamsi_none_is_placeholder():
    assert format_shamsi(None) == "—"


def test_format_shamsi_long_names_month():
    assert format_shamsi_long(date(2025, 1, 1)) == "۱۲ دی ۱۴۰۳"


def test_format_datetime_includes_time():
    text = format_datetime_shamsi("2025-01-01T10:30:00+00:00")
    assert "/" in text and ":" in text
    assert not any(ch.isascii() and ch.isdigit() for ch in text)


def test_format_shamsi_with_weekday_is_persian():
    text = format_shamsi(date(2025, 1, 1), with_weekday=True)
    assert any(day in text for day in ("شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"))


def test_coerce_datetime_handles_bad_input():
    assert coerce_datetime(None) is None
    assert coerce_datetime("") is None
    assert coerce_datetime("not a date") is None
    assert coerce_datetime("2025-01-01").year == 2025


def test_relative_fa_is_persian():
    assert relative_fa(datetime.now()) == "لحظه‌ای پیش"
    assert "پیش" in relative_fa(datetime.now() - timedelta(hours=2))
