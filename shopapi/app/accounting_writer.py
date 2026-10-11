"""Order and person writer for the accounting DB (dry-run by default).

Runs the full insert transaction and ROLLS BACK unless real writes are enabled
for the connected host. Idempotent on Sharhlp = 'API-<our order id>'. SQL Server
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
    status_code: int
    usercode: int
    anbarcode: int
    items: list = field(default_factory=list)  # [{num, codekala, meg, gey}]
    idempotent: bool = False
    committed: bool = False
    rolled_back: bool = False


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
        mablp = sum(qty * price for _, qty, price in items)  # §5.2: no rounding
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
        if dry_run is None:
            dry_run = not self.write_allowed()
        phone = "0" + key  # 09xxxxxxxxx, as the software stores it

        conn = self.connection()
        try:
            conn.autocommit = False
            conn.execute("SET LOCK_TIMEOUT 5000")
            try:
                return self._create_person(
                    conn, first_name, last_name, phone, key, address or "", dry_run
                )
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    def _create_person(
        self, conn, first_name: str, last_name: str, phone: str, key: str,
        address: str, dry_run: bool,
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
        ) + ("",) * len(PERSON_EMPTY_TEXT_COLUMNS)
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

        if dry_run:
            conn.rollback()
            return PersonResult(person_code=code, taf_code=taf, rolled_back=True)
        conn.commit()
        return PersonResult(person_code=code, taf_code=taf, committed=True)

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
            )

        codlp = int(
            conn.execute(f"SELECT ISNULL(MAX(Codlp),0)+1 AS n FROM {db}.dbo.KalaOrder").fetchone()[0]
        )

        # Shamsi date via the accounting DB function (no user input here).
        datelp = conn.execute(
            f"SELECT {db}.dbo.MiladiToShamsi(CONVERT(varchar(20), CONVERT(date, GETDATE()))) AS d"
        ).fetchone()[0]

        header_sql, header_values = insert_statement(
            f"{db}.dbo.KalaOrder",
            HEADER_COLUMNS,
            (codlp, person_code, datelp, mablp, sharhlp, -100, 0, "", 0, 0,
             status_code, 0, usercode, 0, 0, 0),
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
