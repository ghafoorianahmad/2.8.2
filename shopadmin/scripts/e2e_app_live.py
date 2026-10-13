r"""Drive the real wizard + login + main window against a LIVE shopapi instance.

The closest automated equivalent of the acceptance test: it runs the first-run
wizard against the server, signs in with a staff account (server-side session
token — the client never holds ADMIN_API_KEY), then loads the main pages with
real data. Runs offscreen; it uses a throw-away local data folder.

How to run (Windows, PowerShell, local test setup):
    1. ``shopapi\``: .env points at the TEST database ``hesab5 t``
       (ACCOUNTING_WRITE_ENABLED=false); start it:  .\run.ps1
    2. A staff account must exist on that server (see e2e_check.py for the
       SHOPADMIN_BOOTSTRAP_KEY option on a fresh test server).
    3. In ``shopadmin\``:
         $env:SHOPADMIN_USER = "owner"
         $env:SHOPADMIN_PASSWORD = "<password>"      # never printed
         .\.venv\Scripts\python.exe scripts\e2e_app_live.py [base_url]

Same environment variables as e2e_check.py (SHOPADMIN_BASE_URL,
SHOPADMIN_CERT_FILE, SHOPADMIN_BOOTSTRAP_KEY). With https, the pinned
certificate comes from SHOPADMIN_CERT_FILE; the wizard's fingerprint
confirmation is ticked automatically because this is a test run.
Exit code: 0 all passed, 1 a check failed, 2 missing credentials.
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
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import QThreadPool, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.api_client import ShopApiClient  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.wizard import SetupWizard, needs_setup  # noqa: E402

from e2e_check import default_base_url, read_cert_pem, read_credentials  # noqa: E402


def pump(app: QApplication, rounds: int = 60, wait_ms: int = 25_000) -> None:
    QThreadPool.globalInstance().waitForDone(wait_ms)
    for _ in range(rounds):
        app.processEvents()
    QThreadPool.globalInstance().waitForDone(5_000)
    for _ in range(rounds):
        app.processEvents()


def main() -> int:
    base_url = default_base_url()
    user, password = read_credentials()
    if not (user and password):
        print("Set SHOPADMIN_USER and SHOPADMIN_PASSWORD (a staff account on the server).")
        return 2

    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.apply_theme(app)

    tmp = Path(tempfile.mkdtemp(prefix="shopadmin-e2e-"))
    failures: list[str] = []
    try:
        store = Store(tmp / "shopadmin.db")
        client = ShopApiClient("", timeout=25)
        auth = AuthService(store, client)

        # ---- 1. a fresh install must ask for setup ---------------------
        if not needs_setup(store):
            failures.append("a fresh install did not request first-run setup")
        else:
            print("[ok] fresh install requires the setup wizard", flush=True)

        # ---- 2. wizard: probe the server, pin the certificate ----------
        wizard = SetupWizard(store, auth)
        wizard.show()
        wizard.base_url_input.setText(base_url)
        wizard._test_connection()
        pump(app)
        result_text = wizard.connection_result.text()
        if "برقرار شد" not in result_text:
            failures.append(f"wizard connection test did not succeed: {result_text!r}")
        else:
            print(f"[ok] wizard test-connection: {result_text.splitlines()[0]}", flush=True)
        if wizard.bootstrap_required:
            failures.append("the server has no staff account yet; create one first "
                            "(see e2e_check.py, SHOPADMIN_BOOTSTRAP_KEY)")

        # ---- 3. wizard: finish (https: the test run confirms the pin) --
        wizard.cert_confirm.setChecked(True)
        wizard._test_connection(advance=True)
        pump(app, rounds=20)
        if needs_setup(store):
            failures.append("the wizard did not complete the setup")
        else:
            print("[ok] wizard saved the server address"
                  f"{' and pinned certificate' if store.server_cert_pem else ''}", flush=True)
        if store.base_url != base_url.rstrip("/"):
            failures.append(f"saved base url mismatch: {store.base_url!r}")
        wizard.close()

        # ---- 4. sign in with the staff account (server session) --------
        client.configure(store.base_url, "")
        client.set_server_cert(store.server_cert_pem or read_cert_pem())
        login = auth.authenticate(user, password)
        if not client.has_session:
            failures.append("login did not leave a session token on the client")
        print(f"[ok] signed in as {login.principal.username} "
              f"({login.principal.role}); session token held in memory only", flush=True)

        # ---- 5. main window against the live server --------------------
        context = AppContext(store=store, auth=auth, api=client, principal=login.principal)
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

        window.navigate("dashboard")
        pump(app)
        dashboard = window._pages["dashboard"]
        print(f"[ok] dashboard cards — customers={dashboard.card_pending_customers._value_label.text()!r} "
              f"receipts={dashboard.card_receipts._value_label.text()!r} "
              f"products={dashboard.card_products._value_label.text()!r}", flush=True)
        if dashboard.card_products._value_label.text() in ("…", "—"):
            failures.append("the dashboard product count did not load from shopapi")

        window.navigate("products")
        pump(app)
        products = window._pages["products"]
        if products.table.rowCount() == 0:
            failures.append("the products page showed no rows for a live server")
        else:
            first = products.table.item(0, 1).text()
            print(f"[ok] products page loaded {products.table.rowCount()} row(s); "
                  f"first={first!r}", flush=True)

        window.navigate("settings")
        pump(app, rounds=15, wait_ms=3000)
        status = window._pages["settings"].connection_status.text()
        if "حسابداری" not in status:
            failures.append(f"the settings page did not report accounting mode: {status!r}")
        else:
            print(f"[ok] settings reports: {status}", flush=True)

        for key, label in (("customers", "customers"), ("orders", "orders")):
            window.navigate(key)
            pump(app)
            print(f"[ok] {label} page loaded "
                  f"({window._pages[key].table.rowCount()} row(s))", flush=True)

        # ---- 6. logout ends the server session -------------------------
        window.close()
        auth.logout()
        if client.has_session:
            failures.append("logout left a session token on the client")
        else:
            print("[ok] logout dropped the session", flush=True)
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
