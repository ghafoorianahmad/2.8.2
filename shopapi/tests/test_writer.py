"""Accounting writer unit tests with a fake connection (no real SQL)."""
import pyodbc
import pytest

from app.accounting_writer import (
    DETAIL_COLUMNS,
    HEADER_COLUMNS,
    AccountingWriter,
    insert_statement,
)
from app.config import Settings


class FakeConn:
    def __init__(self, idempotent_codlp=0, max_codlp=5, verify_count=1,
                 datelp="1405/07/13"):
        self.autocommit = False
        self.executed = []  # list of (sql, params_tuple)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.idempotent_codlp = idempotent_codlp
        self.max_codlp = max_codlp
        self.verify_count = verify_count
        self.datelp = datelp

    def execute(self, sql, *params):
        self.executed.append((sql, tuple(params)))
        return self

    def fetchone(self):
        sql, _ = self.executed[-1]
        s = sql.upper()
        if "SHARHLP" in s:
            return (self.idempotent_codlp,)
        if "MILADITOSHAMSI" in s:
            return (self.datelp,)
        if "UPDLOCK" in s:
            return (self.max_codlp + 1,)
        if "COUNT(*)" in s:
            return (self.verify_count,)
        return (None,)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FlakyLockConn(FakeConn):
    """Raises a lock-timeout on the first idempotency check, then recovers."""

    def __init__(self):
        super().__init__(max_codlp=5)
        self.sharhlp_seen = 0

    def execute(self, sql, *params):
        # Only the idempotency SELECT mentions Sharhlp in a WHERE; the header
        # INSERT also names the Sharhlp column, so require SELECT to disambiguate.
        if "SHARHLP" in sql.upper() and "SELECT" in sql.upper():
            self.sharhlp_seen += 1
            if self.sharhlp_seen == 1:
                raise pyodbc.Error("1222 Lock request time out period exceeded")
        return super().execute(sql, *params)


def _writer(max_codlp=5, verify_count=1, idempotent_codlp=0):
    conn = FakeConn(max_codlp=max_codlp, verify_count=verify_count,
                    idempotent_codlp=idempotent_codlp)
    settings = Settings(accounting_database="hesab5", accounting_write_enabled=False)
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    return writer, conn


def test_dry_run_rolls_back_and_returns_values():
    writer, conn = _writer(max_codlp=5)
    res = writer.write_order(1, 7001, [(101, 2.0, 100.0), (102, 1.0, 50.0)])
    assert res.accounting_order_no == 6
    assert res.person_code == 7001
    assert res.mablp == 250.0
    assert res.datelp == "1405/07/13"
    assert res.rolled_back is True
    assert res.committed is False
    assert conn.rolled_back is True
    assert conn.committed is False


def test_empty_string_rule_for_sharh_fields_and_tavasot():
    writer, conn = _writer()
    writer.write_order(1, 7001, [(101, 1.0, 100.0)])

    inserts = [(sql, params) for sql, params in conn.executed
               if sql.strip().upper().startswith("INSERT")]
    assert len(inserts) == 2

    header_sql, header_params = next(
        (s, p) for s, p in inserts if "KalaOrderDetail" not in s
    )
    detail_sql, detail_params = next(
        (s, p) for s, p in inserts if "KalaOrderDetail" in s
    )

    # header params order: Codlp, Codnlp, Datelp, Mablp, Sharhlp, Codf, takhfif,
    #                     tavasot, avarez, va, Taf2, Status, PrintCount, usercode,
    #                     Naghd, Ischeck
    assert header_params[5] == -100            # Codf
    assert header_params[7] == ""              # tavasot (empty string, not None)
    assert header_params[11] == 6808           # Status
    assert header_params[13] == 1              # usercode
    assert header_params[0] == 6               # Codlp
    assert header_params[1] == 7001            # Codnlp (person code)

    # detail params: Num, Codlp_, Codekala, Meg, Gey, sharh, AnbarCode,
    #                PrintCount, takhfif, field1..field8
    assert detail_params[5] == ""              # sharh
    for idx in range(9, 17):
        assert detail_params[idx] == ""        # field1..field8 (empty strings)


def test_idempotent_write_returns_existing_codlp():
    writer, conn = _writer(idempotent_codlp=77)
    res = writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert res.idempotent is True
    assert res.accounting_order_no == 77
    assert not any(sql.strip().upper().startswith("INSERT") for sql, _ in conn.executed)
    assert conn.rolled_back is True


def test_duplicate_codlp_rolls_back():
    writer, conn = _writer(verify_count=0)
    with pytest.raises(RuntimeError):
        writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert conn.rolled_back is True
    assert conn.committed is False


def test_lock_timeout_retries_once():
    conn = FlakyLockConn()
    settings = Settings(accounting_database="hesab5", accounting_write_enabled=False)
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    res = writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert res.accounting_order_no == 6
    assert conn.sharhlp_seen == 2  # idempotency check ran twice (retried once)


def test_column_lists_match_the_accounting_schema():
    assert len(HEADER_COLUMNS) == 16
    assert len(DETAIL_COLUMNS) == 17
    assert HEADER_COLUMNS[5] == "Codf"
    assert HEADER_COLUMNS[7] == "tavasot"
    assert HEADER_COLUMNS[11] == "Status"
    assert DETAIL_COLUMNS[5] == "sharh"
    assert DETAIL_COLUMNS[9:17] == (
        "field1", "field2", "field3", "field4", "field5", "field6", "field7", "field8",
    )


def test_insert_statement_rejects_a_column_value_mismatch():
    with pytest.raises(ValueError):
        insert_statement("[db].dbo.KalaOrderDetail", ("A", "B"), ("only-one",))


def test_insert_statements_have_matching_columns_placeholders_and_params():
    """A fake connection never parses SQL, so verify the arithmetic explicitly.

    This is the regression test for the off-by-one that made every real write
    fail with "The SQL contains 18 parameter markers, but 17 parameters were
    supplied" (only the real-database integration run caught it).
    """
    writer, conn = _writer()
    writer.write_order(7, 7001, [(101, 2.0, 100.0), (102, 1.0, 50.0)])

    inserts = [(sql, params) for sql, params in conn.executed
               if sql.strip().upper().startswith("INSERT")]
    assert len(inserts) == 3  # 1 header + 2 detail rows

    for sql, params in inserts:
        body = sql[sql.index("(") + 1:]
        columns_part, _, rest = body.partition(")")
        columns = [c.strip() for c in columns_part.split(",") if c.strip()]
        values_part = rest[rest.upper().index("VALUES") + len("VALUES"):]
        placeholders = values_part.count("?")
        assert len(columns) == placeholders, sql
        assert len(columns) == len(params), sql
