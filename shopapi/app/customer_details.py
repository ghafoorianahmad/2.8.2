"""A customer's details in the bot (v2.17.0): first and last name, national code, address.

The bot asks once, after the phone is shared, for what neither we nor «سازه حساب»
know. A new customer's details go into the person when staff create it; an existing
person only ever gets its EMPTY fields filled (the writer's WHERE clause guarantees
it), nothing is overwritten. What could not reach «سازه حساب» yet (writes off, accounting
down, the grants of sql/upgrade_2_17_0.sql not run) stays in our own database and is
tried again later.
"""
from __future__ import annotations

import asyncio
import logging
import re

from .db_own import OwnDB
from .text import normalize_fa

logger = logging.getLogger("shopapi.customer_details")

FIELDS = ("first_name", "last_name", "national_code", "address")
MAX_NAME = 50
MIN_ADDRESS = 5
MAX_ADDRESS = 500
#: Letters of any script, with spaces, ZWNJ, hyphen, dot and apostrophe between them.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ ‌\-.'][^\W\d_]+)*$")

INVALID_NAME = "Invalid name"
INVALID_NATIONAL_CODE = "Invalid national code"
INVALID_ADDRESS = "Invalid address"


def national_code_ok(code: str) -> bool:
    """The Iranian national code's check digit (10 digits; all equal is refused)."""
    if not re.fullmatch(r"\d{10}", code) or len(set(code)) == 1:
        return False
    remainder = sum(int(code[i]) * (10 - i) for i in range(9)) % 11
    check = int(code[9])
    return check == remainder if remainder < 2 else check == 11 - remainder


def clean_name(value: str | None) -> str:
    return " ".join(normalize_fa(value).split())


def clean_address(value: str | None) -> str:
    return " ".join(normalize_fa(value).split())


def clean_values(values: dict) -> tuple[dict, str | None]:
    """{field: clean value} of the filled ones, and the first problem (or None)."""
    out: dict = {}
    for field in ("first_name", "last_name"):
        if values.get(field):
            name = clean_name(values[field])
            if not (2 <= len(name) <= MAX_NAME) or not _NAME_RE.match(name):
                return out, INVALID_NAME
            out[field] = name
    if values.get("national_code"):
        code = "".join(normalize_fa(values["national_code"]).split()).replace("-", "")
        if not national_code_ok(code):
            return out, INVALID_NATIONAL_CODE
        out["national_code"] = code
    if values.get("address"):
        address = clean_address(values["address"])
        if not (MIN_ADDRESS <= len(address) <= MAX_ADDRESS):
            return out, INVALID_ADDRESS
        out["address"] = address
    return out, None


def _person(reader, user: dict) -> dict | None:
    """The linked person's details: {} without a person, None when unknown (accounting
    down, or the grants of sql/upgrade_2_17_0.sql were not run yet)."""
    code = user.get("person_code")
    if code is None:
        return {}
    try:
        return reader.person_details(int(code))
    except Exception as exc:  # noqa: BLE001 - pyodbc errors, permission denied, timeouts
        logger.warning("person details not read: %s", type(exc).__name__)
        return None


def view(db: OwnDB, reader, user: dict) -> dict:
    """For the bot: which fields are missing and the saved address. Never the name or
    the national code: the bot has no need of them. ``known`` false = «سازه حساب» could
    not be read, so nothing is called missing."""
    person = _person(reader, user)
    merged = {field: str(user.get(field) or "").strip()
              or str((person or {}).get(field) or "").strip() for field in FIELDS}
    known = person is not None
    return {"missing": [f for f in FIELDS if known and not merged[f]],
            "address": merged["address"], "asked": bool(user.get("details_asked_at")),
            "known": known}


def sync(db: OwnDB, writer, user: dict) -> bool:
    """Fill the linked person's EMPTY fields from our values. True: nothing left to do."""
    code = user.get("person_code")
    values = {field: str(user.get(field) or "").strip() for field in FIELDS}
    values = {field: value for field, value in values.items() if value}
    if code is None or not values:
        return code is not None
    try:
        result = writer.fill_person_empty(int(code), values)
    except Exception as exc:  # noqa: BLE001 - never stops the customer; tried again later
        logger.warning("person details not written: %s", type(exc).__name__)
        db.update_user_details(int(user["id"]), details_sync=1)
        return False
    if not result.committed:
        db.update_user_details(int(user["id"]), details_sync=1)   # writes are off here
        return False
    db.update_user_details(int(user["id"]), details_sync=0)
    db.audit("system:details", "person_fields_filled",
             f"user id={user['id']} person_code={code} fields={sorted(result.filled)}")
    return True


def save(db: OwnDB, writer, user: dict, values: dict) -> dict:
    """Store the customer's answers (already clean) and try «سازه حساب» at once."""
    row = db.update_user_details(int(user["id"]), details_sync=1, **values)
    first, last = str(row.get("first_name") or ""), str(row.get("last_name") or "")
    if first and last:
        row = db.update_user_contact(int(user["id"]), name=f"{first} {last}")
    sync(db, writer, row)
    return db.get_user_by_id(int(user["id"]))


def first_address(db: OwnDB, reader, writer, user: dict, address: str) -> None:
    """Item 10: the first address a customer gives becomes their saved one (ours, and
    «سازه حساب» only if that field is empty). A later «آدرس جدید» stays on its order."""
    if not address or view(db, reader, user)["address"]:
        return
    save(db, writer, user, {"address": address})


async def sync_loop(settings, db_factory, writer_factory, seconds: int = 300) -> None:
    """Background: what could not reach «سازه حساب» earlier (never raises)."""
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(sync_waiting, db_factory(), writer_factory())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("person details sync failed: %s", type(exc).__name__)


def sync_waiting(db: OwnDB, writer) -> int:
    done = 0
    for user in db.users_waiting_sync():
        if sync(db, writer, user):
            done += 1
    return done
