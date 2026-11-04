"""v2.18.2 «گردش سال‌های قبل»: every person of «سازه حساب» and their account turnover, in any
fiscal-year database this sign-in may read. READ-ONLY: only SELECTs, and the shop's own reading and
writing stay on the database chosen in the server settings.

The database name is never taken from the request as it is: it must be on the list the server itself
just read. The national code is masked unless the user has the tick «کد ملی و نشانی مشتری».
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..customer_details import mask_national_code
from ..security import Identity, require_permission
from ..staff import P_CUSTOMER_PRIVATE_VIEW, P_LEDGER_VIEW
from ..statement import build_full_statement
from ..text import normalize_fa

router = APIRouter()

CAN_VIEW = Depends(require_permission(P_LEDGER_VIEW))
NOT_READABLE = "Fiscal database is not readable"
NATIONAL_CODE_LENGTH = 10
MAX_PERSONS = 200


def _checked(reader: AccountingReader, database: str) -> str:
    if database not in {row["name"] for row in reader.ledger_databases()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_READABLE)
    return database


def _digits(text: object) -> str:
    return "".join(ch for ch in normalize_fa(str(text or "")) if ch.isascii() and ch.isdigit())


def matches(person: dict, query: str, *, may_see_code: bool) -> bool:
    """Name, phone or national code. Without the tick only the whole national code matches, or
    trying digit after digit would read the code out."""
    wanted = normalize_fa(query).casefold()
    if " ".join(wanted.split()) in " ".join(normalize_fa(person["name"]).casefold().split()):
        return True
    digits = _digits(query)
    if not digits or len(digits) != len(wanted.replace(" ", "")):
        return False
    code = _digits(person["national_code"])
    if may_see_code:
        if digits in code:
            return True
    elif len(digits) == NATIONAL_CODE_LENGTH and digits == code:
        return True
    return any((digits.lstrip("0") or digits) in phone for phone in person["phones"])


@router.get("/admin/ledger/databases")
def ledger_databases(
    _who: Identity = CAN_VIEW,
    settings: Settings = Depends(deps.get_settings),
    reader: AccountingReader = Depends(deps.get_reader),
) -> list[dict]:
    current = settings.database_name()
    return [{"name": row["name"], "current": row["name"] == current}
            for row in reader.ledger_databases()]


@router.get("/admin/ledger/persons")
def ledger_persons(
    db: str = Query(..., max_length=64),
    q: str = Query("", max_length=100),
    who: Identity = CAN_VIEW,
    reader: AccountingReader = Depends(deps.get_reader),
) -> dict:
    database = _checked(reader, db)
    may_see_code = who.kind == "staff" and who.can(P_CUSTOMER_PRIVATE_VIEW)
    query = q.strip()
    found = [person for person in reader.ledger_persons(database)
             if not query or matches(person, query, may_see_code=may_see_code)]
    items = []
    for person in found[:MAX_PERSONS]:
        code = person["national_code"]
        items.append({"code": person["code"], "name": person["name"],
                      "national_code": code if may_see_code else mask_national_code(code),
                      # enough to tell two people with one name apart, as in «محاسبهٔ اقساط»
                      "phone_tail": person["phones"][0][-2:] if person["phones"] else ""})
    return {"total": len(found), "items": items}


@router.get("/admin/ledger/persons/{code}/statement")
def ledger_statement(
    code: int,
    db: str = Query(..., max_length=64),
    _who: Identity = CAN_VIEW,
    settings: Settings = Depends(deps.get_settings),
    reader: AccountingReader = Depends(deps.get_reader),
) -> dict:
    database = _checked(reader, db)
    data = reader.customer_statement(code, settings.statement_max_rows, database=database)
    return {"person_code": code, "database": database,
            **build_full_statement(data, settings.statement_max_rows)}
