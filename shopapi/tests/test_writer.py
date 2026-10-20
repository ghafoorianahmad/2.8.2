"""Accounting writer unit tests with a fake connection (no real SQL)."""
import pyodbc
import pytest

from app.accounting_writer import (
    AccountingLockTimeout,
    DETAIL_COLUMNS,
    HEADER_COLUMNS,
    AccountingWriter,
    insert_statement,
)
from app.config import Settings


class FakeConn:
    def __init__(self, idempotent_codlp=0, max_codlp=5, verify_count=1,
                 datelp="1405/07/13", lock_result=0, existing_persons=(),
                 max_person=41, taf_code=900):
        self.autocommit = False
        self.executed = []  # list of (sql, params_tuple)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.idempotent_codlp = idempotent_codlp
        self.max_codlp = max_codlp
        self.verify_count = verify_count
        self.datelp = datelp
        self.lock_result = lock_result
        self.existing_persons = list(existing_persons)
        self.max_person = max_person
        self.taf_code = taf_code

    def execute(self, sql, *params):
        self.executed.append((sql, tuple(params)))
        return self

    def fetchone(self):
        sql, _ = self.executed[-1]
        s = sql.upper()
        if "SP_GETAPPLOCK" in s:
            return (self.lock_result,)
        if "SHARHLP" in s:
            return (self.idempotent_codlp,)
        if "MILADITOSHAMSI" in s:
            return (self.datelp,)
        if "MAX(CODLP),0)+1" in s:
            return (self.max_codlp + 1,)
        if "MAX(CODE),0)+1" in s:
            return (self.max_person + 1,)
        if "DBO.TAF WHERE" in s:
            return (self.taf_code,)
        if "COUNT(*)" in s:
            return (self.verify_count,)
        return (None,)

    def fetchall(self):
        sql, _ = self.executed[-1]
        if "DETAILTBL" in sql.upper():
            return [(c,) for c in self.existing_persons]
        return []

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
    """A dry-run writer (production database, writes off)."""
    conn = FakeConn(max_codlp=max_codlp, verify_count=verify_count,
                    idempotent_codlp=idempotent_codlp)
    settings = Settings(accounting_database="hesab5", accounting_write_enabled=False)
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    return writer, conn


def _committing_writer(max_codlp=5, verify_count=1, idempotent_codlp=0, status=0):
    """A writer on the allowlisted test copy with a configured Status."""
    conn = FakeConn(max_codlp=max_codlp, verify_count=verify_count,
                    idempotent_codlp=idempotent_codlp)
    settings = Settings(accounting_database="hesab5 t", accounting_allowed_databases=("hesab5 t",), accounting_write_databases=("hesab5 t",), accounting_status_code=status)
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    return writer, conn


def _writes(conn):
    return [sql for sql, _ in conn.executed
            if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]


def test_dry_run_rolls_back_and_returns_values():
    writer, conn = _writer(max_codlp=5)
    res = writer.write_order(1, 7001, [(101, 2.0, 100.0), (102, 1.0, 50.0)])
    assert res.accounting_order_no == 6
    assert res.person_code == 7001
    assert res.mablp == 250.0
    assert res.status_code is None          # not configured: never guessed
    assert res.datelp == "1405/07/13"
    assert res.rolled_back is True
    assert res.committed is False
    assert res.database == "hesab5"
    assert conn.rolled_back is True
    assert conn.committed is False
    assert _writes(conn) == []              # a dry run never INSERTs


def test_empty_string_rule_for_sharh_fields_and_tavasot():
    writer, conn = _committing_writer()
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
    #                     tavasot, avarez, va, Status, PrintCount, usercode,
    #                     Naghd, Ischeck, keraye
    assert header_params[5] == -100            # Codf
    assert header_params[7] == ""              # tavasot (empty string, not None)
    assert header_params[9] == 0               # va (sales order)
    assert header_params[10] == 0              # Status = ACCOUNTING_STATUS_CODE (configured)
    assert header_params[12] == 1              # usercode
    assert "Taf2" not in header_sql
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
    writer, conn = _committing_writer(verify_count=0)
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
    assert HEADER_COLUMNS[10] == "Status"
    assert "Taf2" not in HEADER_COLUMNS
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
    writer, conn = _committing_writer()
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


# ---- sp_getapplock (reference §5.0) ----------------------------------------

def _sql_index(conn, needle):
    return next(i for i, (sql, _) in enumerate(conn.executed) if needle in sql.upper())


def test_order_lock_is_an_applock_taken_before_the_idempotency_check():
    writer, conn = _writer()
    writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    lock = _sql_index(conn, "SP_GETAPPLOCK")
    assert conn.executed[lock][1] == ("shop:KalaOrder",)
    assert "@LockOwner='Transaction'" in conn.executed[lock][0]
    assert lock < _sql_index(conn, "WHERE SHARHLP")
    assert lock < _sql_index(conn, "MAX(CODLP),0)+1")
    assert not any("UPDLOCK" in sql.upper() or "HOLDLOCK" in sql.upper()
                   for sql, _ in conn.executed)


def test_applock_timeout_rolls_back_without_inserting():
    conn = FakeConn(lock_result=-1)
    writer = AccountingWriter(Settings(accounting_database="hesab5"),
                              connection_factory=lambda: conn)
    with pytest.raises(AccountingLockTimeout):
        writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert conn.rolled_back and not conn.committed and conn.closed
    assert not any(sql.strip().upper().startswith("INSERT") for sql, _ in conn.executed)


def test_mablp_is_not_rounded():
    writer, _ = _writer()
    res = writer.write_order(1, 7001, [(101, 0.5, 101.0), (102, 1.0, 0.3)])
    assert res.mablp == pytest.approx(50.8)


# ---- person creation (reference §5.1 + no duplicate phones) ----------------

def _person_writer(**kw):
    conn = FakeConn(**kw)
    writer = AccountingWriter(Settings(accounting_database="hesab5"),
                              connection_factory=lambda: conn)
    return writer, conn


def test_create_person_links_to_existing_mobile_instead_of_duplicating():
    writer, conn = _person_writer(existing_persons=[812])
    res = writer.create_person("علی", "رضایی", "+98 912 123 4567")
    assert res.existing is True and res.person_code == 812 and not res.ambiguous
    assert not any(sql.strip().upper().startswith(("INSERT", "UPDATE"))
                   for sql, _ in conn.executed)
    lock = _sql_index(conn, "SP_GETAPPLOCK")
    lookup = _sql_index(conn, "DETAILTBL")
    assert conn.executed[lock][1] == ("shop:name_mo",)
    assert lock < lookup
    sql, params = conn.executed[lookup]
    assert params == ("9121234567",)
    assert "TabaghehBandiID IN (1, 3)" in sql
    assert conn.rolled_back and not conn.committed


def test_create_person_reports_a_shared_mobile_as_ambiguous():
    writer, _ = _person_writer(existing_persons=[812, 990])
    res = writer.create_person("", "رضایی", "09121234567")
    assert res.existing and res.ambiguous and res.person_code == 812


def test_create_person_dry_run_reports_the_code_without_writing():
    writer, conn = _person_writer(max_person=41)
    res = writer.create_person("علی", "رضایی", "09121234567")
    assert res.existing is False and res.person_code == 42 and res.taf_code is None
    assert res.rolled_back and not res.committed and conn.rolled_back
    assert _writes(conn) == []


def test_create_person_new_mobile_follows_recipe():
    conn = FakeConn(max_person=41, taf_code=900)
    writer = AccountingWriter(
        Settings(accounting_database="hesab5", accounting_test_databases=("hesab5",)),
        connection_factory=lambda: conn)
    res = writer.create_person("علی", "رضایی", "۰۹۱۲۱۲۳۴۵۶۷", address="مشهد")
    assert res.existing is False and res.person_code == 42 and res.taf_code == 900
    assert res.committed and conn.committed

    writes = [(sql, p) for sql, p in conn.executed
              if sql.strip().upper().startswith(("INSERT", "UPDATE"))]
    tables = [sql.split()[2 if sql.upper().startswith("INSERT") else 1].split(".")[-1]
              for sql, _ in writes]
    assert tables == ["name_mo", "taf", "name_mo", "DetailTBL"]

    name_sql, name_params = writes[0]
    columns = [c.strip() for c in name_sql[name_sql.index("(") + 1:name_sql.index(")")].split(",")]
    row = dict(zip(columns, name_params))
    assert len(columns) == len(name_params) == name_sql.count("?")
    assert row["Code"] == 42 and row["Gcod"] == 4
    assert row["telephons"] == "09121234567"
    assert row["Addres2"] == "مشهد"
    assert "mobile" not in columns and "Tel1" not in columns
    assert row["Codemelli"] == "" and row["end_salary_work"] == ""   # '' not NULL

    assert writes[1][1] == (42, 13, 1, 59, "علی رضایی")               # taf
    assert writes[2][1] == (900, 42)                                   # codetaf
    assert writes[3][1] == (42, 3, "09121234567", 0, 1)                # DetailTBL mobile


def test_create_person_commits_only_when_asked_and_allowed():
    from app.accounting_writer import AccountingWriteRefused

    writer, conn = _person_writer()          # production DB, writes off
    with pytest.raises(AccountingWriteRefused):
        writer.create_person("علی", "رضایی", "09121234567", dry_run=False)
    assert conn.executed == [] and not conn.committed

    conn = FakeConn()
    writer = AccountingWriter(
        Settings(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                 accounting_write_enabled=True, accounting_allowed_databases=("hesab5",)),
        connection_factory=lambda: conn)
    res = writer.create_person("علی", "رضایی", "09121234567", dry_run=False)
    assert res.committed and conn.committed


@pytest.mark.parametrize("bad", ["", "12345", "02112345678", "abc"])
def test_create_person_rejects_non_mobile_numbers(bad):
    writer, conn = _person_writer()
    with pytest.raises(ValueError):
        writer.create_person("a", "b", bad)
    assert conn.executed == []
