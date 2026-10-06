"""Report building and Persian-friendly export (CSV with BOM, and XLSX).

Pure functions so they can be unit-tested without Qt or a network.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .persian import (
    coerce_datetime,
    format_money,
    format_shamsi,
    gregorian_to_jalali,
    to_persian_digits,
)

#: Every order status this application can report on.
DEFAULT_ORDER_STATUSES: tuple[str, ...] = (
    "awaiting_payment",
    "receipt_uploaded",
    "approved",
    "rejected",
    "expired",
    "written",
    "cancelled",
)

_ORDER_HEADERS = (
    "شماره سفارش",
    "نام مشتری",
    "تعداد اقلام",
    "مبلغ کل (تومان)",
    "وضعیت",
    "شماره حسابداری",
    "تاریخ ثبت",
)

_CUSTOMER_HEADERS = (
    "شناسه مشتری",
    "نام مشتری",
    "پلتفرم",
    "وضعیت",
    "کد شخص",
    "تاریخ ثبت‌نام",
)


def _status_fa(status: object) -> str:
    from .statuses import order_status_fa

    return order_status_fa(str(status or ""))


def _customer_status_fa(status: object) -> str:
    from .statuses import customer_status_fa

    return customer_status_fa(str(status or ""))


def _platform_fa(platform: object) -> str:
    from .statuses import platform_fa

    return platform_fa(str(platform or ""))


# --------------------------------------------------------------------------
# filtering / summarising
# --------------------------------------------------------------------------
def filter_by_range(
    rows: Iterable[dict],
    start: date,
    end: date,
    *,
    field: str = "created_at",
) -> list[dict]:
    """Keep rows whose ``field`` falls inside ``[start, end]`` (inclusive)."""
    if end < start:
        start, end = end, start
    kept: list[dict] = []
    for row in rows:
        moment = coerce_datetime(row.get(field))
        if moment is None:
            continue
        day = moment.date()
        if start <= day <= end:
            kept.append(row)
    return kept


def summarize(orders: Sequence[dict], customers: Sequence[dict],
              start: date, end: date) -> dict[str, Any]:
    total = 0.0
    for order in orders:
        try:
            total += float(order.get("total") or 0)
        except (TypeError, ValueError):
            continue
    new_customers = filter_by_range(customers, start, end, field="created_at")
    return {
        "order_count": len(orders),
        "total_amount": total,
        "new_customers": len(new_customers),
        "customer_count": len(customers),
        "start": start,
        "end": end,
    }


# --------------------------------------------------------------------------
# row builders (already Persian-formatted for display/export)
# --------------------------------------------------------------------------
def build_order_rows(orders: Sequence[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        rows.append({
            "id": order.get("id"),
            "customer": order.get("user_name") or "—",
            "items_count": len(order.get("items") or []),
            "total": float(order.get("total") or 0),
            "status": order.get("status"),
            "status_fa": _status_fa(order.get("status")),
            "accounting_order_no": order.get("accounting_order_no"),
            "created_at": order.get("created_at"),
        })
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def build_customer_rows(customers: Sequence[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for customer in customers:
        rows.append({
            "id": customer.get("id"),
            "name": customer.get("name") or "—",
            "platform": _platform_fa(customer.get("platform")),
            "status_fa": _customer_status_fa(customer.get("status")),
            "person_code": customer.get("person_code"),
            "created_at": customer.get("created_at"),
        })
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def write_csv(path: Path, orders: Sequence[dict], customers: Sequence[dict],
              period: tuple[date, date], summary: dict[str, Any]) -> int:
    """Write a UTF-8 **with BOM** CSV so Excel opens Persian text correctly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    order_rows = build_order_rows(orders)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"گزارش فروش — از {format_shamsi(period[0])} تا {format_shamsi(period[1])}"])
        writer.writerow([
            f"تعداد سفارش: {to_persian_digits(summary.get('order_count', 0))}",
            f"مبلغ کل: {format_money(summary.get('total_amount', 0))}",
            f"مشتریان جدید: {to_persian_digits(summary.get('new_customers', 0))}",
        ])
        writer.writerow([])
        writer.writerow(list(_ORDER_HEADERS))
        for row in order_rows:
            writer.writerow([
                to_persian_digits(row["id"]),
                row["customer"],
                to_persian_digits(row["items_count"]),
                to_persian_digits(int(row["total"])),
                row["status_fa"],
                to_persian_digits(row["accounting_order_no"]) if row["accounting_order_no"] else "—",
                format_shamsi(row["created_at"]),
            ])

        writer.writerow([])
        writer.writerow(list(_CUSTOMER_HEADERS))
        for row in build_customer_rows(customers):
            writer.writerow([
                to_persian_digits(row["id"]),
                row["name"],
                row["platform"],
                row["status_fa"],
                to_persian_digits(row["person_code"]) if row["person_code"] else "—",
                format_shamsi(row["created_at"]),
            ])
    return len(order_rows)


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------
def write_xlsx(path: Path, orders: Sequence[dict], customers: Sequence[dict],
               period: tuple[date, date], summary: dict[str, Any]) -> int:
    """Write a right-to-left Excel workbook with two sheets."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    order_rows = build_order_rows(orders)
    customer_rows = build_customer_rows(customers)

    workbook = Workbook()
    header_fill = PatternFill("solid", fgColor="EFF6FF")
    header_font = Font(bold=True, color="1E293B", name="Tahoma", size=11)
    body_font = Font(name="Tahoma", size=11)
    thin = Side(style="thin", color="E2E8F0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    rtl = Alignment(horizontal="right", vertical="center", readingOrder=2)

    def style_sheet(sheet, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        sheet.sheet_view.rightToLeft = True
        sheet.append(list(headers))
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = rtl
            cell.border = border
        for row in rows:
            sheet.append(list(row))
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
                cell.alignment = rtl
                cell.border = border
        for index, header in enumerate(headers, start=1):
            longest = max(
                [len(str(header))] + [len(str(r[index - 1])) for r in rows if len(r) >= index]
                or [10]
            )
            sheet.column_dimensions[get_column_letter(index)].width = min(38, max(12, longest + 4))
        sheet.freeze_panes = "A2"

    # ---- summary sheet ------------------------------------------------
    overview = workbook.active
    overview.title = "خلاصه"
    overview.sheet_view.rightToLeft = True
    overview_rows = [
        ("گزارش فروش", ""),
        ("از تاریخ", format_shamsi(period[0])),
        ("تا تاریخ", format_shamsi(period[1])),
        ("تعداد سفارش", to_persian_digits(summary.get("order_count", 0))),
        ("مبلغ کل", format_money(summary.get("total_amount", 0))),
        ("مشتریان جدید", to_persian_digits(summary.get("new_customers", 0))),
        ("تعداد کل مشتریان", to_persian_digits(summary.get("customer_count", 0))),
    ]
    for label, value in overview_rows:
        overview.append([label, value])
    overview.column_dimensions["A"].width = 22
    overview.column_dimensions["B"].width = 30
    for row in overview.iter_rows():
        for cell in row:
            cell.font = body_font
            cell.alignment = rtl
    for cell in overview["A"]:
        cell.font = header_font

    # ---- orders sheet --------------------------------------------------
    orders_sheet = workbook.create_sheet("سفارش‌ها")
    style_sheet(
        orders_sheet,
        _ORDER_HEADERS,
        [
            [
                to_persian_digits(row["id"]),
                row["customer"],
                to_persian_digits(row["items_count"]),
                to_persian_digits(int(row["total"])),
                row["status_fa"],
                to_persian_digits(row["accounting_order_no"]) if row["accounting_order_no"] else "—",
                format_shamsi(row["created_at"]),
            ]
            for row in order_rows
        ],
    )

    # ---- customers sheet -----------------------------------------------
    customers_sheet = workbook.create_sheet("مشتریان")
    style_sheet(
        customers_sheet,
        _CUSTOMER_HEADERS,
        [
            [
                to_persian_digits(row["id"]),
                row["name"],
                row["platform"],
                row["status_fa"],
                to_persian_digits(row["person_code"]) if row["person_code"] else "—",
                format_shamsi(row["created_at"]),
            ]
            for row in customer_rows
        ],
    )

    workbook.save(path)
    return len(order_rows)


def today_range() -> tuple[date, date]:
    today = date.today()
    return today, today


def shamsi_month_range(reference: datetime | None = None) -> tuple[date, date]:
    """First day of the current Shamsi month through today."""
    moment = reference or datetime.now()
    jy, jm, _jd = gregorian_to_jalali(moment.year, moment.month, moment.day)
    from .persian import jalali_to_gregorian

    first = date(*jalali_to_gregorian(jy, jm, 1))
    return first, moment.date()
