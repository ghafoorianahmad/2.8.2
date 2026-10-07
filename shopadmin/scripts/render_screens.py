"""Render the real screens to PNG files for visual review.

Runs the actual widgets against a fake shopapi (no network) so the screenshots
show exactly what the operator will see.

Usage:
    python scripts/render_screens.py [output_dir]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.api_client import ShopApiClient, SystemInfo  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.login_window import LoginWindow  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.wizard import SetupWizard  # noqa: E402
from tests.conftest import OWNER_PASSWORD, OWNER_TOKEN, FakeShopApi  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens"

FAKE_BASE_URL = "http://shopapi.test"


def new_fake() -> FakeShopApi:
    """A fake server with the owner account and a few staff members."""
    fake = FakeShopApi()
    fake.add_staff("owner", OWNER_PASSWORD, "super_admin", "مالک فروشگاه")
    fake.issue_token("owner", OWNER_TOKEN)
    fake.add_staff("sara", OWNER_PASSWORD, "admin", "سارا احمدی")
    fake.add_staff("reza", OWNER_PASSWORD, "operator", "رضا کریمی", must_change=True)
    fake.add_staff("naz", OWNER_PASSWORD, "viewer", "ناز مرادی")["locked"] = True
    return fake


def client_for(fake: FakeShopApi, token: str = OWNER_TOKEN) -> ShopApiClient:
    return ShopApiClient(FAKE_BASE_URL, token, transport=httpx.MockTransport(fake.handler))


def seed(fake: FakeShopApi) -> None:
    """Populate the fake shopapi with realistic Persian sample data.

    Timestamps are relative to *now* so the default "today"/"30 days" report
    ranges contain data.
    """
    from datetime import datetime, timedelta, timezone

    def ago(hours: float = 0, days: float = 0) -> str:
        moment = datetime.now(timezone.utc) - timedelta(hours=hours, days=days)
        return moment.isoformat(timespec="seconds")

    fake.add_customer(name="زهرا محمدی", platform="telegram", phone="09121234567",
                      created_at=ago(hours=3))
    fake.add_customer(name="علی رضایی", platform="bale", phone="09351112233",
                      created_at=ago(hours=9))
    fake.add_customer(name="مریم حسینی", platform="web", phone="09199887766",
                      created_at=ago(days=1))
    fake.add_customer(name="رضا کریمی", platform="telegram", phone="09121110000",
                      status="approved", person_code=7001, created_at=ago(days=4))
    fake.add_customer(name="سارا احمدی", platform="bale", phone="09362223344",
                      status="rejected", created_at=ago(days=9))
    fake.write_enabled = False

    fake.add_order(id=1041, total=1_250_000.0, user_name="رضا کریمی", created_at=ago(hours=2))
    fake.add_order(id=1040, total=480_000.0, user_name="زهرا محمدی", created_at=ago(hours=6))
    fake.add_order(id=1039, total=2_150_000.0, user_name="علی رضایی", created_at=ago(days=1))
    fake.add_order(id=1038, total=96_000.0, user_name="مریم حسینی",
                   status="awaiting_payment", created_at=ago(days=2))
    fake.add_order(id=1037, total=3_400_000.0, user_name="سارا احمدی", status="written",
                   accounting_order_no=5001, created_at=ago(days=3))
    fake.add_order(id=1036, total=725_000.0, user_name="رضا کریمی", status="approved",
                   created_at=ago(hours=20))

    fake.groups = [
        {"code": 1, "name": "لوازم خانگی"},
        {"code": 2, "name": "مواد غذایی"},
        {"code": 3, "name": "پوشاک"},
    ]
    fake.products = {
        101: {"code": 101, "name": "یخچال فریزر ۳۲ فوت", "group": 1,
              "unit_price": 48_500_000.0, "available_qty": 7.0, "image": None},
        102: {"code": 102, "name": "ماشین لباسشویی ۸ کیلویی", "group": 1,
              "unit_price": 32_900_000.0, "available_qty": 3.0, "image": None},
        103: {"code": 103, "name": "روغن آفتابگردان ۱٫۸ لیتری", "group": 2,
              "unit_price": 185_000.0, "available_qty": 120.0, "image": None},
        104: {"code": 104, "name": "برنج ایرانی هاشمی ۱۰ کیلویی", "group": 2,
              "unit_price": 1_250_000.0, "available_qty": 0.0, "image": None},
        105: {"code": 105, "name": "پیراهن مردانه آستین بلند", "group": 3,
              "unit_price": 890_000.0, "available_qty": 24.0, "image": None},
    }
    fake.persons["09121110000"] = {"code": 7001, "masked_name": "ر*** ک****"}


def build_context(tmp: Path, write_enabled: bool = False, opened: list | None = None):
    store = Store(tmp / "render.db")
    if opened is not None:
        opened.append(store)
    store.configure_connection(FAKE_BASE_URL)
    store.set_setting("wizard_completed", True)
    fake = new_fake()
    seed(fake)
    fake.write_enabled = write_enabled
    client = client_for(fake)
    auth = AuthService(store, client)
    principal = auth.authenticate("owner", OWNER_PASSWORD).principal
    context = AppContext(store=store, auth=auth, api=client, principal=principal)
    context.apply_system_info(
        SystemInfo(accounting_write_enabled=write_enabled, reachable=True)
    )
    return context, store, fake


def settle(app: QApplication, rounds: int = 40) -> None:
    """Pump the event loop until queued background work has finished."""
    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(20_000)
    for _ in range(rounds):
        app.processEvents()
    QThreadPool.globalInstance().waitForDone(5_000)
    for _ in range(rounds):
        app.processEvents()


def grab(widget, path: Path) -> None:
    widget.repaint()
    QApplication.processEvents()
    pixmap = widget.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path), "PNG")
    print(f"  wrote {path.name} ({pixmap.width()}x{pixmap.height()})", flush=True)


def render_all(app: QApplication, tmp: Path, opened: list) -> int:
    # ---- first-run wizard -------------------------------------------------
    store = Store(tmp / "wizard.db")
    opened.append(store)
    wizard = SetupWizard(store, AuthService(store, ShopApiClient()))
    wizard.resize(880, 720)
    wizard.show()
    settle(app, 5)
    grab(wizard, OUT / "01-wizard-step1.png")
    wizard._step = 1
    wizard._update_step()
    wizard.base_url_input.setText("https://192.168.1.10:8443")
    wizard.fingerprint_label.setText("9D17 05D8 EE81 CACC")
    wizard.fingerprint_full.setText(":".join(["9D", "17", "05", "D8"] * 8))
    wizard.cert_box.setVisible(True)
    wizard._show_connection_result("ارتباط با سرور فروشگاه برقرار شد.", ok=True,
                                   detail="پس از پایان، با نام کاربری و گذرواژهٔ خود وارد شوید.")
    settle(app, 5)
    grab(wizard, OUT / "02-wizard-connection.png")
    wizard._step = 2
    wizard._update_step()
    wizard.full_name_input.setText("علی رضایی")
    wizard.new_username_input.setText("owner")
    settle(app, 5)
    grab(wizard, OUT / "03-wizard-admin.png")

    # ---- dialogs over the wizard (they inherit its stylesheet) -----------
    from app.services.connection import MSG_SERVER_UNREACHABLE, unreachable_message
    from app.ui import widgets

    error_dialog = widgets.MessageDialog(
        wizard, "خطای اتصال", "ارتباط با سرور فروشگاه برقرار نشد.", "error",
        detail="نشانی سرور و اتصال شبکه را بررسی کنید.",
    )
    error_dialog.show()
    settle(app, 5)
    grab(error_dialog, OUT / "16-error-dialog.png")
    error_dialog.close()
    unreachable = widgets.ConfirmDialog(
        wizard, MSG_SERVER_UNREACHABLE, unreachable_message("https://192.168.1.10:8443"),
        confirm_text="تلاش دوباره", cancel_text="بستن", kind="warning",
    )
    unreachable.show()
    settle(app, 5)
    grab(unreachable, OUT / "17-server-unreachable.png")
    unreachable.close()
    wizard.close()

    # ---- login ------------------------------------------------------------
    login_store = Store(tmp / "login.db")
    opened.append(login_store)
    login_store.configure_connection(FAKE_BASE_URL)
    login_store.set_setting("wizard_completed", True)
    login = LoginWindow(login_store, AuthService(login_store, client_for(new_fake(), "")))
    login.resize(720, 660)
    login.show()
    settle(app, 5)
    grab(login, OUT / "04-login.png")
    login.close()

    # ---- main window (dry-run banner visible) -----------------------------
    context, main_store, fake = build_context(tmp, write_enabled=False, opened=opened)
    window = MainWindow(context)
    window.resize(1440, 900)
    window.show()

    for key, name, rounds in (
        ("dashboard", "05-dashboard-dryrun.png", 40),
        ("customers", "06-customers.png", 40),
        ("orders", "07-orders.png", 40),
        ("products", "08-products.png", 40),
        ("reports", "09-reports.png", 120),
        ("settings", "10-settings.png", 20),
        ("users", "11-users.png", 40),
        ("server", "14-server.png", 60),
    ):
        window.navigate(key)
        settle(app, rounds)
        grab(window, OUT / name)

    # ---- order detail dialog ---------------------------------------------
    from app.ui.pages.orders import OrderDetailDialog

    dialog = OrderDetailDialog(context, fake.orders[0], window)
    dialog.resize(720, 700)
    dialog.show()
    settle(app, 10)
    grab(dialog, OUT / "12-order-detail.png")
    dialog.close()

    # ---- customer approve dialog -----------------------------------------
    from app.ui.pages.customers import ApproveCustomerDialog

    approve = ApproveCustomerDialog(context, fake.customers[0], window)
    approve.resize(600, 660)
    approve.show()
    settle(app, 40)
    grab(approve, OUT / "13-customer-approve.png")
    approve.close()

    # ---- server setup wizard (first page) ---------------------------------
    from app import server_setup as setup_module
    from app.ui.server_setup_wizard import ServerSetupWizard

    setup_module.is_admin = lambda: True
    setup_module.odbc_driver_installed = lambda driver=None: True
    setup_module.network_is_public = lambda: False
    server_wizard = ServerSetupWizard()
    server_wizard.resize(900, 760)
    server_wizard.show()
    settle(app, 20)
    server_wizard._step = 1
    server_wizard._update()
    server_wizard.db_name.setText("hesab5")
    server_wizard.db_user.setText("shopbot")
    settle(app, 5)
    grab(server_wizard, OUT / "15-server-setup.png")
    server_wizard.close()

    window.close()
    return 0


def main() -> int:
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.apply_theme(app)

    import shutil
    import tempfile

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="shopadmin-render-"))
    opened: list[Store] = []
    try:
        return render_all(app, tmp, opened)
    finally:
        for store in opened:
            try:
                store.close()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
