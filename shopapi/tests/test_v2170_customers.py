"""v2.17.0 #9 and #10: the customer's details and the address of an order."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import customer_details as cd
from app.accounting_reader import AccountingReader
from app.accounting_writer import AccountingWriter
from app.config import Settings

from .conftest import h, register_and_approve, seed_products
from .test_v250 import order_req


def _details(client, chat="111"):
    return client.get(f"/users/bale/{chat}/details", headers=h("bot"))


def _save(client, chat="111", **fields):
    return client.post(f"/users/bale/{chat}/details", json=fields, headers=h("bot"))


def _register(client, chat="222", phone="09124445555"):
    return client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": chat, "name": "نام پروفایل", "phone": phone}).json()


# ---- the check digit ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", ["0499370899", "1234567891", "0012345679"])
def test_good_national_codes(code):
    assert cd.national_code_ok(code)


@pytest.mark.parametrize("code", ["0499370898", "1111111111", "0000000000", "123456789",
                                  "12345678901", "abcdefghij", ""])
def test_bad_national_codes(code):
    assert not cd.national_code_ok(code)


def test_values_are_cleaned():
    values, problem = cd.clean_values({"first_name": "  علي ", "last_name": "رضايي",
                                       "national_code": "۰۴۹۹-۳۷۰۸۹۹", "address": " تهران   ولیعصر "})
    assert problem is None
    assert values == {"first_name": "علی", "last_name": "رضایی",
                      "national_code": "0499370899", "address": "تهران ولیعصر"}


@pytest.mark.parametrize("field,value,problem", [
    ("first_name", "ع", cd.INVALID_NAME),
    ("first_name", "علی۱۲", cd.INVALID_NAME),
    ("last_name", "!!!", cd.INVALID_NAME),
    ("national_code", "1111111111", cd.INVALID_NATIONAL_CODE),
    ("address", "کم", cd.INVALID_ADDRESS),
    ("address", "ا" * 501, cd.INVALID_ADDRESS),
])
def test_bad_values(field, value, problem):
    assert cd.clean_values({field: value})[1] == problem


# ---- asking -------------------------------------------------------------------------------------
def test_a_new_customer_is_asked_everything(client):
    _register(client)
    view = _details(client, "222").json()
    assert view["known"] is True and view["asked"] is False
    assert view["missing"] == ["first_name", "last_name", "national_code", "address"]


def test_a_linked_customer_is_asked_only_what_sazeh_lacks(client, reader):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {"first_name": "علی", "last_name": "رضایی",
                                          "national_code": "", "address": ""}
    assert _details(client).json()["missing"] == ["national_code", "address"]


def test_accounting_down_nothing_is_asked(client, reader):
    seed_products(reader)
    register_and_approve(client)

    def down(_code):
        raise OSError("down")

    reader.person_details = down
    view = _details(client).json()
    assert view["known"] is False and view["missing"] == []


def test_the_view_never_carries_the_name_or_the_code(client, reader):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {"first_name": "علی", "last_name": "رضایی",
                                          "national_code": "0499370899", "address": "تهران"}
    view = _details(client).json()
    assert set(view) == {"missing", "address", "asked", "known"}
    assert "علی" not in str(view) and "0499370899" not in str(view)


def test_bad_answer_is_refused_and_nothing_stored(client, db):
    user = _register(client)
    r = _save(client, "222", national_code="1111111111", first_name="علی")
    assert r.status_code == 422 and r.json()["detail"] == cd.INVALID_NATIONAL_CODE
    assert db.get_user_by_id(user["id"])["first_name"] == ""


def test_answers_are_saved_and_never_logged(client, db):
    user = _register(client)
    assert _save(client, "222", first_name="علی", last_name="رضایی").status_code == 200
    row = db.get_user_by_id(user["id"])
    assert row["first_name"] == "علی" and row["name"] == "علی رضایی"
    logged = str(db.list_audit(50))
    assert "علی" not in logged and "fields=['first_name', 'last_name']" in logged


def test_finished_is_remembered(client, db):
    _register(client)
    assert _save(client, "222", finished=True).json()["asked"] is True
    assert _details(client, "222").json()["asked"] is True


def test_a_rejected_customer_cannot_save(client, db):
    user = _register(client)
    db.set_user_status(user["id"], "rejected")
    assert _save(client, "222", first_name="علی").status_code == 404


# ---- into «سازه حساب» -----------------------------------------------------------------------------
def test_new_customer_all_goes_into_the_new_person(client, db, writer):
    user = _register(client)
    _save(client, "222", first_name="علی", last_name="رضایی", national_code="0499370899",
          address="تهران، ولیعصر، پلاک 1")
    r = client.post(f"/admin/users/{user['id']}/approve", json={}, headers=h("admin"))
    assert r.status_code == 200
    assert ("create_person", "علی", "رضایی", "09124445555") in writer.calls
    assert writer.created_with == {"address": "تهران، ولیعصر، پلاک 1",
                                   "national_code": "0499370899"}


def test_staff_can_still_correct_the_name_when_creating(client, db, writer):
    user = _register(client)
    _save(client, "222", first_name="علی", last_name="رضایی")
    client.post(f"/admin/users/{user['id']}/approve", headers=h("admin"),
                json={"first_name": "علیرضا", "last_name": "رضایی"})
    assert ("create_person", "علیرضا", "رضایی", "09124445555") in writer.calls
    assert db.get_user_by_id(user["id"])["name"] == "علیرضا رضایی"


def test_a_linked_customer_fills_the_person_at_once(client, db, writer, reader):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {"first_name": "علی", "last_name": "", "national_code": "",
                                          "address": ""}
    _save(client, national_code="0499370899")
    calls = [c for c in writer.calls if c[0] == "fill_person_empty"]
    assert calls and calls[-1][1] == 7001 and calls[-1][2]["national_code"] == "0499370899"
    assert db.get_user_by_platform("bale", "111")["details_sync"] == 0


def test_writes_off_keeps_it_for_later(client, db, writer, reader):
    seed_products(reader)
    register_and_approve(client)
    writer.committed = False
    _save(client, national_code="0499370899")
    row = db.get_user_by_platform("bale", "111")
    assert row["details_sync"] == 1 and row["national_code"] == "0499370899"
    writer.committed = True
    assert cd.sync_waiting(db, writer) == 1
    assert db.get_user_by_platform("bale", "111")["details_sync"] == 0


def test_a_writer_failure_never_reaches_the_customer(client, db, writer, reader):
    seed_products(reader)
    register_and_approve(client)

    def boom(*_a, **_k):
        raise OSError("permission denied")

    writer.fill_person_empty = boom
    assert _save(client, national_code="0499370899").status_code == 200
    assert db.get_user_by_platform("bale", "111")["details_sync"] == 1


def test_staff_approval_links_and_fills(client, db, writer, reader):
    user = _register(client)
    _save(client, "222", address="تهران، ولیعصر، پلاک 1")
    reader.person_codes.add(7777)
    r = client.post(f"/admin/users/{user['id']}/approve", json={"person_code": 7777},
                    headers=h("admin"))
    assert r.status_code == 200
    calls = [c for c in writer.calls if c[0] == "fill_person_empty"]
    assert calls[-1][1] == 7777


# ---- the writer: never overwrites -------------------------------------------------------------------
class PersonConn:
    """Records SQL; every UPDATE changes one row unless the test says otherwise."""

    def __init__(self, rowcount=1, sizes=None):
        self.sql = []
        self.autocommit = True
        self.rowcount = rowcount
        self.sizes = {"fname": 50, "Name": 80, "Codemelli": 10, "Addres2": 20} \
            if sizes is None else sizes
        self.committed = False

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        self.last = sql
        return self

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return list(self.sizes.items())

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _writer(conn, *, allowed=True):
    settings = Settings(accounting_database="hesab5 t",
                        accounting_allowed_databases=("hesab5 t",) if allowed else (),
                        accounting_write_databases=("hesab5 t",) if allowed else ())
    return AccountingWriter(settings, connection_factory=lambda: conn)


def _updates(conn):
    return [(s, p) for s, p in conn.sql if s.startswith("UPDATE")]


VALUES = {"first_name": "علی", "last_name": "رضایی", "national_code": "0499370899",
          "address": "تهران، ولیعصر، پلاک 1"}


def test_every_update_has_the_empty_condition():
    conn = PersonConn()
    result = _writer(conn).fill_person_empty(7001, VALUES)
    assert result.committed and conn.committed
    updates = _updates(conn)
    assert len(updates) == 4
    for sql, _params in updates:
        assert "WHERE Code = ?" in sql and "ISNULL" in sql and "= ''" in sql
    address = next(s for s, _p in updates if "SET Addres2" in s)
    assert "ISNULL(Addres2" in address and "ISNULL(Addres," in address     # either holds one
    assert result.filled == ["fname", "Name", "Codemelli", "Addres2"]


def _columns(conn):
    return [s.split(" SET ")[1].split()[0] for s, _p in _updates(conn)]


def test_only_our_four_columns_can_be_written():
    conn = PersonConn()
    _writer(conn).fill_person_empty(7001, {"telephons": "x", "memo1": "y", "first_name": "علی"})
    assert _columns(conn) == ["fname"]


def test_nothing_filled_when_the_field_is_not_empty():
    conn = PersonConn(rowcount=0)
    result = _writer(conn).fill_person_empty(7001, VALUES)
    assert result.committed and result.filled == []


def test_values_are_parameters_and_cut_to_the_column():
    conn = PersonConn()
    _writer(conn).fill_person_empty(7001, VALUES)
    sql, params = next((s, p) for s, p in _updates(conn) if "SET Addres2" in s)
    assert "تهران" not in sql
    assert params == ("تهران، ولیعصر، پلاک 1"[:20], 7001)


def test_a_column_of_unknown_size_is_left_alone():
    conn = PersonConn(sizes={"fname": 50})
    result = _writer(conn).fill_person_empty(7001, VALUES)
    assert _columns(conn) == ["fname"] and result.committed


def test_dry_run_sends_no_update():
    conn = PersonConn()
    result = _writer(conn, allowed=False).fill_person_empty(7001, VALUES)
    assert conn.sql == [] and not result.committed


def test_create_person_writes_the_national_code_and_address():
    from .test_writer import FakeConn

    conn = FakeConn()
    writer = AccountingWriter(
        Settings(accounting_database="hesab5 t", accounting_allowed_databases=("hesab5 t",),
                 accounting_write_databases=("hesab5 t",)),
        connection_factory=lambda: conn)
    writer.create_person("علی", "رضایی", "09124445555", address="تهران، ولیعصر",
                         national_code="0499370899")
    insert = next((s, p) for s, p in conn.executed if "name_mo" in s and s.startswith("INSERT"))
    columns = [c.strip() for c in insert[0].split("(", 1)[1].split(")", 1)[0].split(",")]
    values = dict(zip(columns, insert[1]))
    assert values["Codemelli"] == "0499370899" and values["Addres2"] == "تهران، ولیعصر"
    assert values["Addres"] == ""


def test_reader_person_details_prefers_addres2():
    class Cursor:
        description = [("fname",), ("Name",), ("Codemelli",), ("Addres",), ("Addres2",)]

        def __init__(self, row):
            self.row = row

        def fetchall(self):
            return [self.row]

    class Conn:
        def __init__(self, row):
            self.row = row
            self.params = None

        def execute(self, sql, *params):
            self.sql, self.params = sql, params
            return Cursor(self.row)

        def close(self):
            pass

    conn = Conn((" علی ", "رضایی", None, "قدیمی", ""))
    reader = AccountingReader(Settings(accounting_database="hesab5"),
                              connection_factory=lambda: conn)
    assert reader.person_details(7) == {"first_name": "علی", "last_name": "رضایی",
                                        "national_code": "", "address": "قدیمی"}
    assert conn.params == (7,) and "7" not in conn.sql


# ---- #10 the address of an order ------------------------------------------------------------------
def _order(client, chat="111", **extra):
    seed = {"platform": "bale", "chat_id": chat, "items": [{"kala_code": 101, "qty": 1}], **extra}
    return client.post("/orders", json=seed, headers=h("bot"))


def test_new_customer_first_address_becomes_saved(client, reader, db, writer):
    seed_products(reader)
    _register(client, "222")
    r = _order(client, "222", ship_address="تهران، ولیعصر، پلاک 1")
    assert r.status_code == 201 and r.json()["ship_address"] == "تهران، ولیعصر، پلاک 1"
    assert db.get_user_by_platform("bale", "222")["address"] == "تهران، ولیعصر، پلاک 1"
    assert _details(client, "222").json()["address"] == "تهران، ولیعصر، پلاک 1"


def test_new_address_stays_on_its_order(client, reader, db):
    seed_products(reader)
    _register(client, "222")
    _order(client, "222", ship_address="تهران، ولیعصر، پلاک 1")
    second = _order(client, "222", ship_address="مشهد، احمدآباد، پلاک 2")
    assert second.json()["ship_address"] == "مشهد، احمدآباد، پلاک 2"
    assert db.get_user_by_platform("bale", "222")["address"] == "تهران، ولیعصر، پلاک 1"


def test_existing_with_a_sazeh_address_is_not_overwritten(client, reader, db, writer):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {"first_name": "", "last_name": "", "national_code": "",
                                          "address": "آدرس سازه"}
    assert _details(client).json()["address"] == "آدرس سازه"
    _order(client, ship_address="آدرس تازهٔ این سفارش")
    assert db.get_user_by_platform("bale", "111")["address"] == ""
    assert not [c for c in writer.calls if c[0] == "fill_person_empty"]


def test_existing_without_address_first_one_goes_to_sazeh(client, reader, db, writer):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {"first_name": "علی", "last_name": "رضایی",
                                          "national_code": "", "address": ""}
    _order(client, ship_address="تهران، ولیعصر، پلاک 1")
    calls = [c for c in writer.calls if c[0] == "fill_person_empty"]
    assert calls and calls[-1][2]["address"] == "تهران، ولیعصر، پلاک 1"


def test_an_accounting_problem_never_loses_the_order(client, reader, db, writer):
    seed_products(reader)
    register_and_approve(client)

    def boom(*_a, **_k):
        raise OSError("down")

    writer.fill_person_empty = boom
    assert _order(client, ship_address="تهران، ولیعصر، پلاک 1").status_code == 201


def test_bad_address_is_refused_and_no_order_made(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    r = _order(client, ship_address="کم")
    assert r.status_code == 422 and r.json()["detail"] == cd.INVALID_ADDRESS
    assert db.list_orders("awaiting_payment") == []


def test_check_only_saves_nothing(client, reader, db):
    seed_products(reader)
    _register(client, "222")
    client.post("/orders?check=true", headers=h("bot"), json={
        "platform": "bale", "chat_id": "222", "items": [{"kala_code": 101, "qty": 1}],
        "ship_address": "تهران، ولیعصر، پلاک 1"})
    assert db.get_user_by_platform("bale", "222")["address"] == ""


def test_address_is_shown_to_staff(client, reader):
    seed_products(reader)
    register_and_approve(client)
    order_id = _order(client, ship_address="تهران، ولیعصر، پلاک 1").json()["id"]
    one = client.get(f"/admin/orders/{order_id}", headers=h("admin")).json()
    assert one["ship_address"] == "تهران، ولیعصر، پلاک 1"
    rows = client.get("/admin/orders", params={"status": "awaiting_payment"},
                      headers=h("admin")).json()
    assert rows[0]["ship_address"] == "تهران، ولیعصر، پلاک 1"


def test_order_address_later_only_by_its_customer(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    url = f"/orders/{order_id}/address"
    body = {"platform": "bale", "chat_id": "999", "address": "تهران، ولیعصر"}
    assert client.put(url, json=body, headers=h("bot")).status_code == 404
    body["chat_id"] = "111"
    r = client.put(url, json=body, headers=h("bot"))
    assert r.status_code == 200 and r.json()["ship_address"] == "تهران، ولیعصر"
    db.set_order_status(order_id, "cancelled")
    assert client.put(url, json=body, headers=h("bot")).status_code == 409


# ---- #9 the first receipt -----------------------------------------------------------------------------
def _receipt(client) -> int:
    order_id = order_req(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    return order_id


def test_first_receipt_only_once(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    first = _receipt(client)
    assert client.get(f"/admin/orders/{first}", headers=h("admin")).json()["first_receipt"] is True
    r = client.post(f"/admin/orders/{first}/approve-payment", headers=h("admin"),
                    json={"payer_checked": True})
    assert r.status_code == 200 and r.json()["status"] == "written"
    second = _receipt(client)
    assert client.get(f"/admin/orders/{second}", headers=h("admin")).json()["first_receipt"] is False


def test_a_different_payer_is_recorded_when_asked(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = _receipt(client)
    r = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"), json={
        "payer_checked": True, "record_payer": True, "payer_name": "  حسین   احمدی "})
    body = r.json()
    assert body["status"] == "written" and body["payer_name"] == "حسین احمدی"
    row = db.get_user_by_platform("bale", "111")
    assert row["payer_name"] == "حسین احمدی" and row["payer_asked"] == 1
    assert row["name"] != "حسین احمدی"                # the customer's own name stays


def test_keeping_the_name_records_nothing_and_blocks_nothing(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = _receipt(client)
    r = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"), json={
        "payer_checked": True, "record_payer": False, "payer_name": "حسین احمدی"})
    assert r.json()["status"] == "written" and r.json()["payer_name"] == ""
    assert db.get_user_by_platform("bale", "111")["payer_name"] == ""


def test_approving_without_a_body_still_works(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = _receipt(client)
    assert client.post(f"/admin/orders/{order_id}/approve-payment",
                       headers=h("admin")).json()["status"] == "written"
    assert db.get_user_by_platform("bale", "111")["payer_asked"] == 0   # not asked yet


# ---- SQL files ------------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]


def _sql(name: str) -> str:
    return (ROOT / "sql" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["grant_shop_app.sql", "upgrade_2_17_0.sql"])
def test_sql_grants_what_the_code_reads_and_writes(name):
    text = _sql(name)
    for column in ("fname", "Name", "Codemelli", "Addres", "Addres2"):
        assert column in text
    assert "GRANT UPDATE ON dbo.name_mo" in text
    update = next(line for line in text.splitlines() if line.startswith("GRANT UPDATE ON dbo.name_mo"))
    assert "Addres," not in update                    # read, never written


@pytest.mark.parametrize("name", ["grant_shop_app.sql", "upgrade_2_17_0.sql"])
def test_sql_never_grants_tabagheh_bandi_or_delete(name):
    for line in _sql(name).splitlines():
        if line.startswith("GRANT"):
            assert "dbo.TabaghehBandi" not in line and "DELETE" not in line, line


def test_upgrade_is_for_production_and_changes_no_schema():
    text = _sql("upgrade_2_17_0.sql")
    assert "USE [hesab5];" in text
    for word in ("ALTER TABLE", "CREATE TABLE", "CREATE INDEX", "CREATE TRIGGER", "DROP "):
        assert word not in text
    assert "SELECT p.state_desc" in text and "FROM dbo.name_mo" not in text   # no rows are read


def test_the_setup_uses_the_same_script():
    from app.grant_access import GRANT_SQL

    assert "Codemelli, Addres, Addres2" in GRANT_SQL
    assert "UPDATE ON dbo.name_mo (codetaf, telephons, fname, Name, Codemelli, Addres2)" in GRANT_SQL
