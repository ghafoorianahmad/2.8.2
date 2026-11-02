"""v2.17.0: status codes, write later, Sazeh stage, closing requests, staff notifications."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import control, staff_alerts, tracking
from app.accounting_writer import AccountingWriter
from app.config import Settings

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff
from .test_v250 import FakeConn, order_req


def _receipt(client) -> int:
    order_id = order_req(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    return order_id


# ---- #1 6808 is valid; #2 nothing is written without a valid code ------------------------------
def test_6808_is_a_valid_status():
    conn = FakeConn()
    writer = AccountingWriter(
        Settings(accounting_database="hesab5 t", accounting_allowed_databases=("hesab5 t",),
                 accounting_write_databases=("hesab5 t",), accounting_status_code=6808),
        connection_factory=lambda: conn)
    assert writer.write_order(1, 7001, [(101, 1.0, 100.0)]).status_code == 6808
    assert control.validate_settings({"ACCOUNTING_STATUS_CODE": "6808"}) == {}
    assert not hasattr(control, "INVALID_STATUS_CODES")


@pytest.mark.parametrize("code", [None, 0, -5])
def test_receipt_without_a_valid_code_is_accepted_but_never_written(client, reader, writer, db,
                                                                    settings, code):
    seed_products(reader)
    register_and_approve(client)
    settings.accounting_status_code = code
    calls = []
    writer.write_order = lambda *a, **k: calls.append(a)
    order_id = _receipt(client)
    r = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["accounting_pending"] is True
    assert body["accounting_order_no"] is None
    assert calls == []                                       # the writer was never even asked
    kinds = [e["kind"] for e in db.list_events(0, 100)]
    assert "payment_approved" in kinds                       # the customer is told


def _waiting_order(client, reader, settings) -> int:
    seed_products(reader)
    register_and_approve(client)
    settings.accounting_status_code = None
    order_id = _receipt(client)
    client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    return order_id


def test_write_later_needs_the_code_then_writes(client, reader, db, settings):
    order_id = _waiting_order(client, reader, settings)
    url = f"/admin/orders/{order_id}/write-accounting"
    refused = client.post(url, headers=h("admin"))
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Order status code is not configured"
    settings.accounting_status_code = 6808
    done = client.post(url, headers=h("admin"))
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "written" and body["accounting_pending"] is False
    assert body["accounting_order_no"]
    # only once
    assert client.post(url, headers=h("admin")).status_code == 409


def test_write_later_has_its_own_tick(client, reader, db, settings):
    order_id = _waiting_order(client, reader, settings)
    settings.accounting_status_code = 6808
    sales = staff(db, "operator", "mina")
    assert client.post(f"/admin/orders/{order_id}/write-accounting",
                       headers=sales).status_code == 403
    db.update_staff(db.get_staff_by_username("mina")["id"], perm_grant="acctwrite.edit")
    assert client.post(f"/admin/orders/{order_id}/write-accounting",
                       headers=sales).status_code in (200, 404)     # 404: another's work


def test_a_sent_order_can_still_be_written(client, reader, db, settings):
    order_id = _waiting_order(client, reader, settings)
    assert client.post(f"/admin/orders/{order_id}/ship", json={},
                       headers=h("admin")).status_code == 200
    settings.accounting_status_code = 6808
    assert client.post(f"/admin/orders/{order_id}/write-accounting",
                       headers=h("admin")).json()["status"] == "written"


def test_a_waiting_order_is_not_archived(client, reader, db, settings):
    order_id = _waiting_order(client, reader, settings)
    client.post(f"/admin/orders/{order_id}/ship", json={}, headers=h("admin"))
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
    assert db.archive_closed(future)["orders"] == 0


def test_a_dry_run_is_still_not_reported_as_written(client, reader, writer, db):
    seed_products(reader)
    register_and_approve(client)
    from app.accounting_writer import WriteResult

    writer.write_order = lambda *a, **k: WriteResult(
        accounting_order_no=5, person_code=7001, datelp="", mablp=1, status_code=6808,
        usercode=1, anbarcode=1, rolled_back=True)
    order_id = _receipt(client)
    body = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin")).json()
    assert body["status"] == "receipt_uploaded" and body["accounting_pending"] is False


# ---- #7 status codes and the stage -----------------------------------------------------------------
@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ACCOUNTING_STATUS_CODE=\n", encoding="utf-8")
    monkeypatch.setattr(control.STATE, "env_file", path)
    monkeypatch.delenv("ACCOUNTING_STATUS_CODE", raising=False)
    monkeypatch.delenv("ACCOUNTING_HANDOVER_STATUS_CODE", raising=False)
    return path


def test_status_codes_take_effect_at_once(client, reader, db, settings, env_file):
    order_id = _waiting_order(client, reader, settings)
    r = client.put("/admin/shop-rules/status-codes", headers=staff(db, "super_admin", "boss"),
                   json={"order_status": "6808", "handover_status": "6914"})
    assert r.status_code == 200 and r.json()["configured"] is True
    assert settings.accounting_status_code == 6808 and settings.accounting_handover_code == 6914
    text = env_file.read_text(encoding="utf-8")
    assert "ACCOUNTING_STATUS_CODE=6808" in text and "ACCOUNTING_HANDOVER_STATUS_CODE=6914" in text
    assert client.post(f"/admin/orders/{order_id}/write-accounting",
                       headers=h("admin")).status_code == 200


@pytest.mark.parametrize("order,handover", [("0", ""), ("", ""), ("x", ""), ("6808", "6808"),
                                            ("6808", "abc")])
def test_status_codes_validation(client, db, settings, env_file, order, handover):
    r = client.put("/admin/shop-rules/status-codes", headers=staff(db, "super_admin", "boss"),
                   json={"order_status": order, "handover_status": handover})
    assert r.status_code == 422


def test_handover_code_is_optional(client, db, settings, env_file):
    r = client.put("/admin/shop-rules/status-codes", headers=staff(db, "super_admin", "boss"),
                   json={"order_status": "6808"})
    assert r.status_code == 200 and settings.accounting_handover_code is None


def test_status_codes_have_their_own_ticks(client, db, settings, env_file):
    mina = staff(db, "operator", "mina")
    assert client.get("/admin/shop-rules", headers=mina).status_code == 403
    assert client.put("/admin/shop-rules/status-codes", headers=mina,
                      json={"order_status": "1"}).status_code == 403
    db.update_staff(db.get_staff_by_username("mina")["id"], perm_grant="status_codes.view")
    seen = client.get("/admin/shop-rules", headers=mina).json()
    assert "status_codes" in seen and "work_hours" not in seen and "auto_invoice" not in seen
    assert client.put("/admin/shop-rules/status-codes", headers=mina,
                      json={"order_status": "1"}).status_code == 403
    assert client.get("/admin/server/settings", headers=mina).status_code == 403


@pytest.mark.parametrize("info,stage", [
    (None, "missing"),
    ({"status": 6808, "ordered": 2, "invoiced": 0}, "approved"),
    ({"status": 6914, "ordered": 2, "invoiced": 0}, "handover"),
    ({"status": 6914, "ordered": 2, "invoiced": 1}, "partial"),
    ({"status": 6808, "ordered": 2, "invoiced": 2}, "invoiced"),
    ({"status": 99, "ordered": 2, "invoiced": 0}, "other"),
    ({"status": None, "ordered": 2, "invoiced": 0}, "other"),
])
def test_order_stage(info, stage):
    assert tracking.order_stage(info, 6808, 6914) == stage


def test_no_handover_code_means_other():
    assert tracking.order_stage({"status": 6914, "ordered": 1, "invoiced": 0}, 6808, None) == "other"


def test_orders_carry_their_stage(client, reader, settings):
    seed_products(reader)
    register_and_approve(client)
    settings.accounting_handover_code = 6914
    order_id = _receipt(client)
    codlp = client.post(f"/admin/orders/{order_id}/approve-payment",
                        headers=h("admin")).json()["accounting_order_no"]
    reader.order_stages = lambda codes: {codlp: {"status": 6914, "ordered": 1, "invoiced": 0}}
    rows = client.get("/admin/orders", params={"status": "written"}, headers=h("admin")).json()
    assert rows[0]["sazeh_stage"] == "handover" and rows[0]["sazeh_status"] == 6914
    one = client.get(f"/admin/orders/{order_id}", headers=h("admin")).json()
    assert one["sazeh_stage"] == "handover"


def test_accounting_down_leaves_the_stage_empty(client, reader, settings):
    seed_products(reader)
    register_and_approve(client)
    order_id = _receipt(client)
    client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))

    def down(_codes):
        raise OSError("down")

    reader.order_stages = down
    rows = client.get("/admin/orders", params={"status": "written"}, headers=h("admin"))
    assert rows.status_code == 200 and rows.json()[0]["sazeh_stage"] is None


def test_stage_sql_is_read_only_and_parameterized():
    from app.accounting_reader import AccountingReader

    calls = []

    class Cursor:
        description = [("Codlp",), ("Status",), ("OrderedQty",), ("InvoicedQty",)]

        def fetchall(self):
            return [(7, 6808, 2.0, 0.0)]

    class Conn:
        def execute(self, sql, *params):
            calls.append((sql, params))
            return Cursor()

        def close(self):
            pass

    reader = AccountingReader(Settings(accounting_database="hesab5"),
                              connection_factory=lambda: Conn())
    assert reader.order_stages([7]) == {7: {"status": 6808, "ordered": 2.0, "invoiced": 0.0}}
    sql, params = calls[0]
    assert sql.lstrip().upper().startswith("SELECT") and "IN (?)" in sql and "7" not in sql
    assert params == ([7],)


# ---- #8 automatic invoices: a place only ---------------------------------------------------------
def test_auto_invoice_is_off_and_unavailable(client, db):
    boss = staff(db, "super_admin", "boss")
    assert client.get("/admin/shop-rules", headers=boss).json()["auto_invoice"] == {
        "enabled": False, "available": False}


# ---- #3 no request is closed silently ---------------------------------------------------------------
def _request(client) -> int:
    return client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                               "text": "گوشی"}, headers=h("bot")).json()["id"]


def test_closing_needs_a_message(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    req = _request(client)
    url = f"/admin/item-requests/{req}/status"
    r = client.post(url, json={"status": "done"}, headers=h("admin"))
    assert r.status_code == 409 and r.json()["detail"] == "Send the customer a message first"
    message = db.add_item_request_message(req, "موجود شد", "x")
    assert client.post(url, json={"status": "done"}, headers=h("admin")).status_code == 200
    assert message["status"] == "pending"


def test_a_failed_message_does_not_count(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    req = _request(client)
    message = db.add_item_request_message(req, "موجود شد", "x")
    db.set_item_request_message_result(message["id"], False, "blocked")
    assert client.post(f"/admin/item-requests/{req}/status", json={"status": "done"},
                       headers=h("admin")).status_code == 409


def test_other_statuses_need_no_message(client, reader):
    seed_products(reader)
    register_and_approve(client)
    req = _request(client)
    assert client.post(f"/admin/item-requests/{req}/status", json={"status": "seen"},
                       headers=h("admin")).status_code == 200


# ---- #12 staff notifications -----------------------------------------------------------------------
#: A Sunday (2026-11-01) in Tehran; every test sets its own hour.
def at(hour: int, minute: int = 0, day: int = 1) -> datetime:
    from app.sales import TEHRAN

    return datetime(2026, 11, day, hour, minute, tzinfo=TEHRAN).astimezone(timezone.utc)


def test_default_hours():
    hours = staff_alerts.WorkHours()
    assert (hours.start, hours.end) == ("09:00", "21:00")
    assert hours.is_open(at(9).astimezone(staff_alerts.TEHRAN))
    assert hours.is_open(at(20, 59).astimezone(staff_alerts.TEHRAN))
    assert not hours.is_open(at(21).astimezone(staff_alerts.TEHRAN))
    assert not hours.is_open(at(8, 59).astimezone(staff_alerts.TEHRAN))
    friday = datetime(2026, 11, 6, 12, tzinfo=staff_alerts.TEHRAN)
    assert friday.weekday() == 4 and not hours.is_open(friday)


def test_next_start_skips_days_off():
    hours = staff_alerts.WorkHours()
    thursday_night = datetime(2026, 11, 5, 22, tzinfo=staff_alerts.TEHRAN)
    assert hours.next_start(thursday_night).date().isoformat() == "2026-11-07"    # after Friday


@pytest.fixture
def linked(db):
    """Two linked staff members; bale only for the second."""
    for name, mobile in (("mina", "09120000001"), ("reza", "09120000002")):
        row = db.create_staff(name, name, "operator", "x")
        db.update_staff(row["id"], mobile=mobile)
        db.set_staff_link(row["id"], "bale", {"mina": "c1", "reza": "c2"}[name])
    return db


def _new_order(db, created_at: str | None = None) -> int:
    user = db.register_user("bale", f"u{datetime.now().timestamp()}", "x", "09123334444")
    order = db.create_order(user["id"], 3, 1000.0, None, [(1, "گوشی", 1.0, 1000.0, None, None,
                                                           None, None)], accounting_db="hesab5")
    if created_at:
        db._conn.execute("UPDATE orders SET created_at=?, updated_at=? WHERE id=?",
                         (created_at, created_at, order["id"]))
        db._conn.commit()
    return int(order["id"])


def test_new_order_goes_to_all_linked_and_repeats_every_5_minutes(linked):
    db = linked
    order_id = _new_order(db, at(9, 30).isoformat())
    db.set_state(f"{staff_alerts.SUMMARY_KEY}:bale", "2026-11-01")
    first = staff_alerts.due(db, "bale", at(10))
    assert len(first) == 1 and first[0]["target_id"] == order_id
    assert first[0]["kind"] == "order" and first[0]["chats"] == ["c1", "c2"]
    assert first[0]["repeat"] == 0
    assert staff_alerts.due(db, "bale", at(10, 4)) == []
    again = staff_alerts.due(db, "bale", at(10, 5))
    assert len(again) == 1 and again[0]["repeat"] == 1


def test_a_claimed_order_stops_repeating(linked):
    db = linked
    order_id = _new_order(db, at(9, 30).isoformat())
    db.set_state(f"{staff_alerts.SUMMARY_KEY}:bale", "2026-11-01")
    assert staff_alerts.due(db, "bale", at(10))
    db.claim("order", order_id, db.get_staff_by_username("mina")["id"])
    assert staff_alerts.due(db, "bale", at(11)) == []


def test_a_receipt_is_news_of_its_own(linked):
    db = linked
    order_id = _new_order(db, at(9, 30).isoformat())
    db.set_state(f"{staff_alerts.SUMMARY_KEY}:bale", "2026-11-01")
    staff_alerts.due(db, "bale", at(10))
    db.set_order_status(order_id, "receipt_uploaded")
    items = staff_alerts.due(db, "bale", at(10, 1))      # no 5-minute wait for a new kind
    assert [i["kind"] for i in items] == ["receipt"]


def test_outside_hours_nothing_then_one_summary_at_opening(linked):
    db = linked
    for _ in range(2):
        _new_order(db, at(22, 0, day=1).isoformat())
    assert staff_alerts.due(db, "bale", at(23, 0, day=1)) == []
    assert staff_alerts.due(db, "bale", at(8, 0, day=2)) == []
    opening = staff_alerts.due(db, "bale", at(9, 0, day=2))
    assert [i["kind"] for i in opening] == ["summary"]
    assert opening[0]["counts"]["order"] == 2 and opening[0]["chats"] == ["c1", "c2"]
    assert staff_alerts.due(db, "bale", at(9, 1, day=2)) == []          # once a day


def test_summary_is_per_platform(linked):
    db = linked
    db.set_staff_link(db.get_staff_by_username("mina")["id"], "telegram", "t1")
    _new_order(db, at(22, 0, day=1).isoformat())
    assert staff_alerts.due(db, "bale", at(9, 0, day=2))[0]["chats"] == ["c1", "c2"]
    assert staff_alerts.due(db, "telegram", at(9, 0, day=2))[0]["chats"] == ["t1"]


def test_no_linked_staff_nothing_is_recorded(db):
    _new_order(db, at(9, 30).isoformat())
    assert staff_alerts.due(db, "bale", at(10)) == []
    assert db.staff_alert_log("bale") == {}


def test_notices_follow_the_ticks(linked):
    db = linked
    mina = db.get_staff_by_username("mina")
    db.update_staff(mina["id"], perm_revoke="staff_alerts.view")
    reza = db.get_staff_by_username("reza")
    db.update_staff(reza["id"], perm_revoke="orders.view")
    _new_order(db, at(9, 30).isoformat())
    db.set_state(f"{staff_alerts.SUMMARY_KEY}:bale", "2026-11-01")
    assert staff_alerts.due(db, "bale", at(10)) == []


def test_manual_off_holds_until_the_next_working_period(linked):
    db = linked
    _new_order(db, at(9, 30).isoformat())
    db.set_state(f"{staff_alerts.SUMMARY_KEY}:bale", "2026-11-01")
    current = staff_alerts.apply_action(db, "off", "boss", at(10))
    assert current.active is False and current.override == "off"
    assert staff_alerts.due(db, "bale", at(12)) == []
    assert staff_alerts.state(db, at(20)).active is False
    assert staff_alerts.state(db, at(9, 0, day=2)).active is True       # next opening
    assert staff_alerts.state(db, at(9, 0, day=2)).override == ""


def test_manual_off_before_opening_ends_at_that_opening(db):
    staff_alerts.apply_action(db, "off", "boss", at(8))
    assert staff_alerts.state(db, at(8, 30)).active is False
    assert staff_alerts.state(db, at(9)).active is True


def test_holiday_skips_todays_period_even_before_opening(db):
    staff_alerts.apply_action(db, "holiday", "boss", at(8))
    assert staff_alerts.state(db, at(10)).active is False
    assert staff_alerts.state(db, at(20)).active is False
    assert staff_alerts.state(db, at(9, 0, day=2)).active is True


def test_manual_on_outside_hours_until_the_next_period(linked):
    db = linked
    order_id = _new_order(db, at(22, 0).isoformat())
    assert staff_alerts.due(db, "bale", at(23)) == []
    current = staff_alerts.apply_action(db, "on", "boss", at(23))
    assert current.active is True and current.override == "on"
    items = staff_alerts.due(db, "bale", at(23))
    assert [i["target_id"] for i in items] == [order_id]
    assert staff_alerts.state(db, at(9, 0, day=2)).override == ""


def test_manual_on_during_hours_goes_back_to_the_schedule(db):
    staff_alerts.apply_action(db, "off", "boss", at(10))
    current = staff_alerts.apply_action(db, "on", "boss", at(11))
    assert current.active is True and current.override == ""
    assert staff_alerts.state(db, at(22)).active is False               # no repeats at night


def test_days_are_editable(client, db):
    boss = staff(db, "super_admin", "boss")
    r = client.put("/admin/shop-rules/work-hours", headers=boss,
                   json={"start": "10:00", "end": "18:30", "days": [0, 1, 4]})
    assert r.status_code == 200 and r.json()["days"] == [0, 1, 4]
    hours = staff_alerts.load_hours(db)
    assert hours.is_open(datetime(2026, 11, 6, 12, tzinfo=staff_alerts.TEHRAN))
    assert not hours.is_open(datetime(2026, 11, 1, 12, tzinfo=staff_alerts.TEHRAN))


@pytest.mark.parametrize("body", [{"start": "25:00", "end": "26:00", "days": []},
                                  {"start": "18:00", "end": "09:00", "days": [0]},
                                  {"start": "09:00", "end": "18:00", "days": [9]}])
def test_bad_hours_are_refused(client, db, body):
    boss = staff(db, "super_admin", "boss")
    assert client.put("/admin/shop-rules/work-hours", headers=boss, json=body).status_code == 422


def test_dashboard_buttons_have_their_own_tick(client, db):
    mina = staff(db, "operator", "mina")
    assert client.get("/admin/staff-alerts/state", headers=mina).status_code == 200
    assert client.post("/admin/staff-alerts/action", headers=mina,
                       json={"action": "off"}).status_code == 403
    db.update_staff(db.get_staff_by_username("mina")["id"], perm_grant="staff_alerts.edit")
    r = client.post("/admin/staff-alerts/action", headers=mina, json={"action": "off"})
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.post("/admin/staff-alerts/action", headers=mina,
                       json={"action": "bogus"}).status_code == 422


def test_mobile_and_link(client, db):
    boss = staff(db, "super_admin", "boss")
    mina = client.post("/admin/staff", headers=boss, json={
        "username": "mina", "password": "abcd1234", "role": "operator",
        "mobile": "۰۹۱۲۰۰۰۰۰۰۱"}).json()
    assert mina["mobile"] == "09120000001" and mina["linked_platforms"] == []
    # a stranger's number links nothing
    r = client.post("/staff-links", headers=h("bot"), json={
        "platform": "bale", "chat_id": "9", "phone": "09129999999"})
    assert r.json() == {"linked": False}
    r = client.post("/staff-links", headers=h("bot"), json={
        "platform": "bale", "chat_id": "55", "phone": "+989120000001"})
    assert r.json()["linked"] is True
    row = client.get("/admin/staff", headers=boss).json()
    assert [u for u in row if u["username"] == "mina"][0]["linked_platforms"] == ["bale"]
    # a new number needs a new link
    client.patch(f"/admin/staff/{mina['id']}", headers=boss, json={"mobile": "09120000009"})
    assert db.staff_links_of(mina["id"]) == []
    # unlink
    client.post("/staff-links", headers=h("bot"), json={
        "platform": "bale", "chat_id": "55", "phone": "09120000009"})
    assert client.post(f"/admin/staff/{mina['id']}/unlink", headers=boss).status_code == 200
    assert db.staff_links_of(mina["id"]) == []


def test_mobile_rules(client, db):
    boss = staff(db, "super_admin", "boss")
    first = client.post("/admin/staff", headers=boss, json={
        "username": "mina", "password": "abcd1234", "mobile": "09120000001"})
    assert first.status_code == 201
    assert client.post("/admin/staff", headers=boss, json={
        "username": "reza", "password": "abcd1234", "mobile": "12"}).status_code == 422
    assert client.post("/admin/staff", headers=boss, json={
        "username": "sara", "password": "abcd1234", "mobile": "09120000001"}).status_code == 409


def test_an_inactive_member_is_not_linked_and_gets_nothing(db):
    row = db.create_staff("mina", "", "operator", "x")
    db.update_staff(row["id"], mobile="09120000001", active=0)
    assert staff_alerts.link(db, "bale", "1", "09120000001") is None
    db.update_staff(row["id"], active=1)
    assert staff_alerts.link(db, "bale", "1", "09120000001") is not None
    db.update_staff(row["id"], active=0)
    assert db.staff_links_for_platform("bale") == []


def test_claim_from_the_bot(client, reader, db):
    row = db.create_staff("mina", "", "operator", "x")
    db.set_staff_link(row["id"], "bale", "c1")
    other = db.create_staff("reza", "", "operator", "x")
    db.set_staff_link(other["id"], "bale", "c2")
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    body = {"platform": "bale", "target_type": "order", "target_id": order_id}
    # the bot's service key only
    assert client.post("/admin/staff-alerts/claim", headers=staff(db, "super_admin", "boss"),
                       json={**body, "chat_id": "c1"}).status_code == 403
    assert client.post("/admin/staff-alerts/claim", headers=h("admin"),
                       json={**body, "chat_id": "nobody"}).json() == {
        "claimed": False, "reason": "not_linked"}
    assert client.post("/admin/staff-alerts/claim", headers=h("admin"),
                       json={**body, "chat_id": "c1"}).json() == {"claimed": True}
    assert db.get_order(order_id)["owner_id"] == row["id"]
    assert client.post("/admin/staff-alerts/claim", headers=h("admin"),
                       json={**body, "chat_id": "c2"}).json() == {
        "claimed": False, "reason": "taken"}
    assert client.post("/admin/staff-alerts/claim", headers=h("admin"),
                       json={**body, "chat_id": "c1"}).json() == {"claimed": True}   # again: fine


def test_claim_needs_the_tick(client, reader, db):
    row = db.create_staff("mina", "", "operator", "x")
    db.update_staff(row["id"], perm_revoke="claim.edit")
    db.set_staff_link(row["id"], "bale", "c1")
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    r = client.post("/admin/staff-alerts/claim", headers=h("admin"), json={
        "platform": "bale", "chat_id": "c1", "target_type": "order", "target_id": order_id})
    assert r.json() == {"claimed": False, "reason": "not_allowed"}


def test_claim_in_shopadmin_stops_the_repeats(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    mina = staff(db, "operator", "mina")
    order_id = order_req(client).json()["id"]
    assert client.post(f"/admin/orders/{order_id}/claim", headers=mina).status_code == 200
    assert db.unclaimed_orders() == []
    req = _request(client)
    assert client.post(f"/admin/item-requests/{req}/claim", headers=mina).status_code == 200
    assert db.unclaimed_requests() == []


def test_due_is_for_the_bots_only(client, db):
    assert client.get("/admin/staff-alerts/due", params={"platform": "bale"},
                      headers=staff(db, "super_admin", "boss")).status_code == 403
    assert client.get("/admin/staff-alerts/due", params={"platform": "bale"},
                      headers=h("admin")).json() == {"items": []}
