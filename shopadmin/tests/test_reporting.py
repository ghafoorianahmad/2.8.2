"""Tests for the report/export core (no Qt, no network)."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta

import pytest

from app.reporting import (
    DEFAULT_ORDER_STATUSES,
    build_customer_rows,
    build_order_rows,
    filter_by_range,
    shamsi_month_range,
    summarize,
    write_csv,
    write_xlsx,
)


def _order(order_id=1, total=100000.0, when="2025-01-01T10:00:00+00:00", status="written"):
    return {
        "id": order_id,
        "status": status,
        "total": total,
        "created_at": when,
        "user_name": "مشتری نمونه",
        "accounting_order_no": 5001,
        "items": [{"kala_code": 1, "name": "کالا", "qty": 2.0, "unit_price": 50000.0}],
    }


def _customer(customer_id=1, when="2025-01-01T10:00:00+00:00", status="approved"):
    return {
        "id": customer_id,
        "name": "مشتری نمونه",
        "platform": "telegram",
        "status": status,
        "person_code": 7001,
        "created_at": when,
    }


# ---- filtering ------------------------------------------------------------
def test_filter_by_range_is_inclusive():
    from app.persian import coerce_datetime

    start = coerce_datetime("2025-01-01T00:00:00+00:00").date()
    end = coerce_datetime("2025-01-03T00:00:00+00:00").date()
    rows = [
        _order(1, when="2024-12-31T10:00:00+00:00"),
        _order(2, when="2025-01-01T10:00:00+00:00"),
        _order(3, when="2025-01-03T10:00:00+00:00"),
        _order(4, when="2025-01-04T10:00:00+00:00"),
    ]
    kept = filter_by_range(rows, start, end)
    assert [row["id"] for row in kept] == [2, 3]


def test_filter_by_range_swaps_reversed_bounds():
    today = date.today()
    rows = [_order(1, when=datetime.now().isoformat())]
    assert len(filter_by_range(rows, today + timedelta(days=1), today - timedelta(days=1))) == 1


def test_filter_by_range_skips_unparseable_dates():
    assert filter_by_range([_order(when="garbage")], date(2000, 1, 1), date(2100, 1, 1)) == []


# ---- summarising ----------------------------------------------------------
def test_summarize_totals():
    orders = [_order(1, total=100.0), _order(2, total=250.5)]
    summary = summarize(orders, [_customer()], date(2000, 1, 1), date(2100, 1, 1))
    assert summary["order_count"] == 2
    assert summary["total_amount"] == pytest.approx(350.5)
    assert summary["new_customers"] == 1


def test_summarize_ignores_a_broken_total():
    orders = [_order(1, total=100.0), {**_order(2), "total": "not a number"}]
    summary = summarize(orders, [], date(2000, 1, 1), date(2100, 1, 1))
    assert summary["total_amount"] == pytest.approx(100.0)
    assert summary["order_count"] == 2


def test_summarize_with_no_orders():
    summary = summarize([], [], date(2000, 1, 1), date(2100, 1, 1))
    assert summary == {
        "order_count": 0,
        "total_amount": 0.0,
        "new_customers": 0,
        "customer_count": 0,
        "start": date(2000, 1, 1),
        "end": date(2100, 1, 1),
    }


# ---- row building ---------------------------------------------------------
def test_build_order_rows_sorts_newest_first_and_translates_status():
    rows = build_order_rows([
        _order(1, when="2025-01-01T10:00:00+00:00"),
        _order(2, when="2025-03-01T10:00:00+00:00", status="receipt_uploaded"),
    ])
    assert [row["id"] for row in rows] == [2, 1]
    assert rows[0]["status_fa"] == "رسید رسیده"
    assert rows[0]["items_count"] == 1


def test_build_customer_rows_translates_platform_and_status():
    rows = build_customer_rows([_customer(status="pending")])
    assert rows[0]["platform"] == "تلگرام"
    assert rows[0]["status_fa"] == "در انتظار تأیید"


def test_unknown_status_is_not_english():
    row = build_order_rows([_order(status="brand_new_status")])[0]
    assert row["status_fa"] == "نامشخص"


# ---- CSV ------------------------------------------------------------------
def test_write_csv_uses_utf8_bom_for_excel(tmp_path):
    path = tmp_path / "report.csv"
    count = write_csv(path, [_order()], [_customer()], (date(2025, 1, 1), date(2025, 1, 2)),
                      summarize([_order()], [_customer()], date(2025, 1, 1), date(2025, 1, 2)))
    assert count == 1
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Excel needs a UTF-8 BOM for Persian text"
    text = raw.decode("utf-8-sig")
    assert "شماره سفارش" in text
    assert "مشتری نمونه" in text
    assert "ریال" in text


def test_write_csv_numbers_are_persian_digits(tmp_path):
    path = tmp_path / "report.csv"
    write_csv(path, [_order(total=1234567.0)], [], (date(2025, 1, 1), date(2025, 1, 1)),
              summarize([_order(total=1234567.0)], [], date(2025, 1, 1), date(2025, 1, 1)))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    flat = " ".join(" ".join(row) for row in rows)
    assert "۱۲۳۴۵۶۷" in flat
    assert "1234567" not in flat


def test_write_csv_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deep" / "report.csv"
    write_csv(path, [], [], (date(2025, 1, 1), date(2025, 1, 1)), summarize([], [], date(2025, 1, 1), date(2025, 1, 1)))
    assert path.exists()


# ---- XLSX -----------------------------------------------------------------
def test_write_xlsx_creates_rtl_sheets(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "report.xlsx"
    count = write_xlsx(path, [_order()], [_customer()],
                       (date(2025, 1, 1), date(2025, 1, 2)),
                       summarize([_order()], [_customer()], date(2025, 1, 1), date(2025, 1, 2)))
    assert count == 1
    workbook = openpyxl.load_workbook(path)
    assert workbook.sheetnames == ["خلاصه", "سفارش‌ها", "مشتریان"]
    for sheet in workbook.worksheets:
        assert sheet.sheet_view.rightToLeft is True
    orders_sheet = workbook["سفارش‌ها"]
    headers = [cell.value for cell in orders_sheet[1]]
    assert headers[0] == "شماره سفارش"
    assert "مشتری نمونه" in [cell.value for row in orders_sheet.iter_rows() for cell in row]


def test_shamsi_month_range_starts_on_the_first():
    start, end = shamsi_month_range(datetime(2025, 1, 1))
    assert end == date(2025, 1, 1)
    assert start.day <= 23  # first of Dey 1403 is in December
    assert start <= end


def test_default_order_statuses_cover_the_seven_requested_tabs():
    assert len(DEFAULT_ORDER_STATUSES) == 7
    assert "written" in DEFAULT_ORDER_STATUSES
    assert "expired" in DEFAULT_ORDER_STATUSES
