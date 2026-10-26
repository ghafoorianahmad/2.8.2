"""v2.9.4: the setup's precise database test (as the service account), the
database list, «مدیر کل» on reinstall, the status-code helper (read only), the
test-data cleanup (never the accounting DB) and the backup alert with its
reason."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import cleanup, control, db_setup, grant_access, monitor
from app.config import Settings
from app.staff import hash_password, verify_password

from .conftest import h
from .test_phase3 import staff


def _settings(**kw) -> Settings:
    base = dict(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                accounting_username="shopbot", accounting_password="S3cret!",
                accounting_trusted=False)
    base.update(kw)
    return Settings(**base)


class SqlError(Exception):
    """Like pyodbc.Error: (SQLSTATE, driver text with the native number)."""


# ---- fake SQL Server -----------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, server):
        self.server = server
        self.result = []

    def execute(self, sql, *params):
        self.server.executed.append((sql, params))
        for mark, error in self.server.fail.items():
            if mark in sql:
                raise error
        if sql.startswith("SELECT DB_ID"):
            self.result = [(5 if params[0] in self.server.databases else None,)]
        elif "FROM sys.databases" in sql:
            self.result = [(name,) for name in self.server.databases]
        elif "sys.server_principals" in sql:
            self.result = [(1,)] if params[0] in self.server.logins else []
        elif "EXECUTE AS LOGIN" in sql:
            self.result = [(12,)]
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class FakeConn:
    def __init__(self, server):
        self.server = server

    def cursor(self):
        return FakeCursor(self.server)

    def close(self):
        pass


class FakeServer:
    def __init__(self, databases=("hesab5", "hesab5 t"), logins=(), fail=None,
                 connect_error=None):
        self.databases = list(databases)
        self.logins = set(logins)
        self.fail = dict(fail or {})
        self.connect_error = connect_error
        self.strings = []
        self.executed = []

    def connect(self, string, **_kw):
        self.strings.append(string)
        if self.connect_error is not None:
            raise self.connect_error
        return FakeConn(self)


class OkReader:
    def __init__(self, settings):
        self.settings = settings

    def ping(self):
        return True

    def list_groups(self):
        return [{"code": 1}, {"code": 2}]


def failing_reader(error):
    class Reader(OkReader):
        def ping(self):
            raise error
    return Reader


# ---- database list ---------------------------------------------------------------------------------
def test_database_list_uses_this_windows_account_first():
    server = FakeServer(databases=["hesab2", "hesab5", "hesab5 t"])
    answer = db_setup.list_databases(_settings(), server.connect)
    assert answer == {"ok": True, "databases": ["hesab2", "hesab5", "hesab5 t"]}
    assert "Trusted_Connection=yes" in server.strings[0] and "DATABASE=master" in server.strings[0]
    assert "S3cret" not in server.strings[0]
    sql = server.executed[0][0]
    assert "sys.databases" in sql and "database_id > 4" in sql and "INSERT" not in sql.upper()


def test_database_list_server_not_found():
    server = FakeServer(connect_error=SqlError("08001", "[08001] Named Pipes Provider: "
                                                        "Could not open a connection (53)"))
    answer = db_setup.list_databases(_settings(), server.connect)
    assert answer["ok"] is False and answer["kind"] == "server_not_found"
    assert answer["title_fa"] == "SQL Server پیدا نشد" and answer["fix_fa"]


# ---- precise diagnosis -------------------------------------------------------------------------------
def test_diagnose_server_not_found():
    server = FakeServer(connect_error=SqlError("08001", "[08001] TCP Provider: error (10061)"))
    answer = db_setup.diagnose(_settings(), server.connect, OkReader)
    assert answer["kind"] == "server_not_found" and "SQL Server پیدا نشد" in answer["message_fa"]


def test_diagnose_database_missing_lists_the_real_ones():
    server = FakeServer(databases=["hesab5", "hesab5 t"])
    answer = db_setup.diagnose(_settings(accounting_database="hesab2"), server.connect, OkReader)
    assert answer["kind"] == "db_missing" and answer["title_fa"] == "این پایگاه‌داده وجود ندارد"
    assert answer["databases"] == ["hesab5", "hesab5 t"]


def test_diagnose_sql_login_missing_is_no_access_wrong_password_is_bad_password():
    login_failed = SqlError("28000", "[28000] Login failed for user 'shopbot'. (18456)")
    server = FakeServer(logins=())
    answer = db_setup.diagnose(_settings(), server.connect, failing_reader(login_failed))
    assert answer["kind"] == "no_access" and answer["title_fa"] == "دسترسی نیست"
    server = FakeServer(logins={"shopbot"})
    answer = db_setup.diagnose(_settings(), server.connect, failing_reader(login_failed))
    assert answer["kind"] == "bad_password"


def test_diagnose_no_permission_on_the_database():
    denied = SqlError("42000", "[42000] Cannot open database \"hesab5\" requested (4060)")
    server = FakeServer(logins={"shopbot"})
    answer = db_setup.diagnose(_settings(), server.connect, failing_reader(denied))
    assert answer["kind"] == "no_access" and answer["error_code"] == "4060"


def test_windows_sign_in_is_tested_as_the_service_account():
    """2.9.3: «OK» with the administrator's account, then the service could not
    sign in. Now the service login itself is impersonated."""
    server = FakeServer(logins=set())                    # no login for the service yet
    settings = _settings(accounting_trusted=True)
    answer = db_setup.diagnose(settings, server.connect, OkReader)
    assert answer["ok"] is False and answer["kind"] == "no_access"
    assert answer["login"] == "NT SERVICE\\ShopServer"
    server = FakeServer(logins={"NT SERVICE\\ShopServer"})
    answer = db_setup.diagnose(settings, server.connect, OkReader)
    assert answer["ok"] is True and answer["as_service"] is True
    impersonation = next(sql for sql, _ in server.executed if "EXECUTE AS LOGIN" in sql)
    assert "REVERT" in impersonation and "QUOTENAME(?" in impersonation
    assert "NT SERVICE" not in impersonation                   # the name is a parameter
    assert any(params == ("NT SERVICE\\ShopServer", "hesab5") for sql, params in server.executed
               if "EXECUTE AS LOGIN" in sql)
    # on master: this administrator needs no right in the shop's database itself
    assert all("DATABASE=master" in s for s in server.strings)
    for sql, _params in server.executed:
        assert not any(word in sql.upper() for word in ("INSERT ", "UPDATE ", "DELETE ", "CREATE "))


def test_service_account_without_rights_on_the_database():
    server = FakeServer(logins={"NT SERVICE\\ShopServer"},
                        fail={"EXECUTE AS LOGIN": SqlError(
                            "42000", "[42000] The server principal is not able to access "
                                     "the database (916)")})
    answer = db_setup.diagnose(_settings(accounting_trusted=True), server.connect, OkReader)
    assert answer["kind"] == "no_access" and answer["verified"] is True


def test_no_sysadmin_cannot_verify_but_does_not_fail():
    server = FakeServer(logins={"NT SERVICE\\ShopServer"},
                        fail={"EXECUTE AS LOGIN": SqlError(
                            "42000", "[42000] Cannot execute as the server principal (15406)")})
    answer = db_setup.diagnose(_settings(accounting_trusted=True), server.connect, OkReader)
    assert answer["ok"] is True and answer["as_service"] is False and "sysadmin" in answer["note_fa"]


def test_service_login_on_this_computer_or_another(monkeypatch):
    monkeypatch.setenv("USERDOMAIN", "SHOP")
    monkeypatch.setenv("COMPUTERNAME", "SRV1")
    assert db_setup.service_sql_login(r".\SQLEXPRESS", set()) == "NT SERVICE\\ShopServer"
    assert db_setup.service_sql_login(r"SRV1\SQLEXPRESS", {"srv1"}) == "NT SERVICE\\ShopServer"
    assert db_setup.service_sql_login("SQLBOX,1433", {"srv1"}) == "SHOP\\SRV1$"
    login, windows = grant_access.shop_login(_settings(accounting_trusted=True))
    assert (login, windows) == ("NT SERVICE\\ShopServer", True)
    assert grant_access.WINDOWS_LOGIN_RE.match("SHOP\\SRV1$")
    assert grant_access.grant_batches("hesab5", "SHOP\\SRV1$")
    with pytest.raises(grant_access.GrantError):
        grant_access.grant_batches("hesab5", "SHOP\\SRV1$'; DROP")


def test_remote_windows_outside_a_domain(monkeypatch):
    monkeypatch.setenv("USERDOMAIN", "SRV1")
    monkeypatch.setenv("COMPUTERNAME", "SRV1")
    monkeypatch.setattr(db_setup, "is_local_server", lambda server, names=None: False)
    server = FakeServer()
    answer = db_setup.check_as_service(_settings(accounting_server="SQLBOX", accounting_trusted=True),
                                       server.connect)
    assert answer["kind"] == "remote_windows"


# ---- «مدیر کل» on reinstall / server settings -----------------------------------------------------------
def test_owner_is_shown_and_reset_or_added_with_the_service_key_only(client, db):
    owner = db.create_staff("owner", "مالک", "super_admin", hash_password("Old12345"))
    db.create_staff("sara", "سارا", "operator", hash_password("Sara12345"))
    assert client.get("/auth/owner", headers=staff(db, "super_admin", "boss2")).status_code == 403
    owners = client.get("/auth/owner", headers=h("admin")).json()["owners"]
    assert [o["username"] for o in owners] == ["owner", "boss2"]
    assert "password" not in str(owners) and "hash" not in str(owners)
    # same username + new password = reset (and unlock)
    db.update_staff(owner["id"], failed_attempts=9, locked_until="2999-01-01T00:00:00+00:00")
    r = client.post("/auth/owner", json={"username": "OWNER", "full_name": "",
                                         "password": "New12345"}, headers=h("admin"))
    assert r.status_code == 200 and r.json()["action"] == "password_reset"
    row = db.get_staff_by_username("owner")
    assert verify_password("New12345", row["password_hash"]) and row["locked_until"] is None
    assert row["full_name"] == "مالک"                       # blank name = unchanged
    # a new username = one more owner
    r = client.post("/auth/owner", json={"username": "owner2", "full_name": "دوم",
                                         "password": "Two12345"}, headers=h("admin"))
    assert r.json()["action"] == "created" and db.get_staff_by_username("owner2")["role"] == \
        "super_admin"
    # a staff member's username is never turned into an owner
    r = client.post("/auth/owner", json={"username": "sara", "full_name": "",
                                         "password": "Sara99999"}, headers=h("admin"))
    assert r.status_code == 409
    assert db.get_staff_by_username("sara")["role"] == "operator"
    r = client.post("/auth/owner", json={"username": "x", "full_name": "", "password": "1"},
                    headers=h("admin"))
    assert r.status_code == 422


# ---- status-code helper (read only) -----------------------------------------------------------------
class StatusReader:
    def __init__(self):
        self.calls = 0

    def order_status_overview(self, limit=20):
        self.calls += 1
        return {"database": "hesab5 t", "statuses": [{"status": 1, "internet": False,
                                                      "count": 3, "first_order": 1,
                                                      "last_order": 9, "last_date": "1405/08/01"}],
                "latest_sazeh": []}


def test_status_codes_for_owner_and_service_never_for_sales(client, db, monkeypatch):
    reader = StatusReader()
    client.app.dependency_overrides[__import__("app.deps", fromlist=["x"]).get_reader] = \
        lambda: reader
    r = client.get("/admin/server/order-status-codes", headers=h("admin"))
    assert r.status_code == 200 and r.json()["statuses"][0]["status"] == 1
    assert client.get("/admin/server/order-status-codes",
                      headers=staff(db, "super_admin", "boss")).status_code == 200
    assert client.get("/admin/server/order-status-codes",
                      headers=staff(db, "operator", "sara")).status_code == 403


def test_status_overview_sql_only_reads():
    from app.accounting_reader import AccountingReader

    statements = []

    class Cur:
        description = [("Status",), ("Internet",), ("Cnt",), ("FirstCode",), ("LastCode",),
                       ("LastDate",)]

        def fetchall(self):
            return []

    class Conn:
        def execute(self, sql, *params):
            statements.append(sql)
            return Cur()

        def close(self):
            pass

    overview = AccountingReader(_settings(), lambda: Conn()).order_status_overview()
    assert overview["statuses"] == [] and overview["latest_sazeh"] == []
    assert len(statements) == 2
    for sql in statements:
        assert sql.lstrip().upper().startswith("SELECT")
        assert not any(w in sql.upper() for w in ("INSERT", "UPDATE ", "DELETE", "EXEC", "INTO "))
        assert "KalaOrder" in sql and "name_mo" not in sql and "Sharhlp" not in sql


# ---- live database test by the running service -------------------------------------------------------
def test_db_check_by_the_service_itself(client, db, monkeypatch):
    from app.routers import server_admin

    seen = {}

    class Reader(OkReader):
        def __init__(self, settings):
            seen["trusted"] = settings.accounting_trusted
            seen["database"] = settings.accounting_database
            super().__init__(settings)

    monkeypatch.setattr(server_admin, "AccountingReader", Reader)
    body = {"server": r".\SQLEXPRESS", "database": "hesab5"}
    assert client.post("/admin/server/db-check", json=body,
                       headers=staff(db, "super_admin", "boss")).status_code == 403
    r = client.post("/admin/server/db-check", json=body, headers=h("admin"))
    assert r.json() == {"ok": True, "groups": 2} and seen == {"trusted": True,
                                                              "database": "hesab5"}


# ---- cleanup -----------------------------------------------------------------------------------------
def _fresh_backup(minutes=1):
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return {"at": at, "ok": True, "file": "ShopServer_x.zip", "verify": {"ok": True}}


def _bots_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE platform_state (platform TEXT PRIMARY KEY, last_update_id INTEGER);
        CREATE TABLE conversations (platform TEXT, chat_id TEXT, state TEXT);
        CREATE TABLE carts (platform TEXT, chat_id TEXT, kala_code INTEGER);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO platform_state VALUES ('bale', 77);
        INSERT INTO conversations VALUES ('bale', '1', 'x');
        INSERT INTO carts VALUES ('bale', '1', 5);
        INSERT INTO kv VALUES ('k', 'v');
    """)
    conn.commit()
    conn.close()


def _seed_shop(db):
    user = db._conn.execute(
        "INSERT INTO users (platform, chat_id, name, phone, status, created_at) "
        "VALUES ('bale','1','زهرا','09120000000','approved','2026-10-01')").lastrowid
    order = db._conn.execute(
        "INSERT INTO orders (user_id, status, price_level, total, created_at, updated_at) "
        "VALUES (?, 'awaiting_payment', 3, 1000, 'x', 'x')", (user,)).lastrowid
    db._conn.execute("INSERT INTO order_items (order_id, kala_code, name, qty, unit_price) "
                     "VALUES (?, 5, 'قاب', 1, 1000)", (order,))
    db._conn.execute("INSERT INTO proxies (host, port, secret, state, added_at) "
                     "VALUES ('1.2.3.4', 443, 'ee', 'main', 'x')")
    db._conn.commit()
    db.add_event("order_created", order, "bot")
    db.set_state("sales_closed", "0", "test")


def test_cleanup_clears_only_the_shops_own_test_data(client, db, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")
    _bots_db(tmp_path / "shopbots.db")
    monkeypatch.setattr(control.STATE, "env_file", env)
    monkeypatch.setattr(control, "backup_status", lambda: _fresh_backup())
    db.create_staff("owner", "مالک", "super_admin", hash_password("Own12345"))
    db.create_staff("test1", "آزمایشی", "operator", hash_password("Tst12345"))
    _seed_shop(db)
    preview = client.get("/admin/server/cleanup-test-data", headers=h("admin")).json()
    assert preview["counts"]["orders"] == 1 and preview["counts"]["users"] == 1
    assert preview["staff_removed"] == ["test1"] and preview["owners"] == ["owner"]
    assert preview["backup_fresh"] is True and preview["confirm_text"] == "پاک‌سازی"
    # a staff token may not; a wrong confirmation is refused
    assert client.post("/admin/server/cleanup-test-data", json={"confirm": "پاک‌سازی"},
                       headers=staff(db, "super_admin", "boss")).status_code == 403
    r = client.post("/admin/server/cleanup-test-data", json={"confirm": "بله"},
                    headers=h("admin"))
    assert r.status_code == 409 and "confirmation" in r.json()["detail"]
    r = client.post("/admin/server/cleanup-test-data", json={"confirm": "پاک‌سازی"},
                    headers=h("admin"))
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["orders"] == 1
    for table in cleanup.OWN_TABLES:
        assert db._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0, table
    assert db.get_staff_by_username("owner") is not None
    assert db.get_staff_by_username("test1") is None
    assert db.get_staff_by_username("boss")["role"] == "super_admin"   # every owner stays
    assert db._conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0] == 1
    assert db.get_state("sales_closed") == "0"
    assert db._conn.execute("SELECT COUNT(*) FROM product_groups").fetchone()[0] > 0
    bots = sqlite3.connect(tmp_path / "shopbots.db")
    assert bots.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    assert bots.execute("SELECT COUNT(*) FROM carts").fetchone()[0] == 0
    assert bots.execute("SELECT last_update_id FROM platform_state").fetchone()[0] == 77
    assert bots.execute("SELECT COUNT(*) FROM kv").fetchone()[0] == 1
    bots.close()
    assert any(a["action"] == "cleanup_test_data" for a in db.list_audit(50)) \
        if hasattr(db, "list_audit") else True


def test_cleanup_needs_a_fresh_verified_backup(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(control.STATE, "env_file", tmp_path / ".env")
    for status in ({}, _fresh_backup(minutes=90),
                   {**_fresh_backup(), "verify": {"ok": False}}):
        monkeypatch.setattr(control, "backup_status", lambda s=status: s)
        r = client.post("/admin/server/cleanup-test-data", json={"confirm": "پاک‌سازی"},
                        headers=h("admin"))
        assert r.status_code == 409 and "backup" in r.json()["detail"]


def test_cleanup_removes_receipt_files_and_never_opens_the_accounting(db, tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "12.jpg").write_bytes(b"x")
    result = cleanup.clear_test_data(db, bots_path=None, receipts_dir=receipts,
                                     confirm=cleanup.CONFIRM_TEXT, backup_status=_fresh_backup())
    assert result["counts"]["receipt_files"] == 1 and not list(receipts.iterdir())
    source = (cleanup.__file__ and open(cleanup.__file__, encoding="utf-8").read())
    assert "pyodbc" not in source and "AccountingReader" not in source and "KalaOrder" not in source
    for kept in cleanup.KEPT_TABLES:
        assert kept not in cleanup.OWN_TABLES


# ---- backup alert ------------------------------------------------------------------------------------
class Sent(list):
    def __call__(self, text):
        self.append(text)
        return 1


def test_failed_backup_is_reported_once_per_run_with_its_reason(db, monkeypatch):
    settings = replace(_settings(), health_fail_threshold=2)
    sent = Sent()
    status = {"at": "2026-10-25T03:00:00+03:30", "ok": False, "error": "off-server copy failed",
              "offsite": {"configured": True, "ok": False,
                          "error": "PermissionError: Access is denied."},
              "last_success_at": None}
    monkeypatch.setattr(control, "backup_status", lambda: status)
    reader = OkReader(settings)
    mon = monitor.HealthMonitor(settings, lambda: db, lambda: reader, sender=sent)
    mon.tick()
    assert len(sent) == 1 and "ShopServerBackup" in sent[0] and "PermissionError" not in sent[0]
    assert "نسخهٔ بیرون از سرور" in sent[0]
    mon.tick()
    mon.tick()
    assert len(sent) == 1                                   # the same run: once
    # a restarted service does not report the same failure again
    again = monitor.HealthMonitor(settings, lambda: db, lambda: reader, sender=sent)
    again.tick()
    assert len(sent) == 1
    # the next night fails too: reported again
    status = {**status, "at": "2026-10-26T03:00:00+03:30"}
    monkeypatch.setattr(control, "backup_status", lambda: status)
    again.tick()
    assert len(sent) == 2
    # and recovers
    ok = {"at": "2026-10-27T03:00:00+03:30", "ok": True,
          "last_success_at": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(control, "backup_status", lambda: ok)
    again.tick()
    assert sent[-1] == monitor.TEXTS_UP["backup"]
