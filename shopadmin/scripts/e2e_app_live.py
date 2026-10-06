"""Drive the real wizard + main window against a LIVE shopapi instance.

This is the closest automated equivalent of the acceptance test: it fills in the
first-run wizard with the running server's URL and ADMIN_API_KEY, completes it,
logs in, and loads the dashboard and product pages with real data.

Usage:
    python scripts/e2e_app_live.py [base_url]
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QThreadPool, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.auth import AuthService  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.wizard import SetupWizard, needs_setup  # noqa: E402

from e2e_check import read_shopapi_key  # noqa: E402


def pump(app: QApplication, rounds: int = 60, wait_ms: int = 25_000) -> None:
    QThreadPool.globalInstance().waitForDone(wait_ms)
    for _ in range(rounds):
        app.processEvents()
    QThreadPool.globalInstance().waitForDone(5_000)
    for _ in range(rounds):
        app.processEvents()


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    api_key = read_shopapi_key()
    if not api_key:
        print("No ADMIN_API_KEY available.")
        return 2

    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.apply_theme(app)

    tmp = Path(tempfile.mkdtemp(prefix="shopadmin-e2e-"))
    failures: list[str] = []
    try:
        store = Store(tmp / "shopadmin.db")
        auth = AuthService(store)

        # ---- 1. a fresh install must ask for setup ---------------------
        if not needs_setup(store, auth):
            failures.append("a fresh install did not request first-run setup")
        else:
            print("[ok] fresh install requires the setup wizard", flush=True)

        # ---- 2. wizard: test the real connection -----------------------
        wizard = SetupWizard(store, auth)
        wizard.show()
        wizard.base_url_input.setText(base_url)
        wizard.api_key_input.setText(api_key)
        wizard._test_connection()
        pump(app)
        result_text = wizard.connection_result.text()
        if "موفقیت" not in result_text:
            failures.append(f"wizard connection test did not succeed: {result_text!r}")
        else:
            print(f"[ok] wizard test-connection: {result_text.splitlines()[0]}", flush=True)
            if "حالت آزمایشی" in result_text:
                print("[ok] wizard warns about dry-run mode", flush=True)

        # ---- 3. wizard: create the first super admin -------------------
        wizard.full_name_input.setText("مالک فروشگاه")
        wizard.new_username_input.setText("owner")
        wizard.new_password_input.setText("Secret123")
        wizard.confirm_password_input.setText("Secret123")
        wizard._finish()
        pump(app, rounds=10)
        if needs_setup(store, auth):
            failures.append("the wizard did not complete the setup")
        else:
            print("[ok] wizard created the super admin and saved the settings", flush=True)
        if store.base_url != base_url:
            failures.append(f"saved base url mismatch: {store.base_url!r}")
        else:
            print(f"[ok] settings persisted (base url {store.base_url})", flush=True)
        wizard.close()

        # ---- 4. log in for real ----------------------------------------
        login = auth.authenticate("owner", "Secret123")
        print(f"[ok] login as {login.principal.username} "
              f"({login.principal.role})", flush=True)

        # ---- 5. main window against the live server --------------------
        from app.api_client import ShopApiClient

        client = ShopApiClient(store.base_url, store.api_key, timeout=25)
        context = AppContext(store=store, auth=auth, api=client,
                             principal=login.principal)
        window = MainWindow(context)
        window.resize(1440, 900)
        window.show()

        window.check_connection_async()
        pump(app)
        if not context.connection_ok:
            failures.append("the top-bar connection probe reported offline")
        else:
            print("[ok] connection status dot: connected", flush=True)

        if not context.system_info.accounting_write_enabled:
            if not window.banner.isVisible():
                failures.append("the dry-run banner is not visible")
            else:
                print("[ok] yellow dry-run banner is visible", flush=True)

        # dashboard with real data
        window.navigate("dashboard")
        pump(app)
        dashboard = window._pages["dashboard"]
        print(f"[ok] dashboard cards — customers={dashboard.card_pending_customers._value_label.text()!r} "
              f"receipts={dashboard.card_receipts._value_label.text()!r} "
              f"products={dashboard.card_products._value_label.text()!r}", flush=True)
        if dashboard.card_products._value_label.text() in ("…", "—"):
            failures.append("the dashboard product count did not load from shopapi")

        # products with real data
        window.navigate("products")
        pump(app)
        products = window._pages["products"]
        if products.table.rowCount() == 0:
            failures.append("the products page showed no rows for a live server")
        else:
            first = products.table.item(0, 1).text()
            print(f"[ok] products page loaded {products.table.rowCount()} row(s); "
                  f"first={first!r}", flush=True)

        # settings shows the live server state
        window.navigate("settings")
        pump(app, rounds=15, wait_ms=3000)
        settings = window._pages["settings"]
        status = settings.connection_status.text()
        if "حسابداری" not in status:
            failures.append(f"the settings page did not report accounting mode: {status!r}")
        else:
            print(f"[ok] settings reports: {status}", flush=True)

        # customers page (may legitimately be empty)
        window.navigate("customers")
        pump(app)
        print("[ok] customers page loaded "
              f"({window._pages['customers'].table.rowCount()} row(s))", flush=True)

        # orders page
        window.navigate("orders")
        pump(app)
        print("[ok] orders page loaded "
              f"({window._pages['orders'].table.rowCount()} row(s))", flush=True)

        window.close()
        client.close()
        store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"E2E FAILED with {len(failures)} problem(s):")
        for problem in failures:
            print(f"  - {problem}")
        return 1
    print("E2E against the live shopapi: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
