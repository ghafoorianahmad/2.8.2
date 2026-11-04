"""v2.18.0: shifts, the Sazeh name, required details, one person with several numbers."""
from __future__ import annotations

from datetime import datetime

import pytest

from app import customer_details as cd
from app import staff_alerts
from app.accounting_writer import AccountingWriter, PersonPhone

from .conftest import h, register_and_approve, seed_products
from .test_v2170 import staff


def register(client, platform="bale", chat_id="111", phone="09120000000", name="مشتری"):
    return client.post("/users/register", headers=h("bot"), json={
        "platform": platform, "chat_id": chat_id, "name": name, "phone": phone})


CODE = "0084575948"
ADDRESS = "مشهد، خیابان نمونه، پلاک ۱"
FULL = {"first_name": "علی", "last_name": "رضایی", "national_code": CODE, "address": ADDRESS}


def _at(hour: int, minute: int = 0) -> datetime:
    # 2026-11-03 is a Tuesday (a working day by default)
    return datetime(2026, 11, 3, hour, minute, tzinfo=staff_alerts.TEHRAN)


# ---- shifts -------------------------------------------------------------------------------------
def test_a_day_with_a_midday_break():
    hours = staff_alerts.WorkHours(shifts=(("16:00", "21:00"), ("09:00", "13:00")))
    assert (hours.start, hours.end) == ("09:00", "21:00")
    assert hours.is_open(_at(9)) and hours.is_open(_at(12, 59))
    assert not hours.is_open(_at(13)) and not hours.is_open(_at(15, 59))
    assert hours.is_open(_at(16)) and not hours.is_open(_at(21))
    assert hours.next_start(_at(14)) == _at(16)
    assert hours.shift_start(_at(17)) == _at(16) and hours.shift_start(_at(14)) is None


def test_old_saved_hours_are_one_shift(db):
    db.set_state(staff_alerts.HOURS_KEY, '{"start": "08:00", "end": "18:00", "days": [0, 1]}', "t")
    hours = staff_alerts.load_hours(db)
    assert hours.shifts == (("08:00", "18:00"),)
    assert hours.as_dict()["shifts"] == [{"start": "08:00", "end": "18:00"}]


@pytest.mark.parametrize("shifts,problem", [
    ([("09:00", "13:00"), ("12:00", "21:00")], "overlap"),
    ([("13:00", "09:00")], "after"),
    ([("25:00", "26:00")], "look like"),
])
def test_bad_shifts(shifts, problem):
    assert problem in staff_alerts.hours_problem("", "", [0], shifts)


def test_shifts_through_the_api(client, db):
    boss = staff(db, "super_admin", "boss")
    body = {"days": [0, 1], "shifts": [{"start": "09:00", "end": "13:00"},
                                       {"start": "16:00", "end": "21:00"}]}
    saved = client.put("/admin/shop-rules/work-hours", json=body, headers=boss).json()
    assert saved["shifts"] == body["shifts"]
    rules = client.get("/admin/shop-rules", headers=boss).json()
    assert rules["work_hours"]["shifts"] == body["shifts"]
    # the single start and end of 2.17 still work
    old = client.put("/admin/shop-rules/work-hours", headers=boss,
                     json={"start": "10:00", "end": "20:00", "days": [0]}).json()
    assert old["shifts"] == [{"start": "10:00", "end": "20:00"}]


def test_each_shift_sends_its_own_summary(db):
    hours = staff_alerts.WorkHours(shifts=(("09:00", "13:00"), ("16:00", "21:00")))
    first = hours.shift_start(_at(10))
    second = hours.shift_start(_at(17))
    assert first == hours.period_start(_at(10).date()) and second != first


# ---- the person's name --------------------------------------------------------------------------
def test_customer_lists_show_the_sazeh_name(client, reader):
    seed_products(reader)
    reader.person_name_map = {7001: "رضا کریمی"}
    user_id = register_and_approve(client)
    rows = client.get("/admin/users", headers=h("admin")).json()
    assert rows[0]["person_name"] == "رضا کریمی"
    one = client.get(f"/admin/users/{user_id}", headers=h("admin")).json()
    assert one["person_name"] == "رضا کریمی"


def test_customer_list_works_when_names_cannot_be_read(client, reader):
    seed_products(reader)
    register_and_approve(client)

    def down(_codes):
        raise OSError("down")

    reader.person_names = down
    assert client.get("/admin/users", headers=h("admin")).json()[0]["person_name"] is None


# ---- required details ---------------------------------------------------------------------------
def test_form_payload_is_checked_again_on_the_server(client):
    register(client)
    r = client.post("/users/bale/111/details", headers=h("bot"),
                    json={**FULL, "first_name": "Ali"})
    assert r.status_code == 422 and "حروف فارسی" in r.json()["detail"]
    r = client.post("/users/bale/111/details", headers=h("bot"),
                    json={**FULL, "national_code": "0084575949"})
    assert r.status_code == 422 and "رقم کنترل" in r.json()["detail"]
    r = client.post("/users/bale/111/details", headers=h("bot"),
                    json={**FULL, "address": "Valiasr street 12"})
    assert r.status_code == 422 and "نشانی" in r.json()["detail"]
    r = client.post("/users/bale/111/details", json=FULL, headers=h("bot"))
    assert r.status_code == 200 and r.json()["missing"] == []


@pytest.mark.parametrize("missing", ["first_name", "last_name", "national_code", "address"])
def test_no_new_person_without_all_four(client, writer, missing):
    user_id = register(client).json()["id"]
    body = {k: v for k, v in FULL.items() if k != missing}
    r = client.post(f"/admin/users/{user_id}/approve", json=body, headers=h("admin"))
    assert r.status_code == 422 and writer.calls == []


def test_names_are_persian_letters_only_when_approving(client, writer):
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={**FULL, "first_name": "Ali"},
                    headers=h("admin"))
    assert r.status_code == 422 and "حروف فارسی" in r.json()["detail"]


def _waiting_order(client, reader, details: dict):
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", headers=h("bot"), json={
        "platform": "bale", "chat_id": "111", "items": [{"kala_code": 101, "qty": 1}]}).json()
    reader.person_detail_map = {7001: details}
    client.post(f"/orders/{order['id']}/receipt", headers=h("bot"), json={
        "platform": "bale", "chat_id": "111", "file_ref": "x", "note": ""})
    return order


def test_an_order_is_not_written_until_the_details_are_complete(client, reader, writer, db):
    order = _waiting_order(client, reader, {"first_name": "علی", "last_name": "رضایی",
                                            "national_code": "", "address": ""})
    db._conn.execute("UPDATE orders SET status='receipt_uploaded' WHERE id=?", (order["id"],))
    db._conn.commit()
    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.status_code == 200 and r.json()["accounting_pending"] is True
    assert not [call for call in writer.calls if call[0] == order["id"]]
    # «ثبت در حسابداری» says why
    r = client.post(f"/admin/orders/{order['id']}/write-accounting", headers=h("admin"))
    assert r.status_code == 409 and r.json()["detail"] == cd.DETAILS_INCOMPLETE
    # staff type what the customer told them
    r = client.put("/admin/users/1/details", headers=h("admin"),
                   json={"national_code": CODE, "address": ADDRESS})
    assert r.status_code == 200
    r = client.post(f"/admin/orders/{order['id']}/write-accounting", headers=h("admin"))
    assert r.status_code == 200 and r.json()["status"] == "written"
    assert [call[0] for call in writer.calls if call[0] == order["id"]] == [order["id"]]


def test_unknown_details_stop_the_write_too(client, reader, writer, db):
    order = _waiting_order(client, reader, {})

    def down(_code):
        raise OSError("no grant")

    reader.person_details = down
    db._conn.execute("UPDATE orders SET status='receipt_uploaded' WHERE id=?", (order["id"],))
    db._conn.commit()
    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.json()["accounting_pending"] is True and writer.calls == []


def test_details_are_not_logged(client, db):
    user_id = register(client).json()["id"]
    client.put(f"/admin/users/{user_id}/details", json=FULL, headers=h("admin"))
    rows = db._conn.execute("SELECT detail FROM audit_log").fetchall()
    assert not any(CODE in str(tuple(row)) for row in rows)


# ---- one person, several numbers ---------------------------------------------------------------
PEOPLE = [
    {"code": 501, "first_name": "علي", "last_name": "رضايي", "national_code": ""},
    {"code": 502, "first_name": "علی", "last_name": "رضائی", "national_code": "0499370899"},
    {"code": 503, "first_name": "حسن", "last_name": "کریمی", "national_code": CODE},
    {"code": 504, "first_name": "زهرا", "last_name": "محمدی", "national_code": ""},
]


def test_candidates_by_name_and_national_code(client, reader, db):
    user_id = register(client).json()["id"]
    db.update_user_details(user_id, first_name="علی", last_name="رضایی")
    reader.matching_persons = PEOPLE
    reader.phone_tails = {501: "47"}
    found = client.get(f"/admin/users/{user_id}/person-candidates", headers=h("admin")).json()
    assert found["national_code"] is None
    best = found["candidates"][0]
    assert (best["code"], best["verdict"], best["phone_tail"]) == (501, "same", "47")
    assert 504 not in [c["code"] for c in found["candidates"]]


def test_a_national_code_on_another_person_is_found(client, reader, db):
    user_id = register(client).json()["id"]
    db.update_user_details(user_id, first_name="علی", last_name="رضایی", national_code=CODE)
    reader.matching_persons = PEOPLE
    reader.phone_tails = {503: "12"}
    found = client.get(f"/admin/users/{user_id}/person-candidates", headers=h("admin")).json()
    assert found["national_code"] == {"code": 503, "name": "حسن کریمی", "phone_tail": "12"}


def test_national_code_links_instead_of_creating(client, reader, writer):
    reader.person_codes = {503}
    reader.matching_persons = PEOPLE
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json=FULL, headers=h("admin"))
    assert r.status_code == 200 and r.json()["person_code"] == 503
    assert not [call for call in writer.calls if call[0] == "create_person"]
    assert writer.phone_calls == [(503, "09120000000")]


def test_linking_adds_the_new_number_to_the_person(client, reader, writer):
    reader.person_codes = {501}
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={"person_code": 501},
                    headers=h("admin"))
    assert r.status_code == 200
    assert writer.phone_calls == [(501, "09120000000")]


def test_same_name_gets_no_added_mark(client, writer, reader):
    # two people with one name stay two: nothing is added to tell them apart
    reader.matching_persons = PEOPLE
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", headers=h("admin"), json={
        **FULL, "national_code": "0067749828"})
    assert r.status_code == 200
    assert ("create_person", "علی", "رضایی", "09120000000") in writer.calls


def test_a_failed_number_is_tried_again_later(client, reader, writer, db):
    reader.person_codes = {501}
    writer.committed = False
    user_id = register(client).json()["id"]
    client.post(f"/admin/users/{user_id}/approve", json={"person_code": 501}, headers=h("admin"))
    assert db.get_user_by_id(user_id)["details_sync"] == 1
    writer.committed = True
    assert cd.sync_waiting(db, writer) == 1
    assert db.get_user_by_id(user_id)["details_sync"] == 0


class _Cursor:
    rowcount = 1

    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else (0,)


class _Conn:
    """Answers the phone lookup; records every statement."""

    def __init__(self, owners=()):
        self.owners = list(owners)
        self.sql: list[tuple] = []
        self.autocommit = True
        self.committed = 0
        self.rolled_back = 0

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        if "sp_getapplock" in sql:
            return _Cursor([(0,)])
        if "DetailTBL d" in sql:
            return _Cursor([(o,) for o in self.owners])
        if "INFORMATION_SCHEMA" in sql:
            return _Cursor([("telephons", 200)])
        return _Cursor()

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


def _writer(settings, conn, *, allowed=True) -> AccountingWriter:
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    writer.write_allowed = lambda: allowed
    writer._db = lambda: "[hesab5 t]"
    return writer


def _writes(conn) -> list[str]:
    return [sql for sql, _ in conn.sql if sql.startswith(("INSERT", "UPDATE", "DELETE"))]


def test_writer_adds_a_new_number(settings):
    conn = _Conn()
    result = _writer(settings, conn).add_person_phone(501, "09121112233", dry_run=False)
    assert isinstance(result, PersonPhone) and result.added and result.done
    writes = _writes(conn)
    assert len(writes) == 2 and "DetailTBL" in writes[0] and "telephons" in writes[1]
    assert conn.committed == 1
    params = dict((sql, p) for sql, p in conn.sql)[writes[0]]
    assert (501, 3, "09121112233", 0, 0) == tuple(params)


def test_writer_leaves_a_known_number_alone(settings):
    conn = _Conn(owners=[501])
    result = _writer(settings, conn).add_person_phone(501, "09121112233", dry_run=False)
    assert result.done and not result.added and _writes(conn) == []


def test_writer_never_takes_another_persons_number(settings):
    conn = _Conn(owners=[900])
    result = _writer(settings, conn).add_person_phone(501, "09121112233", dry_run=False)
    assert result.other_person == 900 and not result.added and _writes(conn) == []


def test_a_dry_run_sends_nothing(settings):
    conn = _Conn()
    result = _writer(settings, conn, allowed=False).add_person_phone(501, "09121112233")
    assert not result.done and _writes(conn) == []
