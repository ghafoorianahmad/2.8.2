"""Screens for a visual before/after review (v2.7.0): login, orders, price list and
settings, as the manager and as a sales user, against a fake shopapi (no network).

Usage:
    python scripts/review_screens.py <output_dir> <prefix>      # e.g.  ... before
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import render_screens as rs  # noqa: E402
from app.api_client import SystemInfo  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.login_window import LoginWindow  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from tests.conftest import OWNER_PASSWORD  # noqa: E402

SALES_TOKEN = "sales-token-review"
PAGES = (("orders", "orders"), ("pricelist", "pricelist"), ("settings", "settings"))


def seed_prices(fake) -> None:
    fake.add_pricelist(status="active", list_date="1405/07/26")
    fake.add_price_row("17 Pro Max 256 ZAA", "Silver", action="map", kala_code=101,
                       color_label="نقره‌ای")
    fake.add_price_row("17 Pro Max 256 CHA", "Silver", action="map", kala_code=101, auto=True)
    fake.add_price_row("17 Pro Max 256 ZAA", "Orange", action="map", kala_code=101, auto=True)
    fake.add_price_row("Galaxy A57 256GB Ram8", "Lilac/Blue", section="SAMSUNG", kind="ویتنام")
    fake.add_price_row("Redmi Note 15 256GB Ram8", "Black", section="XIAOMI", action="ignore")


def context_for(tmp: Path, opened: list, username: str, token: str):
    store = Store(tmp / f"{username}.db")
    opened.append(store)
    store.configure_connection(rs.FAKE_BASE_URL)
    store.set_setting("wizard_completed", True)
    fake = rs.new_fake()
    fake.add_staff("sales1", OWNER_PASSWORD, "operator", "مینا فروش")
    fake.issue_token("sales1", SALES_TOKEN)
    rs.seed(fake)
    seed_prices(fake)
    client = rs.client_for(fake, token)
    auth = AuthService(store, client)
    principal = auth.authenticate(username, OWNER_PASSWORD).principal
    context = AppContext(store=store, auth=auth, api=client, principal=principal)
    context.apply_system_info(SystemInfo(accounting_write_enabled=False, reachable=True))
    return context


def render(app: QApplication, out: Path, prefix: str, tmp: Path, opened: list) -> None:
    login_store = Store(tmp / "login.db")
    opened.append(login_store)
    login_store.configure_connection(rs.FAKE_BASE_URL)
    login_store.set_setting("wizard_completed", True)
    login = LoginWindow(login_store, AuthService(login_store, rs.client_for(rs.new_fake(), "")))
    login.resize(1100, 700)
    login.show()
    rs.settle(app, 5)
    rs.grab(login, out / f"{prefix}_01_login.png")
    login.close()

    for who, username, token in (("admin", "owner", rs.OWNER_TOKEN),
                                 ("sales", "sales1", SALES_TOKEN)):
        context = context_for(tmp, opened, username, token)
        window = MainWindow(context)
        window.resize(1366, 820)
        window.show()
        rs.settle(app, 40)
        rs.grab(window, out / f"{prefix}_{who}_00_after_login.png")
        for number, (key, name) in enumerate(PAGES, start=2):
            window.navigate(key)
            rs.settle(app, 60)
            rs.grab(window, out / f"{prefix}_{who}_{number:02d}_{name}.png")
        extras(app, out, prefix, who, context, window)
        window.close()


def extras(app, out: Path, prefix: str, who: str, context, window) -> None:
    """The order dialog (and, where they exist, the courier dialog and user form)."""
    from app.ui.pages.orders import OrderDetailDialog

    orders = context.api.list_orders("receipt_uploaded")
    if orders:
        dialog = OrderDetailDialog(context, orders[0], window)
        dialog.resize(760, 720)
        dialog.show()
        rs.settle(app, 10)
        rs.grab(dialog, out / f"{prefix}_{who}_05_order_dialog.png")
        dialog.close()
    try:
        from app.ui.pages.orders import ShipDialog
    except ImportError:
        ShipDialog = None
    if ShipDialog is not None and who == "sales":
        ship = ShipDialog(window, "۱۰۴۱")
        ship.name_input.setText("علی پیک")
        ship.phone_input.setText("۰۹۱۲۳۴۵۶۷۸۹")
        ship.show()
        rs.settle(app, 5)
        rs.grab(ship, out / f"{prefix}_{who}_06_ship_dialog.png")
        ship.close()
    if who == "admin" and "users" in getattr(window, "_pages", {}):
        from app.ui.pages.users import UserFormDialog

        form = UserFormDialog(context, None, window)
        form.resize(720, 760)
        form.show()
        rs.settle(app, 5)
        rs.grab(form, out / f"{prefix}_{who}_06_new_user_form.png")
        form.close()


def main() -> int:
    out = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "shot"
    mode = sys.argv[3] if len(sys.argv) > 3 else ""
    app = QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    if mode and hasattr(theme, "set_mode"):
        theme.apply_theme(app, mode)
    else:
        theme.apply_theme(app)
    import shutil
    import tempfile

    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="shopadmin-review-"))
    opened: list = []
    try:
        render(app, out, prefix, tmp, opened)
    finally:
        for store in opened:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
