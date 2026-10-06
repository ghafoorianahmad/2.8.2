"""End-to-end acceptance check against a RUNNING shopapi instance.

This is the real integration test: it uses the shipped ShopApiClient to talk to
a live server over HTTP — no mocks — and verifies the data the desktop app needs.

Usage:
    python scripts/e2e_check.py [base_url]

Reads ADMIN_API_KEY from the shopapi .env (../shopapi/.env) unless the
SHOPADMIN_API_KEY environment variable is set. Never prints the key.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api_client import ApiError, ShopApiClient  # noqa: E402
from app.persian import format_money, format_shamsi, to_persian_digits  # noqa: E402
from app.reporting import DEFAULT_ORDER_STATUSES, filter_by_range, summarize  # noqa: E402
from app.statuses import customer_status_fa, order_status_fa  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, note: str = "") -> None:
    results.append((status, name, note))
    marker = {"PASS": "[ok]", "FAIL": "[!!]", "SKIP": "[--]"}[status]
    print(f"{marker} {name}" + (f" — {note}" if note else ""), flush=True)


def read_shopapi_key() -> str:
    key = os.getenv("SHOPADMIN_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT.parent / "shopapi" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("ADMIN_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    api_key = read_shopapi_key()
    if not api_key:
        print("No ADMIN_API_KEY available; cannot run the authenticated checks.")
        return 2

    client = ShopApiClient(base_url, api_key, timeout=20)
    print(f"target: {base_url}\n", flush=True)

    try:
        # ---- 1. health (no key) -----------------------------------------
        try:
            health = client.health()
            record(PASS if health.get("status") == "ok" else FAIL,
                   "GET /health returns status=ok", str(health))
        except ApiError as exc:
            record(FAIL, "GET /health", exc.message)
            return 1

        # ---- 2. system-info (drives the dry-run banner) -----------------
        info = None
        try:
            info = client.system_info()
            note = ("accounting_write_enabled="
                    f"{'true' if info.accounting_write_enabled else 'false (dry-run banner will show)'}")
            record(PASS, "GET /admin/system-info", note)
            if not info.accounting_write_enabled:
                record(PASS, "yellow dry-run banner is required by this server state",
                       "ACCOUNTING_WRITE_ENABLED=false")
        except ApiError as exc:
            record(FAIL, "GET /admin/system-info", exc.message)

        # ---- 3. customers ----------------------------------------------
        customers = []
        try:
            customers = client.list_customers()
            record(PASS, "GET /admin/users", f"{len(customers)} customer(s)")
            for status_code in ("pending", "approved", "rejected"):
                subset = client.list_customers(status_code)
                assert all(c["status"] == status_code for c in subset), status_code
            record(PASS, "GET /admin/users?status=... filters correctly")
        except ApiError as exc:
            record(FAIL, "GET /admin/users", exc.message)

        # ---- 4. orders per status --------------------------------------
        orders_by_status: dict[str, list] = {}
        try:
            for status_code in DEFAULT_ORDER_STATUSES:
                orders_by_status[status_code] = client.list_orders(status_code)
            counts = ", ".join(f"{s}={len(v)}" for s, v in orders_by_status.items())
            record(PASS, "GET /admin/orders for all 7 statuses", counts)
        except ApiError as exc:
            record(FAIL, "GET /admin/orders", exc.message)

        # ---- 5. products + groups --------------------------------------
        try:
            page = client.list_products(page=1, page_size=5)
            record(PASS, "GET /products", f"total={page.get('total')} "
                                          f"items={len(page.get('items') or [])}")
            groups = client.list_groups()
            record(PASS, "GET /groups", f"{len(groups)} group(s)")
        except ApiError as exc:
            record(FAIL, "GET /products", exc.message)

        # ---- 6. auth is actually enforced ------------------------------
        try:
            bad = ShopApiClient(base_url, "definitely-wrong-key", timeout=15)
            bad.list_customers()
            record(FAIL, "a wrong API key is rejected", "no error raised")
        except ApiError as exc:
            ok = exc.status_code in (401, 403)
            record(PASS if ok else FAIL, "a wrong API key is rejected",
                   f"HTTP {exc.status_code}")
        finally:
            try:
                bad.close()
            except Exception:
                pass

        # ---- 7. Persian rendering of real data -------------------------
        if customers:
            sample = customers[0]
            rendered = (
                f"status={customer_status_fa(sample.get('status'))} "
                f"date={format_shamsi(sample.get('created_at'))}"
            )
            problem = _has_ascii_digit(rendered)
            record(PASS if not problem else FAIL,
                   "customer status/date render in Persian", rendered)
        else:
            record(SKIP, "Persian rendering of a customer", "no customers in the database")

        real_orders = [o for group in orders_by_status.values() for o in group]
        if real_orders:
            order = real_orders[0]
            rendered = (f"status={order_status_fa(order.get('status'))} "
                        f"total={format_money(order.get('total'))} "
                        f"date={format_shamsi(order.get('created_at'))}")
            problem = _has_ascii_digit(rendered)
            record(PASS if not problem else FAIL,
                   "order status/amount/date render in Persian", rendered)
            summary = summarize(real_orders, customers,
                                min_date(real_orders), max_date(real_orders))
            record(PASS, "report summary over live data",
                   f"orders={to_persian_digits(summary['order_count'])} "
                   f"amount={format_money(summary['total_amount'])} "
                   f"new_customers={to_persian_digits(summary['new_customers'])}")
        else:
            record(SKIP, "Persian rendering of an order", "no orders in the database")

        # ---- 8. order detail has the fields the dialog needs -----------
        if real_orders:
            order = real_orders[0]
            needed = {"id", "status", "total", "created_at", "items"}
            missing = needed - set(order)
            record(PASS if not missing else FAIL,
                   "OrderOut carries the fields the detail dialog renders",
                   f"missing={sorted(missing)}" if missing else "all present")

    finally:
        client.close()

    failures = [r for r in results if r[0] == FAIL]
    passes = [r for r in results if r[0] == PASS]
    skips = [r for r in results if r[0] == SKIP]
    print(f"\n{len(passes)} passed, {len(failures)} failed, {len(skips)} skipped")
    for _status, name, note in failures:
        print(f"  FAILED: {name} — {note}")
    return 1 if failures else 0


def min_date(orders: list) -> "object":
    from app.persian import coerce_datetime

    dates = [coerce_datetime(o.get("created_at")) for o in orders]
    dates = [d for d in dates if d is not None]
    return min(dates).date()


def max_date(orders: list) -> "object":
    from app.persian import coerce_datetime

    dates = [coerce_datetime(o.get("created_at")) for o in orders]
    dates = [d for d in dates if d is not None]
    return max(dates).date()


def _has_ascii_digit(text: str) -> bool:
    return any(ch.isascii() and ch.isdigit() for ch in text)


if __name__ == "__main__":
    sys.exit(main())
