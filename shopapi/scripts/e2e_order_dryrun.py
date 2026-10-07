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
    if env.get("ACCOUNTING_WRITE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"):
        stop("ACCOUNTING_WRITE_ENABLED is on in .env")
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
        record("1b DB=hesab5 t and dry-run on", not flags["accounting_write_enabled"],
               f"db={db_name}, write_enabled={flags['accounting_write_enabled']}")
        if flags["accounting_write_enabled"]:
            stop("server reports writes enabled")

        # ---- step 2: customer, products, order -------------------------------
        stamp = time.strftime("%Y%m%d%H%M%S")
        chat_id = f"TEST-E2E-{stamp}"
        r = bot.post("/users/register", json={"platform": "web", "chat_id": chat_id,
                                              "name": "TEST-E2E", "phone": "09000000000"})
        if not record("2a register customer (web/TEST-E2E)", r.status_code == 200, f"HTTP {r.status_code}"):
            return 1
        user_id = r.json()["id"]

        from app.accounting_reader import AccountingReader
        from app.accounting_writer import AccountingWriter
        from app.config import Settings

        settings = Settings.from_env()
        person = args.person_code
        if not person:
            conn = AccountingReader(settings).connection()
            try:  # the Code column only; no personal data is read
                person = int(conn.execute(
                    f"SELECT TOP 1 Code FROM [{db_name}].dbo.name_mo WHERE Code > 0 ORDER BY Code").fetchone()[0])
            finally:
                conn.close()
        r = admin.post(f"/admin/users/{user_id}/approve", json={"person_code": person})
        if not record("2b approve customer (admin)", r.status_code == 200 and r.json()["status"] == "approved",
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
            res.accounting_order_no, person, res.datelp, res.mablp, f"API-{oid}", -100, 0, "", 0, 0, 0,
            res.status_code, 0, res.usercode, 0, 0])))
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


if __name__ == "__main__":
    raise SystemExit(main())
