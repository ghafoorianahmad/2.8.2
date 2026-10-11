"""End-to-end order test, DRY-RUN ONLY, no bots, on 'hesab5 t' only.

Run ON THE SERVER PC (the bot/admin keys are only accepted from loopback):

    shopapi\\.venv\\Scripts\\python.exe shopapi\\scripts\\e2e_order_dryrun.py \\
        [--env C:\\ProgramData\\ShopServer\\.env] [--url https://127.0.0.1:8443] [--person-code N]

It reads the keys from the .env itself and never prints them. It refuses to run if
the configured database is not 'hesab5 t' or if ACCOUNTING_WRITE_ENABLED is on.
Test data is named TEST-E2E (user name, chat_id, receipt ref). The accounting
text columns are fixed by the writer (Sharhlp = 'API-<order id>', sharh = '').

The final "rows that WOULD be written" preview runs the real AccountingWriter with
dry_run=True (explicit), recording every statement; it always rolls back.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_DB = "hesab5 t"
ALIASES = {"DB_SERVER": "ACCOUNTING_SERVER", "DB_NAME": "ACCOUNTING_DATABASE",
           "DB_DRIVER": "ACCOUNTING_DRIVER", "DB_TRUSTED": "ACCOUNTING_TRUSTED_CONNECTION",
           "DB_USER": "ACCOUNTING_USERNAME", "DB_PASSWORD": "ACCOUNTING_PASSWORD",
           "DB_ENCRYPT": "ACCOUNTING_ENCRYPT"}

results: list[tuple[str, str, str]] = []


def record(step: str, ok: bool, note: str = "") -> bool:
    results.append((step, "PASS" if ok else "FAIL", note))
    print(f"[{'PASS' if ok else 'FAIL'}] {step} {note}")
    return ok


def stop(reason: str) -> None:
    print(f"ABORT: {reason}")
    raise SystemExit(2)


class Recorder:
    """Wraps a pyodbc connection; keeps every statement with its parameters."""

    def __init__(self, conn, log):
        self._conn, self._log = conn, log

    def execute(self, sql, *params):
        self._log.append((sql, params))
        return self._conn.execute(sql, *params)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name in ("_conn", "_log"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ShopServer" / ".env"))
    ap.add_argument("--url", default="https://127.0.0.1:8443")
    ap.add_argument("--person-code", type=int, default=0, help="existing accounting person code (default: lowest)")
    ap.add_argument("--real-write", action="store_true",
                    help="expect ACCOUNTING_WRITE_ENABLED=true on a LOCAL 'hesab5 t' and really write "
                         "(then checks the rows, view_sefaresh, idempotency and distinct Codlp)")
    args = ap.parse_args()

    env = {k: v for k, v in dotenv_values(args.env).items() if v is not None}
    for friendly, internal in ALIASES.items():
        if env.get(friendly) and not env.get(internal):
            env[internal] = env[friendly]
    os.environ.update(env)

    # ---- step 1: server + safety gates -------------------------------------
    db_name = env.get("ACCOUNTING_DATABASE", "")
    if db_name != REQUIRED_DB:
        stop(f"database is '{db_name}', not '{REQUIRED_DB}'")
    env_write = env.get("ACCOUNTING_WRITE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    server = env.get("ACCOUNTING_SERVER", "")
    if args.real_write:
        if not env_write:
            stop("--real-write needs ACCOUNTING_WRITE_ENABLED=true in .env")
        if server.lower() not in (r".\sqlexpress", "localhost", r"(local)\sqlexpress"):
            stop(f"--real-write only on the local instance, not '{server}'")
    elif env_write:
        stop("ACCOUNTING_WRITE_ENABLED is on in .env (use --real-write on the local test DB)")
    bot, admin = httpx.Client(base_url=args.url, verify=False, timeout=30,
                              headers={"X-API-Key": env.get("BOT_API_KEY", "")}), \
        httpx.Client(base_url=args.url, verify=False, timeout=30,
                     headers={"X-API-Key": env.get("ADMIN_API_KEY", "")})
    try:
        h = bot.get("/health")
        record("1a server /health", h.status_code == 200, f"HTTP {h.status_code}")
        info = admin.get("/admin/system-info")
        if info.status_code != 200:
            record("1b system-info (admin key, loopback)", False, f"HTTP {info.status_code} {info.text[:120]}")
            stop("cannot verify dry-run state")
        flags = info.json()
        expected = bool(args.real_write)
        record(f"1b DB=hesab5 t and writes {'ON' if expected else 'off (dry-run)'}",
               flags["accounting_write_enabled"] == expected
               and (not expected or flags.get("write_allowed_on_host")),
               f"db={db_name}, write_enabled={flags['accounting_write_enabled']}")
        if flags["accounting_write_enabled"] != expected:
            stop("server write mode does not match the requested mode")

        # ---- step 2: customer, products, order -------------------------------
        stamp = time.strftime("%Y%m%d%H%M%S")
        from app.accounting_reader import AccountingReader
        from app.accounting_writer import AccountingWriter
        from app.config import Settings

        settings = Settings.from_env()
        # Reuse an approved TEST-E2E customer from an earlier run: a person code can be
        # linked to one customer only, so a new customer would need another real code.
        users = admin.get("/admin/users").json()
        reuse = next((u for u in users if u["name"] == "TEST-E2E" and u["status"] == "approved"
                      and u["platform"] == "web"), None)
        if reuse is not None:
            chat_id, person = reuse["chat_id"], reuse["person_code"]
            record("2a reuse approved TEST-E2E customer", True, f"user id={reuse['id']}")
            record("2b customer already approved", True, "")
        else:
            chat_id = f"TEST-E2E-{stamp}"
            r = bot.post("/users/register", json={"platform": "web", "chat_id": chat_id,
                                                  "name": "TEST-E2E", "phone": "09000000000"})
            if not record("2a register customer (web/TEST-E2E)", r.status_code == 200, f"HTTP {r.status_code}"):
                return 1
            user_id = r.json()["id"]
            person = args.person_code
        if reuse is None and not person:
            conn = AccountingReader(settings).connection()
            try:  # the Code column only; no personal data is read
                person = int(conn.execute(
                    f"SELECT TOP 1 Code FROM [{db_name}].dbo.name_mo WHERE Code > 0 ORDER BY Code").fetchone()[0])
            finally:
                conn.close()
        if reuse is None:
            r = admin.post(f"/admin/users/{user_id}/approve", json={"person_code": person})
        if reuse is None and not record("2b approve customer (admin)", r.status_code == 200 and r.json()["status"] == "approved",
                      f"HTTP {r.status_code} status={r.json().get('status') if r.status_code == 200 else r.text[:120]}"):
            return 1

        r = bot.get("/products", params={"in_stock": "true", "page_size": 50})
        record("2c list /products", r.status_code == 200, f"HTTP {r.status_code}")
        picks = [p for p in r.json().get("items", []) if p["available_qty"] >= 2 and p["unit_price"] > 0][:2]
        if len(picks) < 2:
            record("2d pick 2 in-stock items", False, "fewer than 2 suitable products")
            return 1
        items = [{"kala_code": picks[0]["code"], "qty": 1}, {"kala_code": picks[1]["code"], "qty": 2}]
        r = bot.post("/orders", json={"platform": "web", "chat_id": chat_id, "items": items})
        if not record("2d create order", r.status_code == 201 and r.json()["status"] == "awaiting_payment",
                      f"HTTP {r.status_code}"):
            print(r.text[:300])
            return 1
        order = r.json()
        oid = order["id"]
        record("   state awaiting_payment", order["status"] == "awaiting_payment", f"order={oid} total={order['total']}")

        # ---- step 3/4: receipt, approve (dry-run) ----------------------------
        r = bot.post(f"/orders/{oid}/receipt", params={"platform": "web", "chat_id": chat_id},
                     json={"receipt_ref": f"TEST-E2E-receipt-{stamp}.png"})
        ok = r.status_code == 200 and r.json()["status"] == "receipt_uploaded"
        record("3a receipt upload -> receipt_uploaded", ok,
               f"HTTP {r.status_code} (API accepts a reference string, not image bytes)")
        r = admin.post(f"/admin/orders/{oid}/approve-payment")
        body = r.json() if r.status_code == 200 else {}
        if args.real_write:
            return real_write_checks(bot, admin, chat_id, stamp, oid, body, r, picks, person)
        record("3b approve-payment (dry-run, no write)", r.status_code == 200,
               f"HTTP {r.status_code} status={body.get('status', r.text[:120])} "
               f"accounting_order_no={body.get('accounting_order_no')}")
        g = admin.get(f"/admin/orders", params={"status": "receipt_uploaded"})
        still = any(o["id"] == oid for o in g.json()) if g.status_code == 200 else None
        record("4  state after dry-run approve", still is True,
               "stays receipt_uploaded (a dry-run never reaches 'written'/'approved'); retry stays possible"
               if still else f"unexpected: {body.get('status')}")

        # ---- rows that WOULD be written (always rolled back) -----------------
        log: list = []
        writer = AccountingWriter(settings, connection_factory=lambda: Recorder(
            AccountingWriter(settings)._default_connect(), log))
        write_items = [(it["kala_code"], it["qty"], it["unit_price"]) for it in order["items"]]
        res = writer.write_order(oid, person, write_items, dry_run=True)
        record("5  writer preview rolled back", res.rolled_back and not res.committed,
               f"Codlp={res.accounting_order_no} (would be MAX+1)")
        from app.accounting_writer import DETAIL_COLUMNS, HEADER_COLUMNS
        print("\nWOULD INSERT KalaOrder:")
        print("  ", dict(zip(HEADER_COLUMNS, [
            res.accounting_order_no, person, res.datelp, res.mablp, f"API-{oid}", -100, 0, "", 0, 0,
            res.status_code, 0, res.usercode, 0, 0, 0])))
        print("WOULD INSERT KalaOrderDetail:")
        for i, it in enumerate(res.items, 1):
            print("  ", dict(zip(DETAIL_COLUMNS, [i, res.accounting_order_no, it["codekala"], it["meg"],
                                                  it["gey"], "", res.anbarcode, 0, 0, "", "", "", "", "", "", "", ""])))
        print(f"statements executed in the rolled-back transaction: {len(log)}")
    finally:
        bot.close()
        admin.close()

    failed = [r for r in results if r[1] == "FAIL"]
    print(f"\nSUMMARY: {len(results) - len(failed)} pass, {len(failed)} fail")
    return 1 if failed else 0


TEXT_COLUMNS = ("sharh", "field1", "field2", "field3", "field4", "field5", "field6", "field7", "field8")
HEADER_SHOWN = ("Codlp", "Codnlp", "Datelp", "Mablp", "Sharhlp", "Status", "Codf", "usercode",
                "takhfif", "tavasot", "avarez", "va", "Taf2", "PrintCount", "Naghd", "Ischeck")
DETAIL_SHOWN = ("Num", "Codlp_", "Codekala", "Meg", "Gey", "AnbarCode", "PrintCount", "takhfif") + TEXT_COLUMNS


def _db_conn():
    """Accounting connection that refuses anything but the local 'hesab5 t'."""
    from app.accounting_reader import AccountingReader
    from app.config import Settings

    conn = AccountingReader(Settings.from_env()).connection()
    server, db, machine = conn.execute(
        "SELECT @@SERVERNAME, DB_NAME(), CAST(SERVERPROPERTY('MachineName') AS nvarchar(128))").fetchone()
    if db != REQUIRED_DB or machine.upper() != os.environ.get("COMPUTERNAME", "").upper():
        stop(f"connected to {server}/{db}, not the local '{REQUIRED_DB}'")
    return conn


def _rows_for(conn, codlp: int):
    head = conn.execute(f"SELECT {', '.join(HEADER_SHOWN)} FROM dbo.KalaOrder WHERE Codlp = ?",
                        codlp).fetchall()
    detail = conn.execute(f"SELECT {', '.join(DETAIL_SHOWN)} FROM dbo.KalaOrderDetail "
                          "WHERE Codlp_ = ? ORDER BY Num", codlp).fetchall()
    return head, detail


def _expected_status() -> int:
    from app.config import Settings
    return Settings.from_env().accounting_status_code


def real_write_checks(bot, admin, chat_id, stamp, oid, body, response, picks, person) -> int:
    ok = response.status_code == 200 and body.get("status") == "written" and body.get("accounting_order_no")
    record("3b approve-payment REAL write -> written", bool(ok),
           f"HTTP {response.status_code} status={body.get('status')} Codlp={body.get('accounting_order_no')}")
    if not ok:
        print(response.text[:300])
        return 1
    codlp = int(body["accounting_order_no"])
    conn = _db_conn()
    try:
        head, detail = _rows_for(conn, codlp)
        h = head[0] if head else None
        good = (len(head) == 1 and h.Codnlp == person and h.Sharhlp == f"API-{oid}" and h.Status == _expected_status()
                and h.Codf == -100 and h.usercode == 1 and float(h.Mablp) == float(body["total"]))
        record("4a KalaOrder header (Status per config, Codf -100, usercode 1, Mablp = total)", good, "")
        if h is not None:
            print("   KalaOrder:", {k: getattr(h, k) for k in HEADER_SHOWN})
        texts_ok = all(getattr(d, f) == "" for d in detail for f in TEXT_COLUMNS)
        items = {it["kala_code"]: it for it in body["items"]}
        lines_ok = len(detail) == len(items) and all(
            d.Codekala in items and float(d.Meg) == float(items[d.Codekala]["qty"])
            and float(d.Gey) == float(items[d.Codekala]["unit_price"]) and d.AnbarCode == 1 for d in detail)
        record("4b KalaOrderDetail lines", lines_ok and texts_ok,
               f"{len(detail)} lines; sharh/field1..8 are '' (not NULL): {texts_ok}")
        for d in detail:
            print("   KalaOrderDetail:", {k: getattr(d, k) for k in DETAIL_SHOWN})

        # the accounting software's own order view (no person columns are selected)
        cols = [c.column_name for c in conn.cursor().columns(table="view_sefaresh", schema="dbo")]
        print("   view_sefaresh columns:", cols)
        key = next((c for c in cols if c.lower() == "codlp"), None) or \
            next((c for c in cols if c.lower() == "codlp_"), None)
        if key:
            wanted = [c for c in cols if c.lower() in (
                "codlp", "codlp_", "num", "codekala", "meg", "gey", "mablp", "sharhlp", "status",
                "namekala", "name_kala", "kalaname", "sharhkala", "jam", "mablagh", "total")]
            sel = ", ".join(f"[{c}]" for c in wanted)
            rows = conn.execute(f"SELECT {sel} FROM dbo.view_sefaresh WHERE [{key}] = ?", codlp).fetchall()
            record("5  view_sefaresh returns the order", len(rows) >= 1, f"{len(rows)} rows")
            for row in rows:
                print("   view_sefaresh:", dict(zip(wanted, row)))
        else:
            record("5  view_sefaresh returns the order", False, "no Codlp column found")

        # idempotency: approve again (API) and replay the writer with the same Sharhlp
        again = admin.post(f"/admin/orders/{oid}/approve-payment")
        record("6a approve-payment again is refused/ignored", again.status_code in (200, 409),
               f"HTTP {again.status_code} {again.text[:80]}")
        from app.accounting_writer import AccountingWriter
        from app.config import Settings

        res = AccountingWriter(Settings.from_env()).write_order(
            oid, person, [(it["kala_code"], it["qty"], it["unit_price"]) for it in body["items"]])
        _head2, detail2 = _rows_for(conn, codlp)
        dup = conn.execute("SELECT COUNT(*) FROM dbo.KalaOrder WHERE Sharhlp = ?", f"API-{oid}").fetchone()[0]
        record("6b writer replay is idempotent (no duplicate rows)",
               res.idempotent and not res.committed and dup == 1 and len(detail2) == len(detail),
               f"idempotent={res.idempotent}, headers for API-{oid}: {dup}")

        # two orders back to back get distinct Codlp
        codes = []
        for n in (1, 2):
            o = bot.post("/orders", json={"platform": "web", "chat_id": chat_id,
                                          "items": [{"kala_code": picks[0]["code"], "qty": 1}]})
            if o.status_code != 201:
                record(f"6c back-to-back order {n}", False, f"HTTP {o.status_code} {o.text[:100]}")
                break
            o_id = o.json()["id"]
            bot.post(f"/orders/{o_id}/receipt", params={"platform": "web", "chat_id": chat_id},
                     json={"receipt_ref": f"TEST-E2E-receipt-{stamp}-{n}.png"})
            a = admin.post(f"/admin/orders/{o_id}/approve-payment")
            codes.append((o_id, a.json().get("accounting_order_no") if a.status_code == 200 else None))
        record("6c two back-to-back orders get distinct Codlp",
               len(codes) == 2 and all(c for _, c in codes) and codes[0][1] != codes[1][1], f"{codes}")
        print("ADDED (our order id, Codlp):", [(oid, codlp)] + codes)
    finally:
        conn.close()
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"\nSUMMARY: {len(results) - len(failed)} pass, {len(failed)} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
