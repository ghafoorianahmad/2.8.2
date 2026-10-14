"""Database names may contain spaces: they must be bracketed everywhere.

The dev accounting copy is named "hesab5 t", so `[hesab5 t].dbo.Kala` is the
only valid way to reference it. These tests pin that behaviour for the reader,
the writer, the person lookup and the ODBC connection string.
"""
from __future__ import annotations

import pytest

from app.accounting_reader import AccountingReader
from app.accounting_writer import AccountingWriter
from app.config import Settings
from app.util import quote_identifier

from .test_writer import FakeConn


class RecordingCursor:
    def __init__(self, rows=None, description=None):
        self._rows = rows or []
        self.description = description or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class RecordingConn:
    """Records every SQL statement the reader builds."""

    def __init__(self):
        self.sql: list[tuple[str, tuple]] = []

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        return RecordingCursor()

    def close(self):
        pass


def test_quote_identifier_handles_spaces_and_brackets():
    assert quote_identifier("hesab5 t") == "[hesab5 t]"
    assert quote_identifier("hesab5") == "[hesab5]"
    assert quote_identifier("a]b") == "[a]]b]"


@pytest.mark.parametrize("bad", [None, "", "   ", "x" * 129, "bad\x00name", "line\nbreak"])
def test_quote_identifier_rejects_unsafe_names(bad):
    with pytest.raises(ValueError):
        quote_identifier(bad)


def test_connection_string_keeps_a_spaced_database_name():
    assert "DATABASE=hesab5 t;" in Settings(accounting_database="hesab5 t").accounting_connection_string()
    # ODBC requires braces when the value itself contains a semicolon
    assert "DATABASE={we;ird}" in Settings(accounting_database="we;ird").accounting_connection_string()


def test_reader_brackets_the_database_name():
    conn = RecordingConn()
    reader = AccountingReader(
        Settings(accounting_database="hesab5 t", accounting_status_code=0),
        connection_factory=lambda: conn
    )
    reader.list_groups()
    reader.find_person_by_mobile("09121234567")
    statements = [sql for sql, _ in conn.sql]
    assert any("[hesab5 t].dbo.Gkala" in sql for sql in statements)
    assert any("[hesab5 t].dbo.name_mo" in sql for sql in statements)


def test_writer_brackets_the_database_name():
    conn = FakeConn(max_codlp=0)
    writer = AccountingWriter(
        Settings(accounting_database="hesab5 t", accounting_status_code=0),
        connection_factory=lambda: conn
    )
    writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    statements = [sql for sql, _ in conn.executed]
    assert any("[hesab5 t].dbo.KalaOrder" in sql for sql in statements)
    assert any("[hesab5 t].dbo.KalaOrderDetail" in sql for sql in statements)
    assert any("[hesab5 t].dbo.MiladiToShamsi" in sql for sql in statements)


def test_default_database_matches_the_dev_copy():
    assert Settings().accounting_database == "hesab5 t"


def test_json_responses_declare_the_utf8_charset():
    """PowerShell 5.1 needs the charset to decode Persian names correctly."""
    from app.main import create_app

    app = create_app()
    assert app.router.default_response_class.media_type == "application/json; charset=utf-8"
