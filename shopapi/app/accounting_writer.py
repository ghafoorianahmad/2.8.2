"""Order and person writer for the accounting DB (dry-run by default).

A dry run only READS (lock, idempotency check, next code, Shamsi date) and
never sends an INSERT/UPDATE; a real write happens only when
``Settings.write_allowed()`` (test copy on the test allowlist, or switch +
allowed host + allowlisted database) and, for orders, a configured
``ACCOUNTING_STATUS_CODE``. Idempotent on Sharhlp = 'API-<our order id>'. SQL Server
2008 R2 compatible. Codes are MAX+1 (the tables have no unique index), so every
write first takes an application lock with sp_getapplock (SAZEH_DB_REFERENCE
§5.0: no duplicates and no deadlocks, unlike UPDLOCK/HOLDLOCK).

Only the string 'API-<id>' is ever written as free text on orders;
sharh/field1..8/tavasot are bound as empty strings (never NULL), matching how the
desktop software builds item names by string concatenation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyodbc

from .accounting_reader import person_codes_by_mobile_sql
from .config import Settings
from .text import mobile_key
from .util import quote_identifier

# Column lists are the single source of truth: the INSERT text and the parameter
# tuple are both generated from these sequences, so a placeholder/parameter
# mismatch (an off-by-one) cannot happen again. A fake connection does not parse
# SQL, so the unit tests also assert the arithmetic explicitly.
# Header = recipe §5.2 (+ PrintCount). Taf2/UseUser/Ras/NetOrder/... stay NULL.
HEADER_COLUMNS = (
    "Codlp", "Codnlp", "Datelp", "Mablp", "Sharhlp", "Codf", "takhfif", "tavasot",
    "avarez", "va", "Status", "PrintCount", "usercode", "Naghd", "Ischeck", "keraye",
)
DETAIL_COLUMNS = (
    "Num", "Codlp_", "Codekala", "Meg", "Gey", "sharh", "AnbarCode",
    "PrintCount", "takhfif",
    "field1", "field2", "field3", "field4", "field5", "field6", "field7", "field8",
)


# sp_getapplock: lock owned by the transaction, released at COMMIT/ROLLBACK.
APPLOCK_SQL = (
    "DECLARE @r int; EXEC @r = sp_getapplock @Resource=?, @LockMode='Exclusive', "
    "@LockOwner='Transaction', @LockTimeout=15000; SELECT @r AS r"
)
ORDER_LOCK = "shop:KalaOrder"
PERSON_LOCK = "shop:name_mo"

# New customers go to group 4 (مشتریان); its taf ledger is como=13, codgtaf=59
# (gsh of group 4, reference §5.1).
PERSON_GROUP = 4
PERSON_TAF_COMO = 13
PERSON_TAF_GROUP = 59

# 26 text columns of name_mo the software concatenates: written as '' (never NULL).
PERSON_EMPTY_TEXT_COLUMNS = (
    "Addres", "Cherk", "Zamin", "memo1", "pic", "codeposti", "Codemelli",
    "Numbershenasname", "Moaref", "ShomareEghtesadi", "Namepedar", "AccountingNumber",
    "Degree_salary", "BankeName_salary", "Field_salary", "ShobeName_salary",
    "ServiceTitle_salary", "ServiceDate_salary", "UnderWrite_salary",
    "ThumbPrint_salary", "ShoamreBime_salary", "Jensiat_salary", "shenaseMeli",
    "shomareSabt", "start_salary_work", "end_salary_work",
)


class AccountingLockTimeout(RuntimeError):
    """sp_getapplock did not grant the lock within its timeout."""


class AccountingWriteRefused(RuntimeError):
    """A real write was asked for a database/host where writes are not allowed."""


class AccountingConfigError(RuntimeError):
    """A setting needed for a real write is missing or known to be wrong
    (``ACCOUNTING_STATUS_CODE``)."""


class DuplicateOrderNumber(RuntimeError):
    """Another KalaOrder row has the Codlp we just inserted (rolled back)."""

    def __init__(self, codlp: int, count: int):
        super().__init__(f"expected exactly 1 KalaOrder row for Codlp={codlp}, found {count}")
        self.codlp = codlp
        self.count = count


def take_applock(conn, resource: str) -> None:
    row = conn.execute(APPLOCK_SQL, resource).fetchone()
    result = int(row[0]) if row is not None and row[0] is not None else -999
    if result < 0:  # -1 timeout, -2 cancelled, -3 deadlock victim, -999 error
        raise AccountingLockTimeout(f"sp_getapplock({resource}) returned {result}")


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
    status_code: int | None
    usercode: int
    anbarcode: int
    items: list = field(default_factory=list)  # [{num, codekala, meg, gey}]
    idempotent: bool = False
    committed: bool = False
    rolled_back: bool = False
    #: The database the order was (or would be) written to.
    database: str = ""
    #: Rows with our Codlp found right after COMMIT (1 = fine; >1 = another
    #: program wrote the same number; nothing is deleted, the admin is alerted).
    codlp_rows_after_commit: int = 0

    @property
    def duplicate_after_commit(self) -> bool:
        return self.committed and self.codlp_rows_after_commit > 1


@dataclass
class PersonResult:
    person_code: int
    #: True when the mobile already belonged to a person: nothing was created.
    existing: bool = False
    #: More than one existing person has this mobile; person_code is the lowest.
    ambiguous: bool = False
    taf_code: int | None = None
    committed: bool = False
    rolled_back: bool = False


@dataclass
class PersonFill:
    """v2.17.0: what ``fill_person_empty`` did; ``filled`` = the columns really written."""
    person_code: int
    filled: list = field(default_factory=list)
    committed: bool = False


#: v2.17.0: our field -> the column of name_mo that holds it (recipe §5.1). The address
#: is written to Addres2 (the software's own column) and counts as present when either
#: Addres or Addres2 holds something.
PERSON_FILL_COLUMNS = {"first_name": "fname", "last_name": "Name",
                       "national_code": "Codemelli", "address": "Addres2"}


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

    def _resolve_dry_run(self, dry_run: bool | None) -> bool:
        """None = follow the settings; False (a real write) must also be allowed."""
        if dry_run is None:
            return not self.write_allowed()
        if not dry_run and not self.write_allowed():
            raise AccountingWriteRefused(
                f"real writes are not allowed for database {self.settings.database_name()!r}")
        return bool(dry_run)

    def write_order(
        self,
        our_order_id: int,
        person_code: int,
        items: list[tuple[int, float, float]],
        dry_run: bool | None = None,
    ) -> WriteResult:
        """items: list of (kala_code, qty, unit_price)."""
        dry_run = self._resolve_dry_run(dry_run)
        if not dry_run:
            problem = self.settings.status_code_problem()
            if problem:
                # Never guess KalaOrder.Status: an empty one is «بدون وضعیت» in the software.
                raise AccountingConfigError(problem)

        sharhlp = f"API-{our_order_id}"
        mablp = sum(it[1] * it[2] for it in items)  # §5.2: no rounding
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
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    def create_person(
        self,
        first_name: str,
        last_name: str,
        mobile: str,
        address: str = "",
        dry_run: bool | None = None,
        national_code: str = "",
    ) -> PersonResult:
        """Create a customer per recipe §5.1 - unless the mobile already exists.

        The accounting UI refuses duplicate phone numbers but the DB has no
        unique constraint, so the R4 lookup (DetailTBL types 1 and 3) runs inside
        the same transaction, under the person app lock: an existing person is
        returned (``existing=True``) and nothing is inserted.
        """
        key = mobile_key(mobile)
        if key is None:
            raise ValueError("not a mobile number")
        first_name = (first_name or "").strip()
        last_name = (last_name or "").strip()
        if not last_name:
            raise ValueError("last name is required")
        dry_run = self._resolve_dry_run(dry_run)
        phone = "0" + key  # 09xxxxxxxxx, as the software stores it

        conn = self.connection()
        try:
            conn.autocommit = False
            conn.execute("SET LOCK_TIMEOUT 5000")
            try:
                return self._create_person(
                    conn, first_name, last_name, phone, key, address or "", dry_run,
                    national_code or "",
                )
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    def _create_person(
        self, conn, first_name: str, last_name: str, phone: str, key: str,
        address: str, dry_run: bool, national_code: str = "",
    ) -> PersonResult:
        db = self._db()
        take_applock(conn, PERSON_LOCK)

        found = [int(r[0]) for r in conn.execute(person_codes_by_mobile_sql(db), key).fetchall()]
        if found:
            conn.rollback()
            return PersonResult(person_code=found[0], existing=True, ambiguous=len(found) > 1)

        code = int(
            conn.execute(f"SELECT ISNULL(MAX(Code),0)+1 AS n FROM {db}.dbo.name_mo").fetchone()[0]
        )
        today = conn.execute(f"SELECT {db}.dbo.MiladiToShamsi(GETDATE()) AS d").fetchone()[0]
        if dry_run:
            # A dry run never sends an INSERT/UPDATE: report what would be created.
            conn.rollback()
            return PersonResult(person_code=code, rolled_back=True)

        columns = (
            "Code", "Gcod", "fname", "Name", "Addres2", "datestart", "l_gey", "tartavalod",
            "Man_f", "Mah_f", "Man_n", "Mah_n", "etebar", "etebar2", "etebar3",
            "datebedehe", "mabbedehe", "sumbed", "sumbes", "CodeEghtesadi", "VisitorPercent",
            "Mary_date", "ClubMember", "clubIntroducer", "ClubScore", "Is_salary",
            "ServiceType_salary", "TypeBime_salary", "IsMarried_salary",
            "Code_personley_salary", "isEnd_salary_work", "number_children", "telephons",
        ) + PERSON_EMPTY_TEXT_COLUMNS
        values = (
            code, PERSON_GROUP, first_name, last_name, address, today, 1, "1300/01/01",
            0, "بي حساب", 0, "بي حساب", 0, 0, 0,
            today, 0, 0, 0, 0, 0,
            "    /  /   ", 0, 0, 0, 0,
            0, 0, 0,
            0, 0, 0, phone,
        ) + tuple(national_code if column == "Codemelli" else ""
                  for column in PERSON_EMPTY_TEXT_COLUMNS)
        sql, params = insert_statement(f"{db}.dbo.name_mo", columns, values)
        conn.execute(sql, *params)

        sql, params = insert_statement(
            f"{db}.dbo.taf", ("cota", "como", "va", "codgtaf", "Sharh"),
            (code, PERSON_TAF_COMO, 1, PERSON_TAF_GROUP, f"{first_name} {last_name}".strip()[:100]),
        )
        conn.execute(sql, *params)
        # taf.Code is an IDENTITY: read it back by its natural key, not @@IDENTITY.
        taf = int(
            conn.execute(
                f"SELECT MAX(Code) AS n FROM {db}.dbo.taf WHERE Cota = ? AND codgtaf = ?",
                code, PERSON_TAF_GROUP,
            ).fetchone()[0]
        )
        conn.execute(f"UPDATE {db}.dbo.name_mo SET codetaf = ? WHERE Code = ?", taf, code)
        sql, params = insert_statement(
            f"{db}.dbo.DetailTBL", ("IDMaster", "TabaghehBandiID", "Comment", "Va", "darfn"),
            (code, 3, phone, 0, 1),  # 3 = mobile
        )
        conn.execute(sql, *params)

        conn.commit()
        return PersonResult(person_code=code, taf_code=taf, committed=True)

    def fill_person_empty(self, person_code: int, values: dict,
                          dry_run: bool | None = None) -> PersonFill:
        """v2.17.0: write ``values`` ({our field: text}) into the person's EMPTY fields;
        never overwrites: the condition is in each UPDATE, so a value someone typed in
        the software a moment ago stays. A dry run sends no UPDATE. Text is cut to the
        column's size; a column whose size is unknown is left alone."""
        dry_run = self._resolve_dry_run(dry_run)
        result = PersonFill(person_code=int(person_code))
        wanted = {PERSON_FILL_COLUMNS[f]: str(v).strip() for f, v in values.items()
                  if f in PERSON_FILL_COLUMNS and str(v or "").strip()}
        if dry_run or not wanted:
            return result
        db = self._db()
        conn = self.connection()
        try:
            conn.autocommit = False
            conn.execute("SET LOCK_TIMEOUT 5000")
            try:
                take_applock(conn, PERSON_LOCK)
                sizes = self._person_column_sizes(conn, list(wanted))
                for column, text in wanted.items():
                    size = sizes.get(column)
                    if size is None:
                        continue
                    empty = f"LTRIM(RTRIM(ISNULL({column}, ''))) = ''"
                    if column == "Addres2":
                        empty += " AND LTRIM(RTRIM(ISNULL(Addres, ''))) = ''"
                    cursor = conn.execute(
                        f"UPDATE {db}.dbo.name_mo SET {column} = ? WHERE Code = ? AND {empty}",
                        text[:size] if size > 0 else text, int(person_code))
                    if getattr(cursor, "rowcount", 0) > 0:
                        result.filled.append(column)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()
        result.committed = True
        return result

    def _person_column_sizes(self, conn, columns: list[str]) -> dict[str, int]:
        """{column: characters} of name_mo; 0 = no limit (varchar(max))."""
        marks = ",".join("?" for _ in columns)
        rows = conn.execute(
            "SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH FROM "
            f"{self._db()}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_NAME = 'name_mo' AND COLUMN_NAME IN ({marks})", *columns,
        ).fetchall()
        return {str(r[0]): (0 if r[1] in (-1, None) else int(r[1])) for r in rows}

    def _run(
        self,
        conn,
        person_code: int,
        items: list[tuple[int, float, float]],
        sharhlp: str,
        mablp: float,
        status_code: int | None,
        usercode: int,
        anbarcode: int,
        dry_run: bool,
    ) -> WriteResult:
        db = self._db()

        written_items = [
            {"num": i, "codekala": k, "meg": q, "gey": p}
            for i, (k, q, p) in enumerate((it[:3] for it in items), start=1)
        ]

        # Serialize all our order writers BEFORE the idempotency check, so two
        # writers for the same order cannot both pass it (the second waits for
        # the first to commit, then sees its row).
        take_applock(conn, ORDER_LOCK)

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
                database=self.settings.database_name(),
            )

        codlp = int(
            conn.execute(f"SELECT ISNULL(MAX(Codlp),0)+1 AS n FROM {db}.dbo.KalaOrder").fetchone()[0]
        )

        # Shamsi date via the accounting DB function (no user input here).
        datelp = conn.execute(
            f"SELECT {db}.dbo.MiladiToShamsi(CONVERT(varchar(20), CONVERT(date, GETDATE()))) AS d"
        ).fetchone()[0]

        database = self.settings.database_name()
        if dry_run:
            # A dry run never sends an INSERT: the would-be Codlp/date/sum only.
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
                database=database,
            )

        header_sql, header_values = insert_statement(
            f"{db}.dbo.KalaOrder",
            HEADER_COLUMNS,
            (codlp, person_code, datelp, mablp, sharhlp, -100, 0, "", 0, 0,
             status_code, 0, usercode, 0, 0, 0),
        )
        conn.execute(header_sql, *header_values)

        sharh_max = self._sharh_length(conn) if any(len(it) > 3 and it[3] for it in items) else 0
        for num, item in enumerate(items, start=1):
            kala_code, qty, unit_price = item[:3]
            # v2.6.2: «color — part» of a phone in the line description, cut to the
            # column's size (unknown size = left empty, never a truncation error).
            sharh = str(item[3] if len(item) > 3 else "")[:sharh_max] if sharh_max else ""
            detail_sql, detail_values = insert_statement(
                f"{db}.dbo.KalaOrderDetail",
                DETAIL_COLUMNS,
                (num, codlp, kala_code, qty, unit_price, sharh, anbarcode, 0, 0,
                 "", "", "", "", "", "", "", ""),
            )
            conn.execute(detail_sql, *detail_values)

        count = self._codlp_rows(conn, codlp)
        if count != 1:
            conn.rollback()
            raise DuplicateOrderNumber(codlp, count)

        conn.commit()
        # The desktop software takes no lock (MAX+1), so it can still write the
        # same Codlp next to ours: look again after COMMIT. Nothing is deleted;
        # the caller alerts the admin when there is more than one row.
        try:
            after = self._codlp_rows(conn, codlp)
            conn.rollback()   # end the read-only transaction
        except pyodbc.Error:
            after = 0         # unknown; the order itself is committed
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
            database=database,
            codlp_rows_after_commit=after,
        )

    def _sharh_length(self, conn) -> int:
        """Characters ``KalaOrderDetail.sharh`` holds (0 = unknown -> not used)."""
        try:
            row = conn.execute(
                "SELECT CHARACTER_MAXIMUM_LENGTH AS n FROM "
                f"{self._db()}.INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = 'KalaOrderDetail' AND COLUMN_NAME = 'sharh'"
            ).fetchone()
        except pyodbc.Error:
            return 0
        value = row[0] if row is not None else None
        if value is None:
            return 0
        value = int(value)
        return 200 if value == -1 else max(0, min(value, 200))

    def _codlp_rows(self, conn, codlp: int) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {self._db()}.dbo.KalaOrder WHERE Codlp = ?", codlp
        ).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else 0
