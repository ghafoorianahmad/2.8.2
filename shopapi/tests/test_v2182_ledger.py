"""v2.18.2 «گردش سال‌های قبل»: read-only, its own tick, the national code masked without its tick."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.accounting_reader import AccountingReader
from app.config import Settings
from app.main import create_app
from app.routers.ledger import matches
from app.security import Identity, get_identity

PEOPLE = [
    {"code": 7, "name": "علی كريمي", "national_code": "0012345678", "phones": ["09351112233"]},
    {"code": 8, "name": "سارا احمدی", "national_code": "", "phones": []},
]


class FakeReader:
    def __init__(self):
        self.statement_db = None

    def ledger_databases(self):
        return [{"name": "hesab5 t"}, {"name": "hesab4"}]

    def ledger_persons(self, database):
        assert database == "hesab4"
        return PEOPLE

    def customer_statement(self, code, rows, database=None):
        self.statement_db = database
        return {"rows": [{"id": 1, "date": "1404/01/02", "kind": "f", "doc_no": "9", "debit": 100.0,
                          "credit": 0.0, "description": "x"}],
                "total_debit": 100.0, "total_credit": 0.0}

    def invoice_detail(self, numfact, database=None):
        self.invoice_db = database
        if numfact == 9:
            return {"numfact": 9, "person_code": 7, "date": "1404/01/02", "description": "x",
                    "paid": 0.0,
                    "lines": [{"radif": 1, "code": 5, "name": "کالای نمونهٔ",
                               "qty": 2, "unit_price": 1000, "discount": 0.0, "line_total": 2000.0}],
                    "total": 2000.0}
        return {}


class Who:
    def __init__(self, *ticks):
        self.ticks = set(ticks)
        self.kind = "staff"
        self.must_change_password = False

    def can(self, tick):
        return tick in self.ticks


@pytest.fixture
def make_client():
    def build(*ticks):
        app = create_app()
        reader = FakeReader()
        app.dependency_overrides[deps.get_reader] = lambda: reader
        app.dependency_overrides[deps.get_settings] = lambda: Settings(accounting_database="hesab5 t")
        app.dependency_overrides[get_identity] = lambda: Who(*ticks)
        return TestClient(app), reader
    return build


def test_without_the_tick_nothing(make_client):
    client, _ = make_client()
    for url in ("/admin/ledger/databases", "/admin/ledger/persons?db=hesab4",
                "/admin/ledger/persons/7/statement?db=hesab4"):
        assert client.get(url).status_code == 403


def test_the_databases_say_which_is_current(make_client):
    client, _ = make_client("ledger.view")
    assert client.get("/admin/ledger/databases").json() == [
        {"name": "hesab5 t", "current": True}, {"name": "hesab4", "current": False}]


def test_a_database_not_on_the_servers_list_is_refused(make_client):
    client, _ = make_client("ledger.view")
    for url in ("/admin/ledger/persons?db=hesab5", "/admin/ledger/persons/7/statement?db=x];DROP"):
        assert client.get(url).status_code == 404


def test_the_national_code_is_masked_without_its_tick(make_client):
    client, _ = make_client("ledger.view")
    row = client.get("/admin/ledger/persons?db=hesab4").json()["items"][0]
    assert row["national_code"] == "••••••••78" and row["phone_tail"] == "33"
    client, _ = make_client("ledger.view", "customer_private.view")
    assert client.get("/admin/ledger/persons?db=hesab4").json()["items"][0]["national_code"] == "0012345678"


def test_search_by_name_phone_and_code():
    person = PEOPLE[0]
    for query in ("علی کریمی", "كريمي", "2233", "۰۹۳۵۱۱۱۲۲۳۳"):
        assert matches(person, query, may_see_code=False), query
    assert not matches(person, "رضا", may_see_code=False)
    # without the tick the code cannot be read out digit by digit: only all of it
    assert not matches(person, "00123", may_see_code=False)
    assert matches(person, "0012345678", may_see_code=False)
    assert matches(person, "00123", may_see_code=True)


def test_the_statement_reads_the_chosen_year(make_client):
    client, reader = make_client("ledger.view")
    answer = client.get("/admin/ledger/persons/7/statement?db=hesab4").json()
    assert reader.statement_db == "hesab4" and answer["database"] == "hesab4"
    assert answer["side"] == "debtor" and answer["rows"][0]["debit"] == 100.0


class _Conn:
    def __init__(self, seen):
        self.seen = seen

    def execute(self, sql, *_args):
        self.seen.append(sql)

        class Result:
            description = [("Code",), ("fname",), ("Name",), ("Codemelli",)]

            @staticmethod
            def fetchall():
                return []

            @staticmethod
            def fetchone():
                return (1, 2)
        return Result()

    def close(self):
        pass


def test_only_selects_and_the_working_database_stays_the_default():
    seen = []
    reader = AccountingReader(Settings(accounting_database="hesab5 t"), lambda: _Conn(seen))
    reader.ledger_databases()
    reader.ledger_persons("hesab4")
    reader.customer_statement(7, 10, database="hesab4")
    assert seen and all(sql.lstrip().upper().startswith("SELECT") for sql in seen)
    assert any("[hesab4].dbo.KOL" in sql for sql in seen)
    seen.clear()
    reader.customer_statement(7, 10)
    assert all("[hesab5 t].dbo.KOL" in sql for sql in seen)


def test_the_grant_script_never_gives_a_write():
    script = (Path(__file__).parent.parent / "sql" / "grant_ledger_readonly.sql").read_text("utf-8")
    code = script[script.index("SET NOCOUNT ON"):].upper()
    assert "DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::DBO" in code
    assert "GRANT INSERT" not in code and "GRANT UPDATE" not in code and "GRANT DELETE" not in code
    assert "SP_ADDROLEMEMBER N''SHOP_LEDGER_READ''" in code


def test_invoice_detail_reader_selects_only_invoice_columns():
    seen = []

    class _RowsConn:
        def __init__(self):
            self.seen = seen

        def execute(self, sql, *_args):
            self.seen.append(sql)

            class Result:
                def __init__(self, sql_: str) -> None:
                    self.sql = sql_
                    s = sql_.upper()
                    if "DBO.FACTO" in s:
                        self.description = [("radif",), ("code",), ("qty",), ("unit_price",), ("line_total",)]
                        self._rows = [(1, 5, 2.0, 1000.0, 2000.0)]
                    elif "DBO.KALA" in s:
                        self.description = [("Code",), ("Name",)]
                        self._rows = [(5, "ن")]
                    else:
                        self.description = [("numfact",), ("person_code",), ("date",), ("description",), ("paid",)]
                        self._rows = [(9, 7, "1404/01/02", "d", 0)]

                def fetchall(self):
                    return self._rows

                def fetchone(self):
                    return (1,)

            return Result(sql)

        def close(self):
            pass

    reader = AccountingReader(Settings(accounting_database="hesab5 t"), _RowsConn)
    detail = reader.invoice_detail(9, database="hesab4")
    assert detail == {
        "numfact": 9, "person_code": 7, "date": "1404/01/02", "description": "d",
        "paid": 0.0,
        "lines": [{"radif": 1, "code": 5, "name": "ن", "qty": 2.0, "unit_price": 1000.0,
                   "discount": 0.0, "line_total": 2000.0}],
        "total": 2000.0,
    }
    assert seen and all(sql.lstrip().upper().startswith("SELECT") for sql in seen)
    assert any("[hesab4].dbo.Fact" in sql for sql in seen)
    assert any("[hesab4].dbo.Facto" in sql for sql in seen)
    assert any("[hesab4].dbo.Kala" in sql for sql in seen)
    seen.clear()
    reader.invoice_detail(9)
    assert seen and any("[hesab5 t].dbo.Fact f" in sql for sql in seen)


def test_invoice_detail_endpoint_returns_header_and_lines(make_client):
    client, reader = make_client("ledger.view")
    answer = client.get("/admin/ledger/persons/7/invoice/9/lines?db=hesab4").json()
    assert reader.invoice_db == "hesab4"
    assert answer["person_code"] == 7 and answer["database"] == "hesab4"
    assert answer["numfact"] == 9
    assert answer["lines"][0]["name"] == "کالای نمونهٔ"
    assert answer["lines"][0]["qty"] == 2 and answer["lines"][0]["line_total"] == 2000.0
    assert answer["total"] == 2000.0


def test_invoice_detail_endpoint_needs_the_ledger_tick(make_client):
    client, _ = make_client()
    assert client.get("/admin/ledger/persons/7/invoice/9/lines?db=hesab4").status_code == 403


def test_invoice_detail_endpoint_unknown_database_is_refused(make_client):
    client, _ = make_client("ledger.view")
    assert client.get("/admin/ledger/persons/7/invoice/9/lines?db=hesab5").status_code == 404
    assert client.get("/admin/ledger/persons/7/invoice/9/lines?db=x];DROP").status_code == 404


def test_invoice_detail_endpoint_unknown_invoice_is_404(make_client):
    client, _ = make_client("ledger.view")
    assert client.get("/admin/ledger/persons/7/invoice/0/lines?db=hesab4").status_code == 404


def test_the_detail_grant_script_is_readonly_and_safe_to_run_twice():
    script = (Path(__file__).parent.parent / "sql" / "grant_ledger_detail_readonly.sql").read_text("utf-8")
    code = script[script.index("SET NOCOUNT ON"):].upper()
    for db in ("HESAB1", "HESAB2", "HESAB3", "HESAB4"):
        assert db in code, db
    assert "GRANT SELECT ON DBO.FACT" in code
    assert "GRANT SELECT ON DBO.FACTO" in code
    assert "GRANT SELECT ON DBO.KALA" in code
    assert "DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::DBO" in code
    assert "GRANT INSERT" not in code and "GRANT UPDATE" not in code and "GRANT DELETE" not in code
    assert "CREATE ROLE SHOP_LEDGER_READ" in code
    assert "IF DATABASE_PRINCIPAL_ID(N''SHOP_LEDGER_READ'') IS NULL" in code
    assert "SP_ADDROLEMEMBER N''SHOP_LEDGER_READ''" in code
