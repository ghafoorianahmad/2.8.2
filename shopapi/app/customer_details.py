"""A customer's details (v2.17.0; v2.18.0: all four are required, there is no «فعلاً نه»).

The bot asks, after the phone is shared, for what neither we nor «سازه حساب» know, and asks
again until it has all of first name, last name, national code and address: nothing is written
to «سازه حساب» before that. A new customer's details go into the person when staff create it; an
existing person only ever gets its EMPTY fields filled (the writer's WHERE clause guarantees
it), nothing is overwritten. What could not reach «سازه حساب» yet (writes off, accounting
down, the grants of sql/upgrade_2_17_0.sql not run) stays in our own database and is
tried again later. A number the person does not have yet is added to their phones.
"""
from __future__ import annotations

import asyncio
import logging

from . import name_match, validators
from .db_own import OwnDB
from .text import mobile_key

logger = logging.getLogger("shopapi.customer_details")

FIELDS = ("first_name", "last_name", "national_code", "address")

#: refused by POST /admin/orders/{id}/write-accounting; ShopAdmin shows it in Persian
DETAILS_INCOMPLETE = "Customer details are incomplete"
#: «سازه حساب» says this national code is somebody else's
NATIONAL_CODE_TAKEN = "این کد ملی در حسابداری برای شخص دیگری ثبت شده است."


def national_code_ok(code: str) -> bool:
    """10 digits with the check digit, or a foreign national's 11 digits."""
    return validators.validate_national_code(code).valid


def clean_values(values: dict) -> tuple[dict, str | None]:
    """{field: clean value} of the filled ones, and the first problem as a Persian sentence
    (or None). The same rules as the form's validators.js: never trust what a page sends."""
    out: dict = {}
    for field in FIELDS:
        if values.get(field):
            check = validators.VALIDATORS[field](values[field])
            if not check.valid:
                return out, check.error
            out[field] = check.normalized
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
    """For the bot: which fields are missing, the saved address and (v2.18.0) what the form
    opens with. ``known`` false = «سازه حساب» could not be read: nothing is asked (it may well
    know them), and :func:`write_problem` refuses to write until it can be read."""
    person = _person(reader, user)
    merged = {field: str(user.get(field) or "").strip()
              or str((person or {}).get(field) or "").strip() for field in FIELDS}
    known = person is not None
    return {"missing": [f for f in FIELDS if known and not merged[f]],
            "address": merged["address"], "asked": bool(user.get("details_asked_at")),
            "known": known, "prefill": merged}


def write_problem(db: OwnDB, reader, user_id: int) -> list[str]:
    """v2.18.0: what stops this customer's order from being written to «سازه حساب»: the
    fields still empty. Not being able to read the person leaves it unproven, so it stops too."""
    user = db.get_user_by_id(int(user_id))
    if user is None:
        return list(FIELDS)
    details = view(db, reader, user)
    if not details["known"]:
        return [f for f in FIELDS if not details["prefill"][f]]
    return details["missing"]


def sync(db: OwnDB, writer, user: dict) -> bool:
    """Fill the linked person's EMPTY fields from our values and add the customer's number to
    the person's phones if it is not there yet. True: nothing left to do."""
    code = user.get("person_code")
    values = {field: str(user.get(field) or "").strip() for field in FIELDS}
    values = {field: value for field, value in values.items() if value}
    if code is None:
        return False
    try:
        result = writer.fill_person_empty(int(code), values) if values else None
        phone = writer.add_person_phone(int(code), str(user.get("phone") or "")) \
            if mobile_key(user.get("phone")) else None
    except Exception as exc:  # noqa: BLE001 - never stops the customer; tried again later
        logger.warning("person details not written: %s", type(exc).__name__)
        db.update_user_details(int(user["id"]), details_sync=1)
        return False
    if (result is not None and not result.committed) or (phone is not None and not phone.done):
        db.update_user_details(int(user["id"]), details_sync=1)   # writes are off here
        return False
    db.update_user_details(int(user["id"]), details_sync=0)
    if result is not None:
        db.audit("system:details", "person_fields_filled",
                 f"user id={user['id']} person_code={code} fields={sorted(result.filled)}")
    if phone is not None and phone.added:
        db.audit("system:details", "person_phone_added",
                 f"user id={user['id']} person_code={code}")
    if phone is not None and phone.other_person is not None:
        # this number is another person's: left alone, staff decide
        db.audit("system:details", "person_phone_taken",
                 f"user id={user['id']} person_code={code} other={phone.other_person}")
    return True


def person_candidates(reader, first: str, last: str, national_code: str,
                      limit: int = 5) -> dict:
    """v2.18.0, the approval dialog: who in «سازه حساب» this customer may be.
    ``national_code``: the one person with this code (auto-link). ``candidates``: same or
    similar names, best first, with the last two digits of a phone to tell people apart."""
    persons = reader.persons_for_matching()
    wanted = name_match.normalize_code(national_code)
    by_code = None
    found: list[dict] = []
    new_letters = set(name_match.normalize_name(f"{first} {last}").compact)
    for person in persons:
        name = " ".join(part for part in (person.get("first_name"), person.get("last_name"))
                        if part).strip()
        if wanted and name_match.normalize_code(person.get("national_code")) == wanted:
            by_code = {"code": int(person["code"]), "name": name}
            continue
        # most rows share few letters with this name: not worth comparing one by one
        letters = set(name_match.normalize_name(name).compact)
        if not letters or len(new_letters & letters) / min(len(letters), len(new_letters) or 1) < 0.6:
            continue
        result = name_match.match(first, last, national_code, name, person.get("national_code"))
        if result.verdict != name_match.DIFFERENT:
            found.append({"code": int(person["code"]), "name": name, "score": result.score,
                          "verdict": result.verdict})
    found.sort(key=lambda item: (-item["score"], item["code"]))
    found = found[:limit]
    tails = reader.person_phone_tails([item["code"] for item in found]
                                      + ([by_code["code"]] if by_code else []))
    for item in found:
        item["phone_tail"] = tails.get(item["code"], "")
    if by_code:
        by_code["phone_tail"] = tails.get(by_code["code"], "")
    return {"national_code": by_code, "candidates": found}


def national_code_person(reader, national_code: str) -> int | None:
    """The person holding this national code, if any (it links instead of creating)."""
    wanted = name_match.normalize_code(national_code)
    if not wanted:
        return None
    for person in reader.persons_for_matching():
        if name_match.normalize_code(person.get("national_code")) == wanted:
            return int(person["code"])
    return None


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
