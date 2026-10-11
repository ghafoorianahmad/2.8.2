"""Read-only access to the accounting SQL Server database.

Every query is parameterized and SQL Server 2008 R2 compatible (no OFFSET/FETCH,
STRING_AGG, CONCAT, TRY_CONVERT, IIF or THROW). Only column names, counts and
aggregates are used for stock/reservation math. Product tables (Kala, Gkala) are
read for names; name_mo/DetailTBL are used only for existence checks (COUNT) and
mobile matching (recipe R4), which return person codes only - never names.
"""
from __future__ import annotations

from typing import Optional

import pyodbc

from .config import Settings
from .text import mobile_key, normalize_fa
from .util import quote_identifier

# Price levels -> Kala sale-price columns. Geya/Geyk/Geym are NOT sale prices.
PRICE_COLUMNS = {1: "Gey", 2: "Geycf", 3: "gey3", 4: "gey4", 5: "gey5"}
FORBIDDEN_PRICE_COLUMNS = ("Geya", "Geyk", "Geym")


def person_codes_by_mobile_sql(db: str) -> str:
    """Recipe R4: person codes whose mobile (DetailTBL types 1 and 3) ends in the
    given 10 digits. TOP 2 so a caller can tell a unique match from a shared
    number. ``name_mo.mobile``/``Tel1`` are empty in the real data - never use them.
    """
    return (
        f"SELECT TOP 2 n.Code FROM {db}.dbo.DetailTBL d "
        f"JOIN {db}.dbo.name_mo n ON n.Code = d.IDMaster "
        f"WHERE d.Va = 0 AND d.TabaghehBandiID IN (1, 3) "
        f"AND LEN(RTRIM(d.Comment)) BETWEEN 10 AND 14 "
        f"AND RIGHT(RTRIM(d.Comment), 10) = ? "
        f"GROUP BY n.Code ORDER BY n.Code"
    )


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
            rows = self._rows(conn.execute(f"SELECT Code, Name FROM {db}.dbo.Gkala WHERE Code > 0 ORDER BY Code"))
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
        include_codes: set[int] | None = None,
    ) -> dict:
        """``include_codes``: products priced from the distributor list; they are
        returned without the price/stock filters (the API prices them)."""
        col = price_column(level)
        our_res = our_reservations or {}
        extra = sorted(int(c) for c in (include_codes or ()))[:1000]
        conn = self.connection()
        try:
            db = self._db()
            where = f"{col} > 0"
            if extra:
                where = f"({col} > 0 OR Code IN ({self._in_placeholders(extra)}))"
            products = self._rows(
                conn.execute(
                    f"SELECT Code, Name, Gcod, {col} AS unit_price, pic "
                    f"FROM {db}.dbo.Kala WHERE active = 1 AND {where} ORDER BY Code",
                    *([extra] if extra else []),
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
            if in_stock and avail <= 0 and code not in extra:
                continue
            items.append(
                {
                    "code": code,
                    "name": p["Name"],
                    "group": p["Gcod"],
                    "unit_price": float(p["unit_price"] or 0),
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
        """The single person whose mobile matches (recipe R4), as ``{"code": …}``.

        Returns None when the input is not a mobile number, nothing matches, or
        the number is shared by more than one person (manual approval decides).
        Only the code is read; names are not readable by the least-privilege user.
        """
        key = mobile_key(mobile)
        if key is None:
            return None
        codes = self.person_codes_by_mobile(key)
        if len(codes) != 1:
            return None
        return {"code": codes[0], "masked_name": None}

    def person_codes_by_mobile(self, key: str) -> list[int]:
        """Up to two person codes for a 10-digit mobile key (see mobile_key)."""
        conn = self.connection()
        try:
            rows = conn.execute(person_codes_by_mobile_sql(self._db()), key).fetchall()
        finally:
            conn.close()
        return [int(r[0]) for r in rows]

    def invoice_progress(self, codlps: list[int]) -> dict[int, dict]:
        """Recipe R5 for our written orders: {Codlp: {"ordered", "invoiced"}}.

        An order missing from the result no longer exists in accounting (the
        software deletes an order to cancel it).
        """
        codlps = [int(c) for c in codlps]
        if not codlps:
            return {}
        db = self._db()
        conn = self.connection()
        try:
            rows = self._rows(
                conn.execute(
                    f"SELECT h.Codlp, "
                    f"(SELECT SUM(d.Meg) FROM {db}.dbo.KalaOrderDetail d "
                    f"WHERE d.Codlp_ = h.Codlp) AS OrderedQty, "
                    f"(SELECT SUM(f.Meg) FROM {db}.dbo.facto f "
                    f"WHERE f.ordercode = h.Codlp) AS InvoicedQty "
                    f"FROM {db}.dbo.KalaOrder h "
                    f"WHERE h.Codlp IN ({self._in_placeholders(codlps)})",
                    codlps,
                )
            )
        finally:
            conn.close()
        return {
            int(r["Codlp"]): {
                "ordered": float(r["OrderedQty"] or 0),
                "invoiced": float(r["InvoicedQty"] or 0),
            }
            for r in rows
        }

    def customer_statement(self, person_code: int, max_rows: int = 2000) -> dict:
        """A customer's ledger rows (KOL, reference §3), oldest first.

        Same filter as the verified balance formula. Only the newest
        ``max_rows`` rows are read; the caller's running balance then starts
        from the balance carried over from the older rows (``opening``).
        """
        db = self._db()
        where = (
            f"FROM {db}.dbo.KOL WHERE Noa = 'm' AND Codkol = ? "
            f"AND NOT (Va = N'غ' AND Cod_n IN (-1003, -1005))"
        )
        conn = self.connection()
        try:
            rows = self._rows(
                conn.execute(
                    f"SELECT TOP {int(max_rows)} Num_kol, Date1, Va, N_sanad, Bed, Bes, Sharh "
                    f"{where} ORDER BY Date1 DESC, Num_kol DESC",
                    person_code,
                )
            )
            totals = conn.execute(
                f"SELECT SUM(ISNULL(Bed,0)) AS bed, SUM(ISNULL(Bes,0)) AS bes {where}",
                person_code,
            ).fetchone()
        finally:
            conn.close()
        rows.reverse()
        return {
            "rows": [
                {
                    "id": int(r["Num_kol"]),
                    "date": str(r["Date1"] or "").strip(),
                    "kind": str(r["Va"] or "").strip(),
                    "doc_no": str(r["N_sanad"] or "").strip(),
                    "debit": float(r["Bed"] or 0),
                    "credit": float(r["Bes"] or 0),
                    "description": str(r["Sharh"] or "").strip(),
                }
                for r in rows
            ],
            "total_debit": float(totals[0] or 0) if totals else 0.0,
            "total_credit": float(totals[1] or 0) if totals else 0.0,
        }

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
        """Open (not yet invoiced) quantity of open sales orders, recipe R2.

        Per order line: ordered - invoiced (facto matched on ordercode +
        orderdetailcode + Codekala), clamped at 0, only for headers with va=0.
        Deleted (cancelled) orders simply have no rows any more.
        """
        db = self._db()
        ph = self._in_placeholders(codes)
        rows = self._rows(
            conn.execute(
                f"SELECT d.Codekala, "
                f"SUM(CASE WHEN ISNULL(d.Meg,0) - ISNULL(f.Meg,0) > 0 "
                f"THEN ISNULL(d.Meg,0) - ISNULL(f.Meg,0) ELSE 0 END) AS open_qty "
                f"FROM {db}.dbo.KalaOrderDetail d "
                f"JOIN {db}.dbo.KalaOrder h ON h.Codlp = d.Codlp_ AND ISNULL(h.va,0) = 0 "
                f"LEFT JOIN (SELECT ordercode, orderdetailcode, Codekala, SUM(Meg) AS Meg "
                f"FROM {db}.dbo.facto WHERE ISNULL(ordercode,0) > 0 "
                f"GROUP BY ordercode, orderdetailcode, Codekala) f "
                f"ON f.ordercode = d.Codlp_ AND f.orderdetailcode = d.Num "
                f"AND f.Codekala = d.Codekala "
                f"WHERE d.Codekala IN ({ph}) GROUP BY d.Codekala",
                codes,
            )
        )
        open_map = {r["Codekala"]: float(r["open_qty"] or 0) for r in rows}
        return {code: max(open_map.get(code, 0.0), 0.0) for code in codes}
