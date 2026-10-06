"""Read-only access to the accounting SQL Server database.

Every query is parameterized and SQL Server 2008 R2 compatible (no OFFSET/FETCH,
STRING_AGG, CONCAT, TRY_CONVERT, IIF or THROW). Only column names, counts and
aggregates are used for stock/reservation math. Product tables (Kala, Gkala) are
read for names; name_mo is used only for existence checks (COUNT) and mobile
matching, where the name is masked inside SQL so the raw value never enters this
process.
"""
from __future__ import annotations

from typing import Optional

import pyodbc

from .config import Settings
from .text import normalize_fa
from .util import quote_identifier

# Price levels -> Kala sale-price columns. Geya/Geyk/Geym are NOT sale prices.
PRICE_COLUMNS = {1: "Gey", 2: "Geycf", 3: "gey3", 4: "gey4", 5: "gey5"}
FORBIDDEN_PRICE_COLUMNS = ("Geya", "Geyk", "Geym")

# normalize_fa mappings, mirrored as a SQL REPLACE chain for server-side matching.
_NORMALIZE_PAIRS = [
    ("٠", "0"), ("١", "1"), ("٢", "2"), ("٣", "3"), ("٤", "4"),
    ("٥", "5"), ("٦", "6"), ("٧", "7"), ("٨", "8"), ("٩", "9"),
    ("۰", "0"), ("۱", "1"), ("۲", "2"), ("۳", "3"), ("۴", "4"),
    ("۵", "5"), ("۶", "6"), ("۷", "7"), ("۸", "8"), ("۹", "9"),
    ("ي", "ی"), ("ك", "ک"),
]


def price_column(level: int) -> str:
    try:
        return PRICE_COLUMNS[level]
    except KeyError:
        raise ValueError(f"invalid price level: {level!r}") from None


def compute_available(stock: float, open_reservation: float, our_reservation: float) -> float:
    """available = stock - open_order_reservation - our own pending reservations.

    Clamped at 0: an over-reserved product is reported as out of stock, never as
    a negative quantity.
    """
    available = stock - open_reservation - our_reservation
    return available if available > 0 else 0.0


def _normalize_sql(column: str) -> str:
    expr = column
    for src, dst in _NORMALIZE_PAIRS:
        expr = f"REPLACE({expr}, N'{src}', N'{dst}')"
    return expr


class AccountingReader:
    def __init__(self, settings: Settings, connection_factory=None):
        self.settings = settings
        self._connection_factory = connection_factory or self._default_connect

    def _default_connect(self):
        conn = pyodbc.connect(
            self.settings.accounting_connection_string(),
            timeout=self.settings.accounting_connect_timeout,
        )
        conn.timeout = self.settings.accounting_query_timeout
        return conn

    def connection(self):
        return self._connection_factory()

    def _db(self) -> str:
        return quote_identifier(self.settings.accounting_database)

    @staticmethod
    def _rows(cursor) -> list[dict]:
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    @staticmethod
    def _in_placeholders(values) -> str:
        return ",".join("?" for _ in values)

    # ---- public ----
    def ping(self) -> bool:
        """Cheapest possible proof that the accounting database answers."""
        conn = self.connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return True

    def list_groups(self) -> list[dict]:
        db = self._db()
        conn = self.connection()
        try:
            rows = self._rows(conn.execute(f"SELECT Code, Name FROM {db}.dbo.Gkala ORDER BY Code"))
        finally:
            conn.close()
        return [{"code": r["Code"], "name": r["Name"]} for r in rows]

    def list_products(
        self,
        *,
        q: str | None = None,
        group: int | None = None,
        in_stock: bool = True,
        page: int = 1,
        page_size: int = 20,
        level: int = 3,
        our_reservations: dict[int, float] | None = None,
    ) -> dict:
        col = price_column(level)
        our_res = our_reservations or {}
        conn = self.connection()
        try:
            db = self._db()
            products = self._rows(
                conn.execute(
                    f"SELECT Code, Name, Gcod, {col} AS unit_price, pic "
                    f"FROM {db}.dbo.Kala WHERE active = 1 AND {col} > 0 ORDER BY Code"
                )
            )
            codes = [p["Code"] for p in products]
            stock = self._stock(conn, codes) if codes else {}
            open_res = self._open_reservation(conn, codes) if codes else {}
        finally:
            conn.close()

        items: list[dict] = []
        for p in products:
            if group is not None and p["Gcod"] != group:
                continue
            if q and normalize_fa(q) not in normalize_fa(p["Name"] or ""):
                continue
            code = p["Code"]
            avail = compute_available(
                stock.get(code, 0.0), open_res.get(code, 0.0), our_res.get(code, 0.0)
            )
            if in_stock and avail <= 0:
                continue
            items.append(
                {
                    "code": code,
                    "name": p["Name"],
                    "group": p["Gcod"],
                    "unit_price": float(p["unit_price"]),
                    "available_qty": avail,
                    "image": p["pic"] if p["pic"] is not None else None,
                }
            )

        total = len(items)
        start = (page - 1) * page_size
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items[start : start + page_size],
        }

    def get_products_for_order(
        self,
        codes: list[int],
        level: int,
        our_reservations: dict[int, float] | None = None,
    ) -> dict[int, dict]:
        codes = list(dict.fromkeys(codes))
        if not codes:
            return {}
        col = price_column(level)
        our_res = our_reservations or {}
        conn = self.connection()
        try:
            db = self._db()
            ph = self._in_placeholders(codes)
            products = self._rows(
                conn.execute(
                    f"SELECT Code, Name, Gcod, {col} AS unit_price, pic "
                    f"FROM {db}.dbo.Kala WHERE active = 1 AND Code IN ({ph})",
                    codes,
                )
            )
            stock = self._stock(conn, codes)
            open_res = self._open_reservation(conn, codes)
        finally:
            conn.close()

        out: dict[int, dict] = {}
        for p in products:
            code = p["Code"]
            avail = compute_available(
                stock.get(code, 0.0), open_res.get(code, 0.0), our_res.get(code, 0.0)
            )
            out[code] = {
                "code": code,
                "name": p["Name"],
                "group": p["Gcod"],
                "unit_price": float(p["unit_price"]) if p["unit_price"] is not None else None,
                "available_qty": avail,
                "image": p["pic"] if p["pic"] is not None else None,
            }
        return out

    def person_code_exists(self, code: int) -> bool:
        db = self._db()
        conn = self.connection()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {db}.dbo.name_mo WHERE Code = ?", code
            ).fetchone()
            return int(row[0]) > 0
        finally:
            conn.close()

    def find_person_by_mobile(self, mobile: str) -> Optional[dict]:
        """Return only the person code and a masked name, matched by exact
        normalized mobile number. The name is masked inside SQL."""
        db = self._db()
        conn = self.connection()
        try:
            normalized = _normalize_sql("mobile")
            sql = (
                f"SELECT TOP 1 Code, "
                f"CASE WHEN LEN(Name) <= 1 THEN Name ELSE LEFT(Name,1) + "
                f"REPLICATE('*', LEN(Name)-1) END AS masked_name "
                f"FROM {db}.dbo.name_mo WHERE {normalized} = ? ORDER BY Code"
            )
            row = conn.execute(sql, normalize_fa(mobile)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {"code": int(row[0]), "masked_name": row[1]}

    # ---- internals ----
    def _stock(self, conn, codes: list[int]) -> dict[int, float]:
        db = self._db()
        sql = (
            f"SELECT Codekala, SUM(ISNULL(Megv,0)) - SUM(ISNULL(Megs,0)) AS stock "
            f"FROM {db}.dbo.kardex_an WHERE Codekala IN ({self._in_placeholders(codes)})"
        )
        params: list = list(codes)
        if self.settings.stock_warehouses:
            sql += f" AND Codanbar IN ({self._in_placeholders(self.settings.stock_warehouses)})"
            params += list(self.settings.stock_warehouses)
        sql += " GROUP BY Codekala"
        rows = self._rows(conn.execute(sql, params))
        return {r["Codekala"]: float(r["stock"]) for r in rows}

    def _open_reservation(self, conn, codes: list[int]) -> dict[int, float]:
        db = self._db()
        ph = self._in_placeholders(codes)
        ordered = self._rows(
            conn.execute(
                f"SELECT Codekala, SUM(ISNULL(Meg,0)) AS ordered "
                f"FROM {db}.dbo.KalaOrderDetail WHERE Codekala IN ({ph}) GROUP BY Codekala",
                codes,
            )
        )
        fulfilled = self._rows(
            conn.execute(
                f"SELECT Codekala, SUM(ISNULL(Meg,0)) AS fulfilled "
                f"FROM {db}.dbo.facto WHERE Codekala IN ({ph}) "
                f"AND ISNULL(ordercode,0) > 0 GROUP BY Codekala",
                codes,
            )
        )
        ordered_map = {r["Codekala"]: float(r["ordered"]) for r in ordered}
        fulfilled_map = {r["Codekala"]: float(r["fulfilled"]) for r in fulfilled}
        out: dict[int, float] = {}
        for code in codes:
            open_qty = ordered_map.get(code, 0.0) - fulfilled_map.get(code, 0.0)
            out[code] = open_qty if open_qty > 0 else 0.0
        return out
