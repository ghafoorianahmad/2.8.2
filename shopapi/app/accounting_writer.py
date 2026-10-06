"""Order writer for the accounting DB (dry-run by default).

Runs the full insert transaction and ROLLS BACK unless real writes are enabled
for the connected host. Idempotent on Sharhlp = 'API-<our order id>'. SQL Server
2008 R2 compatible. Only the string 'API-<id>' is ever written as free text;
sharh/field1..8/tavasot are bound as empty strings (never NULL), matching how the
desktop software builds item names by string concatenation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyodbc

from .config import Settings
from .util import quote_identifier, round_half_up

# Column lists are the single source of truth: the INSERT text and the parameter
# tuple are both generated from these sequences, so a placeholder/parameter
# mismatch (an off-by-one) cannot happen again. A fake connection does not parse
# SQL, so the unit tests also assert the arithmetic explicitly.
HEADER_COLUMNS = (
    "Codlp", "Codnlp", "Datelp", "Mablp", "Sharhlp", "Codf", "takhfif", "tavasot",
    "avarez", "va", "Taf2", "Status", "PrintCount", "usercode", "Naghd", "Ischeck",
)
DETAIL_COLUMNS = (
    "Num", "Codlp_", "Codekala", "Meg", "Gey", "sharh", "AnbarCode",
    "PrintCount", "takhfif",
    "field1", "field2", "field3", "field4", "field5", "field6", "field7", "field8",
)


def insert_statement(table: str, columns: tuple[str, ...], values: tuple) -> tuple[str, tuple]:
    """Return ``(sql, values)`` for a parameterized INSERT.

    Raises ValueError when the number of values does not match the number of
    columns, which is exactly the bug this helper was introduced to prevent.
    """
    if len(columns) != len(values):
        raise ValueError(f"{table}: {len(columns)} columns but {len(values)} values")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    return sql, tuple(values)


@dataclass
class WriteResult:
    accounting_order_no: int
    person_code: int
    datelp: str
    mablp: float
    status_code: int
    usercode: int
    anbarcode: int
    items: list = field(default_factory=list)  # [{num, codekala, meg, gey}]
    idempotent: bool = False
    committed: bool = False
    rolled_back: bool = False


class AccountingWriter:
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

    def write_allowed(self) -> bool:
        return self.settings.write_allowed()

    def write_order(
        self,
        our_order_id: int,
        person_code: int,
        items: list[tuple[int, float, float]],
        dry_run: bool | None = None,
    ) -> WriteResult:
        """items: list of (kala_code, qty, unit_price)."""
        if dry_run is None:
            dry_run = not self.write_allowed()

        sharhlp = f"API-{our_order_id}"
        mablp = sum(round_half_up(qty * price) for _, qty, price in items)
        status_code = self.settings.accounting_status_code
        usercode = self.settings.accounting_usercode
        anbarcode = self.settings.accounting_anbarcode

        conn = self.connection()
        try:
            conn.autocommit = False
            conn.execute("SET LOCK_TIMEOUT 5000")
            try:
                return self._run(
                    conn, person_code, items, sharhlp, mablp,
                    status_code, usercode, anbarcode, dry_run,
                )
            except pyodbc.Error as exc:
                conn.rollback()
                # 1222 = lock request timeout; retry once.
                if "1222" in str(exc):
                    conn.execute("SET LOCK_TIMEOUT 5000")
                    return self._run(
                        conn, person_code, items, sharhlp, mablp,
                        status_code, usercode, anbarcode, dry_run,
                    )
                raise
        finally:
            conn.close()

    def _run(
        self,
        conn,
        person_code: int,
        items: list[tuple[int, float, float]],
        sharhlp: str,
        mablp: float,
        status_code: int,
        usercode: int,
        anbarcode: int,
        dry_run: bool,
    ) -> WriteResult:
        db = self._db()

        written_items = [
            {"num": i, "codekala": k, "meg": q, "gey": p}
            for i, (k, q, p) in enumerate(items, start=1)
        ]

        # Next order number, serialized inside the transaction. The update/hold
        # lock is taken BEFORE the idempotency check so that two concurrent
        # writers for the same order cannot both pass the check and insert two
        # headers for one order (the second waits, then sees the first's row).
        codlp = int(
            conn.execute(
                f"SELECT ISNULL(MAX(Codlp),0)+1 AS n "
                f"FROM {db}.dbo.KalaOrder WITH (UPDLOCK, HOLDLOCK)"
            ).fetchone()[0]
        )

        # Idempotency: an existing header with the same Sharhlp means this order
        # was already written; return its Codlp without inserting again.
        existing = conn.execute(
            f"SELECT ISNULL(MAX(Codlp),0) AS n FROM {db}.dbo.KalaOrder WHERE Sharhlp = ?",
            sharhlp,
        ).fetchone()
        if existing is not None and int(existing[0]) > 0:
            conn.rollback()
            return WriteResult(
                accounting_order_no=int(existing[0]),
                person_code=person_code,
                datelp="",
                mablp=mablp,
                status_code=status_code,
                usercode=usercode,
                anbarcode=anbarcode,
                items=written_items,
                idempotent=True,
                committed=False,
                rolled_back=False,
            )

        # Shamsi date via the accounting DB function (no user input here).
        datelp = conn.execute(
            f"SELECT {db}.dbo.MiladiToShamsi(CONVERT(varchar(20), CONVERT(date, GETDATE()))) AS d"
        ).fetchone()[0]

        header_sql, header_values = insert_statement(
            f"{db}.dbo.KalaOrder",
            HEADER_COLUMNS,
            (codlp, person_code, datelp, mablp, sharhlp, -100, 0, "", 0, 0, 0,
             status_code, 0, usercode, 0, 0),
        )
        conn.execute(header_sql, *header_values)

        for num, (kala_code, qty, unit_price) in enumerate(items, start=1):
            detail_sql, detail_values = insert_statement(
                f"{db}.dbo.KalaOrderDetail",
                DETAIL_COLUMNS,
                (num, codlp, kala_code, qty, unit_price, "", anbarcode, 0, 0,
                 "", "", "", "", "", "", "", ""),
            )
            conn.execute(detail_sql, *detail_values)

        count = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM {db}.dbo.KalaOrder WHERE Codlp = ?", codlp
            ).fetchone()[0]
        )
        if count != 1:
            conn.rollback()
            raise RuntimeError(
                f"expected exactly 1 KalaOrder row for Codlp={codlp}, found {count}"
            )

        if dry_run:
            conn.rollback()
            return WriteResult(
                accounting_order_no=codlp,
                person_code=person_code,
                datelp=datelp,
                mablp=mablp,
                status_code=status_code,
                usercode=usercode,
                anbarcode=anbarcode,
                items=written_items,
                idempotent=False,
                committed=False,
                rolled_back=True,
            )

        conn.commit()
        return WriteResult(
            accounting_order_no=codlp,
            person_code=person_code,
            datelp=datelp,
            mablp=mablp,
            status_code=status_code,
            usercode=usercode,
            anbarcode=anbarcode,
            items=written_items,
            idempotent=False,
            committed=True,
            rolled_back=False,
        )
