"""Phase-1 fixes in the reader: R4 mobile matching and R2 open-order reservation.

No real SQL: a scripted connection returns rows per statement and records the
SQL so the recipe's filters can be pinned.
"""
from __future__ import annotations

import pytest

from app.accounting_reader import AccountingReader
from app.config import Settings
from app.text import mobile_key


class ScriptedCursor:
    def __init__(self, rows, columns):
        self._rows = rows
        self.description = [(c,) for c in columns]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class ScriptedConn:
    """Answers each statement with the first scripted (needle, rows, columns) match."""

    def __init__(self, script):
        self.script = script
        self.sql: list[tuple[str, tuple]] = []

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        for needle, rows, columns in self.script:
            if needle in sql:
                return ScriptedCursor(rows, columns)
        return ScriptedCursor([], [])

    def close(self):
        pass


def _reader(script):
    conn = ScriptedConn(script)
    return AccountingReader(Settings(accounting_database="hesab5 t"),
                            connection_factory=lambda: conn), conn


@pytest.mark.parametrize("raw", [
    "09121234567", "9121234567", "+989121234567", "00989121234567", "989121234567",
    "0912 123 4567", "0912-123-4567", "۰۹۱۲۱۲۳۴۵۶۷", "٠٩١٢١٢٣٤٥٦٧",
])
def test_mobile_key_is_the_last_ten_ascii_digits(raw):
    assert mobile_key(raw) == "9121234567"


@pytest.mark.parametrize("raw", [None, "", "12345", "02112345678", "8121234567",
                                 "1234509121234567", "abc"])
def test_mobile_key_rejects_non_mobiles(raw):
    assert mobile_key(raw) is None


def test_find_person_uses_detailtbl_recipe_r4_not_name_mo_mobile():
    reader, conn = _reader([("DetailTBL", [(812,)], ["Code"])])
    assert reader.find_person_by_mobile("+98 912 123 4567") == {"code": 812, "masked_name": None}
    sql, params = conn.sql[-1]
    assert params == ("9121234567",)
    assert "[hesab5 t].dbo.DetailTBL" in sql
    assert "TabaghehBandiID IN (1, 3)" in sql
    assert "d.Va = 0" in sql
    assert "RIGHT(RTRIM(d.Comment), 10) = ?" in sql
    # never the empty name_mo.mobile column, never a name
    assert "mobile" not in sql.lower() and "n.Name" not in sql


def test_find_person_shared_number_needs_manual_approval():
    reader, _ = _reader([("DetailTBL", [(812,), (990,)], ["Code"])])
    assert reader.find_person_by_mobile("09121234567") is None


def test_find_person_without_match_or_with_bad_input():
    reader, conn = _reader([])
    assert reader.find_person_by_mobile("09121234567") is None
    assert reader.find_person_by_mobile("not a phone") is None
    assert len(conn.sql) == 1  # the bad input never reached SQL


def test_open_reservation_follows_recipe_r2():
    reader, conn = _reader([("KalaOrderDetail", [(101, 3.0)], ["Codekala", "open_qty"])])
    assert reader._open_reservation(conn, [101, 102]) == {101: 3.0, 102: 0.0}
    sql, params = conn.sql[-1]
    assert params == ([101, 102],)
    assert "ISNULL(h.va,0) = 0" in sql                     # only sales orders
    assert "f.orderdetailcode = d.Num" in sql              # per order line
    assert "f.ordercode = d.Codlp_" in sql
    assert "ISNULL(ordercode,0) > 0" in sql
    assert "THEN ISNULL(d.Meg,0) - ISNULL(f.Meg,0) ELSE 0 END" in sql  # clamped per line


def test_groups_skip_the_root_group():
    reader, conn = _reader([("Gkala", [(1, "x")], ["Code", "Name"])])
    reader.list_groups()
    assert "WHERE Code > 0" in conn.sql[-1][0]


def test_status_code_has_no_default(monkeypatch):
    """Never guessed: 6808 does not exist and the real value comes from GUI test G2."""
    monkeypatch.delenv("ACCOUNTING_STATUS_CODE", raising=False)
    assert Settings().accounting_status_code is None
    assert Settings.from_env().accounting_status_code is None


def test_invoice_numbers_sql_is_parameterized_facto_numfact_by_ordercode():
    reader, conn = _reader([("f.Numfact", [(41, "2672"), (41, "2680"), (42, "2675")], ["ordercode", "Numfact"])])
    assert reader.invoice_numbers([41, 42]) == {41: ["2672", "2680"], 42: ["2675"]}
    sql, params = conn.sql[0]
    assert "facto" in sql and "f.ordercode IN (?,?)" in sql and "DISTINCT" in sql
    assert "41" not in sql and params == ([41, 42],)       # values travel as parameters only
    assert "OFFSET" not in sql.upper() and "STRING_AGG" not in sql.upper()   # SQL Server 2008 R2
    assert reader.invoice_numbers([]) == {}
