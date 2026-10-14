"""v2.5.0: receipt deadline, sales windows, sales buttons, Status config, DB name
per order, duplicate order numbers, Persian SQL errors, DB allowlist, dry run."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pyodbc
import pytest

from app import order_timeout, sales, sql_errors, tracking
from app.accounting_writer import AccountingWriter, WriteResult
from app.config import Settings
from app.pricelist.repo import PriceListRepo

from .conftest import h, register_and_approve, seed_products
from .test_writer import FakeConn

TEHRAN = timezone(timedelta(hours=3, minutes=30))


def tehran(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TEHRAN)


# 2026-10-14 is a Wednesday; 2026-10-16 is a Friday.
WED = (2026, 10, 14)
FRI = (2026, 10, 16)


def add_list(db, posted: datetime, sha: str = "a") -> int:
    repo = PriceListRepo(db)
    list_id = repo.insert_list(list_date="1405/07/22", sha256=sha, source="telegram",
                               source_ref="t.me/x/1", posted_at=posted.isoformat(),
                               status="held", reason="", rows=[])
    repo.activate(list_id)
    return list_id


def kinds(db):
    return [e["kind"] for e in db.list_events(0, 1000)]


@pytest.fixture
def win(settings):
    settings.sales_windows_enabled = True
    return settings


# ---- sales windows ----------------------------------------------------------------
def test_morning_list_opens_sales_until_13_30(db, win):
    add_list(db, tehran(*WED, 9, 40))
    state = sales.compute(db, win, tehran(*WED, 10, 0))
    assert state.open and state.reason == sales.REASON_LIST and state.list_slot == "morning"
    assert state.until == tehran(*WED, 13, 30).astimezone(timezone.utc).isoformat(timespec="seconds")
    late = sales.compute(db, win, tehran(*WED, 13, 30))
    assert not late.open and late.reason == sales.REASON_LIST_EXPIRED
    assert "به‌روز نشده" in late.message_fa


def test_evening_list_opens_sales_until_20_30(db, win):
    add_list(db, tehran(*WED, 15, 5))
    assert sales.compute(db, win, tehran(*WED, 20, 29)).open
    assert sales.compute(db, win, tehran(*WED, 20, 29)).list_slot == "evening"
    assert not sales.compute(db, win, tehran(*WED, 20, 30)).open


def test_list_after_evening_close_or_from_yesterday_keeps_sales_closed(db, win):
    add_list(db, tehran(*WED, 21, 0))
    assert not sales.compute(db, win, tehran(*WED, 21, 5)).open
    add_list(db, tehran(*WED, 10, 0), sha="b")   # yesterday's morning list, next day
    state = sales.compute(db, win, tehran(2026, 10, 15, 10, 0))
    assert not state.open and state.reason == sales.REASON_LIST_EXPIRED


def test_friday_and_no_list_are_closed(db, win):
    assert sales.compute(db, win, tehran(*WED, 10, 0)).reason == sales.REASON_NO_LIST
    add_list(db, tehran(*FRI, 9, 0))
    state = sales.compute(db, win, tehran(*FRI, 10, 0))
    assert not state.open and state.reason == sales.REASON_WEEKDAY


def test_holiday_closes_until_next_morning(db, win):
    add_list(db, tehran(*WED, 9, 0))
    now = tehran(*WED, 10, 0)
    state = sales.set_override(db, win, "holiday", "staff:ali", now)
    assert not state.open and state.reason == sales.REASON_HOLIDAY
    assert not sales.compute(db, win, tehran(*WED, 11, 0)).open
    add_list(db, tehran(*WED, 15, 0), sha="b")       # a new list does not end the holiday
    assert not sales.compute(db, win, tehran(*WED, 16, 0)).open
    add_list(db, tehran(2026, 10, 15, 9, 0), sha="c")
    assert sales.compute(db, win, tehran(2026, 10, 15, 9, 30)).open


def test_manual_close_lasts_until_a_new_list(db, win):
    add_list(db, tehran(*WED, 9, 0))
    sales.set_override(db, win, "close", "staff:ali", tehran(*WED, 10, 0))
    assert sales.compute(db, win, tehran(*WED, 12, 0)).reason == sales.REASON_MANUAL_CLOSE
    add_list(db, tehran(*WED, 15, 0), sha="b")
    assert sales.compute(db, win, tehran(*WED, 15, 30)).reason == sales.REASON_LIST


def test_manual_open_lasts_until_the_next_transition(db, win):
    add_list(db, tehran(*WED, 9, 0))
    # after the morning window: open until 20:30
    state = sales.set_override(db, win, "open", "staff:ali", tehran(*WED, 14, 0))
    assert state.open and state.reason == sales.REASON_MANUAL_OPEN
    assert sales.compute(db, win, tehran(*WED, 20, 0)).open
    assert not sales.compute(db, win, tehran(*WED, 20, 30)).open      # closing time
    # opened again, then a new list arrives: back to the normal rule
    sales.set_override(db, win, "open", "staff:ali", tehran(*WED, 20, 40))
    assert sales.compute(db, win, tehran(*WED, 21, 0)).open
    add_list(db, tehran(*WED, 21, 30), sha="late")
    assert not sales.compute(db, win, tehran(*WED, 21, 31)).open
    # Friday: a manual open still wins, and it can be closed again at any time
    sales.set_override(db, win, "open", "staff:ali", tehran(*FRI, 9, 0))
    assert sales.compute(db, win, tehran(*FRI, 9, 5)).open
    sales.set_override(db, win, "close", "staff:ali", tehran(*FRI, 9, 10))
    assert not sales.compute(db, win, tehran(*FRI, 9, 11)).open


def test_override_is_stored_audited_and_raises_events(db, win):
    sales.set_override(db, win, "holiday", "staff:ali", tehran(*WED, 10, 0))
    stored = json.loads(db.get_state(sales.OVERRIDE_KEY))
    assert stored["mode"] == "holiday" and stored["by"] == "staff:ali"
    assert any(a["action"] == "sales_holiday" and a["actor"] == "staff:ali"
               for a in db.list_audit(50))
    assert "sales_holiday" in kinds(db)


def test_transitions_raise_one_event_each(db, win):
    add_list(db, tehran(*WED, 9, 0))
    sales.record_transition(db, win, tehran(*WED, 9, 30))   # first run: position only
    assert "sales_opened" not in kinds(db)
    sales.record_transition(db, win, tehran(*WED, 13, 31))
    sales.record_transition(db, win, tehran(*WED, 13, 45))
    assert kinds(db).count("sales_closed") == 1


def test_tehran_time_has_a_fallback_without_tzdata():
    assert sales.TEHRAN.utcoffset(datetime(2026, 7, 1)) == timedelta(hours=3, minutes=30)
    assert sales.parse_hhmm("x", sales.time(13, 30)) == sales.time(13, 30)


# ---- sales state over the API ------------------------------------------------------
def order_req(client, chat_id="111"):
    return client.post("/orders", json={"platform": "bale", "chat_id": chat_id,
                                        "items": [{"kala_code": 101, "qty": 1}]},
                       headers=h("bot"))


def test_orders_are_refused_while_sales_are_closed(client, reader, db, win):
    seed_products(reader)
    register_and_approve(client)
    state = client.get("/shop/state", headers=h("bot")).json()
    assert state["closed"] is True and state["sales_open"] is False
    assert state["reason"] == sales.REASON_NO_LIST and state["message_fa"]
    r = order_req(client)
    assert r.status_code == 409 and r.json()["detail"].startswith("Sales are closed")
    # «باز کردن فروش» in ShopAdmin
    r = client.post("/admin/sales/action", json={"action": "open"}, headers=h("admin"))
    assert r.status_code == 200 and r.json()["sales_open"] is True
    assert order_req(client).status_code == 201
    r = client.post("/admin/sales/action", json={"action": "close"}, headers=h("admin"))
    assert r.json()["closed"] is True and order_req(client).status_code == 409
    assert client.post("/admin/sales/action", json={"action": "holiday"},
                       headers=h("bot")).status_code == 403
    assert client.post("/admin/sales/action", json={"action": "x"},
                       headers=h("admin")).status_code == 422


def test_a_retry_of_an_order_placed_before_closing_gets_the_same_order(client, reader, db, win):
    seed_products(reader)
    register_and_approve(client)
    client.post("/admin/sales/action", json={"action": "open"}, headers=h("admin"))
    body = {"platform": "bale", "chat_id": "111", "items": [{"kala_code": 101, "qty": 1}]}
    first = client.post("/orders", json=body, headers={**h("bot"), "Idempotency-Key": "k" * 16})
    client.post("/admin/sales/action", json={"action": "close"}, headers=h("admin"))
    again = client.post("/orders", json=body, headers={**h("bot"), "Idempotency-Key": "k" * 16})
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


# ---- receipt deadline ----------------------------------------------------------------
def test_order_gets_a_30_minute_receipt_deadline_and_the_db_name(client, reader, settings):
    seed_products(reader)
    register_and_approve(client)
    body = order_req(client).json()
    created = datetime.fromisoformat(body["created_at"])
    deadline = datetime.fromisoformat(body["reserve_until"])
    assert timedelta(minutes=29) <= deadline - created <= timedelta(minutes=31)
    assert body["accounting_db"] == "hesab5"
    assert client.get("/admin/system-info", headers=h("admin")).json()[
        "receipt_deadline_minutes"] == 30


def _expire(db, order_id):
    db._conn.execute("UPDATE orders SET reserve_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                     (order_id,))
    db._conn.commit()


def test_overdue_order_is_cancelled_locally_and_frees_stock(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    assert db.pending_reservations() == {101: 1.0}
    _expire(db, order_id)
    assert order_timeout.cancel_overdue(db) == [order_id]
    got = db.get_order(order_id)
    assert got["status"] == "cancelled" and got["cancel_reason"] == "receipt_timeout"
    assert db.pending_reservations() == {}
    assert "order_auto_cancelled" in kinds(db)
    assert order_timeout.cancel_overdue(db) == []          # once


def test_receipt_after_the_deadline_is_refused(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    _expire(db, order_id)
    r = client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                    json={"receipt_ref": "f1"}, headers=h("bot"))
    assert r.status_code == 409 and "deadline" in r.json()["detail"]
    assert db.get_order(order_id)["status"] == "cancelled"
    r = client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                    json={"receipt_ref": "f1"}, headers=h("bot"))
    assert "deadline" in r.json()["detail"]


def test_an_order_already_in_accounting_is_never_cancelled_only_alerted(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    db._conn.execute("UPDATE orders SET accounting_order_no=555 WHERE id=?", (order_id,))
    db._conn.commit()
    _expire(db, order_id)
    assert order_timeout.cancel_overdue(db) == []
    assert db.get_order(order_id)["status"] == "awaiting_payment"
    order_timeout.cancel_overdue(db)
    assert kinds(db).count(order_timeout.EVENT_NEEDS_ADMIN) == 1


def test_orders_waiting_for_review_are_not_cancelled(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id = order_req(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    _expire(db, order_id)
    assert order_timeout.cancel_overdue(db) == []
    assert db.get_order(order_id)["status"] == "receipt_uploaded"


# ---- DB name per order / invoices -----------------------------------------------
def _written(client):
    order_id = order_req(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    body = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin")).json()
    return order_id, body


def test_invoices_are_never_reported_against_another_database(client, reader, db):
    seed_products(reader)
    register_and_approve(client)
    order_id, body = _written(client)
    assert body["status"] == "written" and body["accounting_db"] == "hesab5"
    codlp = body["accounting_order_no"]
    reader.invoices = {codlp: {"ordered": 1, "invoiced": 1}}
    reader.invoice_nums = {codlp: ["2672"]}
    # connected to another fiscal-year database: the same Codlp is another order there
    assert tracking.sync_invoices(db, reader, "hesab6") == 0
    assert db.get_order(order_id)["invoice_state"] is None
    db._conn.execute("UPDATE orders SET accounting_db=NULL WHERE id=?", (order_id,))
    db._conn.commit()
    assert tracking.sync_invoices(db, reader, "hesab5") == 0         # unknown DB: never
    db._conn.execute("UPDATE orders SET accounting_db='HESAB5' WHERE id=?", (order_id,))
    db._conn.commit()
    assert tracking.sync_invoices(db, reader, "hesab5") == 1
    params = {"platform": "bale", "chat_id": "111"}
    assert client.get(f"/orders/{order_id}", params=params,
                      headers=h("admin")).json()["invoice_numbers"] == ["2672"]


def test_invoice_numbers_hidden_for_an_order_of_another_database(client, reader, db, settings):
    seed_products(reader)
    register_and_approve(client)
    order_id, body = _written(client)
    reader.invoices = {body["accounting_order_no"]: {"ordered": 1, "invoiced": 1}}
    reader.invoice_nums = {body["accounting_order_no"]: ["2672"]}
    tracking.sync_invoices(db, reader, "hesab5")
    settings.accounting_database = "hesab6"
    assert client.get(f"/orders/{order_id}", headers=h("admin")).json()["invoice_numbers"] == []


# ---- duplicate accounting order number --------------------------------------------
def test_duplicate_order_number_after_commit_alerts_the_admin(client, reader, writer, db):
    seed_products(reader)
    register_and_approve(client)
    original = writer.write_order

    def dup(*a, **kw):
        res = original(*a, **kw)
        res.codlp_rows_after_commit = 2
        return res

    writer.write_order = dup
    order_id, body = _written(client)
    assert body["status"] == "written"                       # ours stays; nothing deleted
    assert "accounting_duplicate_order" in kinds(db)


def test_duplicate_inside_the_transaction_is_rolled_back_and_alerted(client, reader, writer, db):
    from app.accounting_writer import DuplicateOrderNumber

    seed_products(reader)
    register_and_approve(client)

    def boom(*a, **kw):
        raise DuplicateOrderNumber(1001, 2)

    writer.write_order = boom
    order_id, body = _written(client)
    assert "Duplicate accounting order number" in body["detail"]
    assert db.get_order(order_id)["status"] == "receipt_uploaded"
    assert "accounting_duplicate_order" in kinds(db)


def test_real_writer_rechecks_the_number_after_commit():
    class DupAfter(FakeConn):
        def __init__(self):
            super().__init__(max_codlp=5)
            self.counts = 0

        def fetchone(self):
            sql, _ = self.executed[-1]
            if "COUNT(*)" in sql.upper():
                self.counts += 1
                return (1 if self.counts == 1 else 2,)
            return super().fetchone()

    conn = DupAfter()
    writer = AccountingWriter(Settings(accounting_database="hesab5 t", accounting_status_code=0),
                              connection_factory=lambda: conn)
    res = writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert res.committed and res.codlp_rows_after_commit == 2 and res.duplicate_after_commit
    assert res.database == "hesab5 t"
    assert not any(sql.strip().upper().startswith("DELETE") for sql, _ in conn.executed)


# ---- Status as config --------------------------------------------------------------------
@pytest.mark.parametrize("status_code", [None, 6808])
def test_commit_needs_a_valid_configured_status(status_code):
    from app.accounting_writer import AccountingConfigError

    conn = FakeConn()
    writer = AccountingWriter(Settings(accounting_database="hesab5 t",
                                       accounting_status_code=status_code),
                              connection_factory=lambda: conn)
    with pytest.raises(AccountingConfigError):
        writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert conn.executed == []
    # a dry run still works and inserts nothing
    res = writer.write_order(1, 7001, [(101, 1.0, 100.0)], dry_run=True)
    assert res.rolled_back and not any(s.strip().upper().startswith("INSERT")
                                       for s, _ in conn.executed)


def test_status_from_env(monkeypatch):
    monkeypatch.setenv("ACCOUNTING_STATUS_CODE", "0")
    assert Settings.from_env().status_code_problem() is None
    monkeypatch.setenv("ACCOUNTING_STATUS_CODE", "6808")
    assert "6808" in Settings.from_env().status_code_problem()


def test_approve_payment_without_status_is_a_clear_409(client, reader, writer, db, settings):
    from app.accounting_writer import AccountingConfigError

    seed_products(reader)
    register_and_approve(client)

    def refuse(*a, **kw):
        raise AccountingConfigError("ACCOUNTING_STATUS_CODE is not set")

    writer.write_order = refuse
    order_id, body = _written(client)
    assert body["detail"] == "Order status code is not configured"
    assert db.get_order(order_id)["status"] == "receipt_uploaded"


# ---- DB allowlist / test mode -------------------------------------------------------------
def test_production_writes_need_the_database_on_the_allowlist():
    base = dict(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                accounting_write_enabled=True)
    assert Settings(**base).write_allowed() is False                       # not allowlisted
    assert Settings(**base, accounting_allowed_databases=("hesab5",)).write_allowed() is True
    assert Settings(**{**base, "accounting_write_enabled": False},
                    accounting_allowed_databases=("hesab5",)).write_allowed() is False
    assert Settings(**{**base, "accounting_server": "PROD"},
                    accounting_allowed_databases=("hesab5",)).write_allowed() is False


def test_test_mode_only_for_allowlisted_test_databases(monkeypatch):
    assert Settings(accounting_database="hesab5 t").is_test_db()
    assert Settings(accounting_database="HESAB5 T ").is_test_db()
    assert not Settings(accounting_database="hesab5").is_test_db()
    assert not Settings(accounting_database="hesab5 t",
                        accounting_test_databases=("shop_test",)).is_test_db()
    monkeypatch.setenv("ACCOUNTING_DATABASE", "shop_test")
    monkeypatch.setenv("ACCOUNTING_TEST_DATABASES", "shop_test, other")
    assert Settings.from_env().is_test_db()


def test_dry_run_never_inserts_and_a_forced_real_write_is_refused():
    from app.accounting_writer import AccountingWriteRefused

    conn = FakeConn()
    writer = AccountingWriter(Settings(accounting_database="hesab5", accounting_status_code=0),
                              connection_factory=lambda: conn)
    res = writer.write_order(1, 7001, [(101, 1.0, 100.0)])
    assert res.rolled_back and not res.committed
    assert not any(s.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for s, _ in conn.executed)
    with pytest.raises(AccountingWriteRefused):
        writer.write_order(1, 7001, [(101, 1.0, 100.0)], dry_run=False)


def test_system_info_reports_the_write_guards(client, settings):
    info = client.get("/admin/system-info", headers=h("admin")).json()
    assert info["accounting_database"] == "hesab5"
    assert info["accounting_write_enabled"] is False and info["database_allowlisted"] is False
    assert info["status_code_configured"] is True


# ---- Persian SQL errors ---------------------------------------------------------------------
@pytest.mark.parametrize("args, code, word", [
    (("28000", "[Microsoft][ODBC Driver 17 for SQL Server][SQL Server]Login failed for user "
               "'shopbot'. (18456) (SQLDriverConnect)"), "18456", "گذرواژه"),
    (("42000", "[Microsoft][ODBC Driver 17 for SQL Server][SQL Server]Cannot open database "
               "\"hesab9\" requested by the login. (4060) (SQLDriverConnect)"), "4060",
     "ACCOUNTING_DATABASE"),
    (("08001", "[Microsoft][ODBC Driver 17 for SQL Server]Named Pipes Provider: Could not "
               "open a connection to SQL Server [53]. (53)"), "53", "پیدا نشد"),
    (("IM002", "[unixODBC][Driver Manager]Data source name not found"), "IM002", "ODBC"),
    (("HYT00", "[Microsoft][ODBC Driver 17 for SQL Server]Login timeout expired (0)"),
     "HYT00", "طول کشید"),
    (("42000", "The SELECT permission was denied on the object 'setting' (229)"), "229",
     "shop_app"),
])
def test_sql_errors_are_explained_in_persian(args, code, word):
    info = sql_errors.describe(pyodbc.Error(*args))
    assert info.code == code and word in info.message_fa


def test_unknown_sql_error_is_generic():
    assert sql_errors.describe(RuntimeError("boom")).message_fa == sql_errors.GENERIC_MESSAGE


def test_api_returns_the_persian_sql_error_without_server_details(client, reader):
    def fail(*a, **kw):
        raise pyodbc.Error("28000", "[SQL Server]Login failed for user 'shopbot'. (18456)")

    reader.list_groups = fail
    r = client.get("/groups", headers=h("bot"))
    assert r.status_code == 503
    body = r.json()
    assert body["error_code"] == "18456" and "گذرواژه" in body["message_fa"]
    assert "shopbot" not in json.dumps(body)


def test_server_status_shows_the_persian_sql_error(client, reader):
    def fail():
        raise pyodbc.Error("42000", "Cannot open database \"x\" (4060)")

    from .test_staff_auth import bearer, owner_token

    reader.ping = fail
    acc = client.get("/admin/server/status",
                     headers=bearer(owner_token(client))).json()["accounting"]
    assert acc["ok"] is False and acc["error_code"] == "4060" and acc["message_fa"]


# ---- shop_app role script --------------------------------------------------------------------
def test_shop_app_grant_script_is_least_privilege():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "sql" / "grant_shop_app.sql").read_text(
        encoding="utf-8")
    upper = text.split("*/", 1)[1].upper()             # the statements, not the header
    assert "CREATE ROLE SHOP_APP" in upper and "SP_ADDROLEMEMBER" in upper
    assert "ALTER ROLE" not in upper                       # SQL Server 2008 R2
    for denied in ("DENY UPDATE, DELETE ON DBO.KALAORDER TO SHOP_APP",
                   "DENY SELECT, INSERT, UPDATE, DELETE ON DBO.SETTING TO SHOP_APP",
                   "DENY SELECT ON DBO.TABAGHEHBANDI TO SHOP_APP"):
        assert denied in upper
    assert "GEYK" not in upper and "GRANT DELETE" not in upper
    assert "GRANT SELECT ON DBO.KALA (" in upper           # column-level only
    assert "PASSWORD" not in upper                         # no secret in the script


def test_installer_ships_the_grant_script():
    from pathlib import Path

    iss = (Path(__file__).resolve().parents[2] / "shopadmin" / "installer" / "ShopAdmin.iss"
           ).read_text(encoding="utf-8")
    files = iss.split("[Files]", 1)[1].split("[Icons]", 1)[0]
    server_part = files.split("#ifdef SERVER", 1)[1].split("#endif", 1)[0]
    assert "grant_shop_app.sql" in server_part and "grant_shop_app.ps1" in server_part


def test_writer_fake_result_shape():
    res = WriteResult(1, 1, "", 0, None, 1, 1)
    assert res.duplicate_after_commit is False
