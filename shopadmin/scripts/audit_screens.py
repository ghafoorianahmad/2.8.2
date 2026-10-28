"""v2.9.3: every screen of ShopAdmin, one after another, for the audits.

``text_fit_audit.py``, ``rtl_audit.py`` and ``button_audit.py`` (and
``render_dialogs.py`` for screenshots) walk the same list: the main window and
every page (as «مدیر» and as «کاربر فروش», wide and narrow), every dialog
(filled with realistic data from a fake shopapi, no network), the sign-in
window, the first-run wizard and every step of the server setup — in one look
(palette × light / dark / follow Windows × «جلوه‌ها»).

    for where, widget in iter_screens(app, tmp):
        problems += check(widget, where)

A dialog that cannot be built is reported as a problem (an audit never skips a
screen silently).
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Iterator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import render_screens as rs  # noqa: E402
from app import permissions as perms  # noqa: E402
from app.statuses import ROLE_OPERATOR  # noqa: E402
from app.ui import theme  # noqa: E402

#: every look (palette × light / dark / follow Windows); «جلوه‌ها» alternate
LOOKS = [(palette, mode, "full" if index % 2 == 0 else "simple")
         for index, (palette, mode) in enumerate(
             (p, m) for p in theme.PALETTE_NAMES for m in theme.THEME_MODES)]
DEFAULT_LOOK = ("ocean", "light", "full")

#: problems found while building the screens (a dialog that raised)
BUILD_PROBLEMS: list[str] = []

LONG_NAME = "SAMSUNG Galaxy S26 Ultra 512GB 12GB RAM — Titanium Silverblue (ZAA) — گارانتی ۱۸ ماهه"


#: v2.9.4: what the server answers for the two «ابزارها» dialogs (no real server)
SAMPLE_STATUS_CODES = {
    "ok": True, "database": "hesab5 t",
    "statuses": [{"status": None, "internet": True, "count": 41, "last_order": 1290,
                  "last_date": "1405/08/03"},
                 {"status": 1, "internet": False, "count": 1180, "last_order": 1288,
                  "last_date": "1405/08/03"},
                 {"status": 3, "internet": False, "count": 66, "last_order": 1201,
                  "last_date": "1405/07/20"}],
    "latest_sazeh": [{"order": 1288 - i, "date": "1405/08/03", "status": 1 if i % 3 else 3,
                      "user_code": 2, "total": 52_500_000 * (i + 1), "items": i % 4 + 1}
                     for i in range(8)],
}
SAMPLE_CLEANUP = {
    "counts": {"orders": 37, "order_items": 52, "payments": 30, "item_requests": 9,
               "item_request_messages": 14, "inquiries": 3, "users": 6, "events": 410,
               "activity_log": 220, "staff": 2, "conversations": 6, "carts": 2,
               "receipt_files": 28},
    "owners": ["owner"], "staff_removed": ["sara", "test1"], "backup_fresh": False,
    "confirm_text": "پاک‌سازی",
    "labels": {"orders": "سفارش", "order_items": "قلم سفارش", "payments": "پرداخت/رسید",
               "item_requests": "درخواست خرید و کالا", "item_request_messages": "پیام درخواست",
               "inquiries": "استعلام", "users": "مشتری (با پیوند ربات)", "events": "اعلان",
               "activity_log": "گزارش فعالیت", "staff": "کاربر کارمند (غیرمدیر کل)",
               "conversations": "گفت‌وگوی ربات", "carts": "سبد خرید ربات",
               "receipt_files": "فایل تصویر رسید"},
}


def seed_more(fake) -> None:
    """Data that exercises long and mixed (Persian + Latin) text."""
    from tests.conftest import TS

    order = fake.add_order(id=1042, total=1_480_000_000.0, user_name="Ahmad Rezaei",
                           user_phone="09121234567", status="awaiting_payment",
                           created_at=TS, request_id=7,
                           items=[{"kala_code": 5012, "name": LONG_NAME, "qty": 1.0,
                                   "unit_price": 1_480_000_000.0}])
    fake.timelines[("order", order["id"])] = [
        {"action": "price_offer", "actor_name": "ahmad", "ts": TS},
        {"action": "offer_accept", "ts": TS},
        {"action": "payment_info", "actor_name": "ahmad", "ts": TS},
        {"action": "assign", "actor_name": "ahmad", "to_name": "Sara Karimi", "ts": TS},
        {"action": "note", "actor_name": "Sara Karimi", "ts": TS},
    ]
    fake.item_requests.extend([
        {"id": 7, "kind": "purchase", "status": "seen", "text": "Galaxy S26 Ultra می‌خواهم",
         "customer_name": "Ahmad Rezaei", "customer_phone": "09121234567", "platform": "bale",
         "person_code": 7001, "created_at": TS, "product_name": LONG_NAME, "kala_code": 5012,
         "color": "Titanium Silverblue", "part": "ZAA", "price_rial": 1_480_000_000,
         "qty": 1, "owned_by_me": True, "admin_note": "ahmad گفت فردا موجود می‌شود"},
        {"id": 8, "kind": "unavailable", "status": "new", "text": "شارژر Anker 65W دارید؟",
         "customer_name": "مریم حسینی", "customer_phone": "09199887766", "platform": "bale",
         "person_code": None, "created_at": TS},
    ])
    fake.item_request_messages[7] = [
        {"id": 1, "request_id": 7, "status": "sent", "error": "", "created_at": TS,
         "created_by": "ahmad", "sent_at": TS,
         "text": "سلام، Galaxy S26 Ultra با رنگ Titanium Silverblue موجود است و قیمت امروز آن "
                 "۱۴۸ میلیون تومان است. اگر تأیید کنید سفارش ثبت می‌شود و اطلاعات پرداخت "
                 "برایتان فرستاده می‌شود."},
        {"id": 2, "request_id": 7, "status": "failed", "error": "پیام‌رسان در دسترس نبود",
         "created_at": TS, "created_by": "Sara Karimi", "sent_at": None, "text": "ok?"},
    ]
    fake.timelines[("request", 7)] = fake.timelines[("order", order["id"])][:2]
    fake.proxies.extend([
        {"id": 1, "host": "proxy-serving.mozitop-network.example.com", "port": 443,
         "kind": "ee", "state": "main", "source": "channel:ProxyMTProto", "last_ok_at": TS,
         "last_latency_ms": 820, "failing_now": False},
        {"id": 2, "host": "203.0.113.45", "port": 8443, "kind": "dd", "state": "probation",
         "source": "manual", "last_ok_at": None, "last_fail_at": TS, "failing_now": True},
    ])
    fake.add_price_row("S26 Ultra 512 12 ZAA", "Titanium Silverblue", section="SAMSUNG")
    fake.add_price_row("17 Pro Max 256", "Deep Blue", action="map", kala_code=5012)
    fake.add_pricelist()
    model = fake.add_catalog_model("galaxy-s26-ultra", "Galaxy S26 Ultra", "Samsung")
    fake.add_catalog_item(model["id"], 5012, LONG_NAME, label="512 گیگ")
    fake.add_catalog_model("iphone-17-pro", "iPhone 17 Pro", "Apple")


def seed_site(root: Path) -> None:
    """v2.11.0: the «سایت» data of this computer, with long mixed text and photos."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    from app.site.store import SiteStore

    def photo(color: str) -> bytes:
        image = QImage(400, 320, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(raw.data())

    store = SiteStore(root)
    if not store.is_empty():
        return
    store.add_photo("galaxy-s26-ultra.jpg", photo("#5b4bb8"))
    store.upsert({"code": "galaxy-s26-ultra", "category": "phone", "brand": "samsung",
                  "name": "Galaxy S26 Ultra", "tier": "پرچمدار", "release_year": 2026,
                  "image": "galaxy-s26-ultra.jpg",
                  "colors": [{"name": "بنفش کبالت"}, {"name": "تیتانیوم آبی نقره‌ای"}],
                  "specs": [["نمایشگر", "6.9 اینچ Dynamic AMOLED 2X، 120Hz"],
                            ["پردازنده", "Snapdragon 8 Elite Gen 5 for Galaxy"]]})
    store.upsert({"code": "iphone-17-pro", "category": "phone", "brand": "apple",
                  "name": "iPhone 17 Pro", "colors": [{"name": "نارنجی کیهانی"}], "hidden": True})
    store.upsert({"code": "anker-737-power-bank", "category": "accessory", "group": "powerbank",
                  "name": "پاوربانک Anker 737 (PowerCore 24K) 140W", "brand_name": "Anker",
                  "specs": [["ظرفیت", "24000 میلی‌آمپر ساعت"]],
                  "description": "شارژ سریع لپ‌تاپ و گوشی با نمایشگر هوشمند"})
    # v2.12.0 «ظاهر و چیدمان»: a logo, a banner picture, featured phones, long store text
    logo, _n = store.add_look_photo("logo", photo("#ff8800"))
    banner, _n = store.add_look_photo("banner", photo("#118866"))

    def look(value):
        value.update(palette="emerald", logo=logo, featured=["galaxy-s26-ultra", "iphone-17-pro"])
        value["hero"]["images"] = [banner]
        value["sections"][5]["show"] = False
        value["store"]["map"] = "https://nshn.ir/abcdefghijkl"

    store.update_look(look)


def build_context(tmp: Path):
    context, store, fake = rs.build_context(tmp)
    seed_more(fake)
    seed_site(Path(store.path).parent / "site")
    return context, store, fake


def settle(app, rounds: int = 10) -> None:
    rs.settle(app, rounds)


def _placeholder_pdf() -> bytes:
    from tests.placeholder_pdf import PLACEHOLDER_PDF_PAGES, _pdf

    return _pdf(PLACEHOLDER_PDF_PAGES)


def _dialogs(context, fake, window) -> Iterator[tuple[str, object]]:
    """(name, factory) of every dialog, filled with the fake data."""
    from PySide6.QtGui import QPixmap

    from app.ui import widgets
    from app.ui.main_window import NotificationDialog
    from app.ui.pages import catalog_models as cm
    from app.ui.pages import customers, item_requests, orders, pricelist, products, users

    order_rows = [o for o in fake.orders if isinstance(o, dict)]
    by_status = {}
    for row in order_rows:
        by_status.setdefault(row.get("status"), row)
    for status, row in sorted(by_status.items(), key=lambda kv: str(kv[0])):
        yield f"order {status}", lambda r=row: orders.OrderDetailDialog(context, r, window)
    long_order = next(o for o in order_rows if o["id"] == 1042)
    yield "order long name", lambda: orders.OrderDetailDialog(context, long_order, window)
    yield "payment info", lambda: orders.PaymentInfoDialog(window, context, long_order)
    yield "ship", lambda: orders.ShipDialog(window, "۱۲")
    yield "assign", lambda: orders.AssignDialog(context, window, "سفارش ۱۲")
    yield "reject payment", lambda: orders.RejectPaymentDialog(window, "۱۲")
    if hasattr(orders, "CancelOrderDialog"):
        yield "cancel order", lambda: orders.CancelOrderDialog(window, "۱۲")
    pixmap = QPixmap(240, 320)
    pixmap.fill(theme_color("#DDE3EC"))
    yield "receipt image", lambda: orders.ReceiptImageDialog(pixmap, "۱۲", window)
    for request in fake.item_requests:
        yield (f"request {request['id']} {request.get('kind')}",
               lambda r=request: item_requests.ItemRequestDialog(context, r, window))
    yield "stock confirm", lambda: item_requests.StockConfirmDialog(window, fake.item_requests[0])
    yield "approve customer", lambda: customers.ApproveCustomerDialog(context, fake.customers[0],
                                                                      window)
    yield "reject customer", lambda: customers.RejectCustomerDialog(window, "زهرا محمدی")
    product = next(iter(fake.products.values()))
    yield "product detail", lambda: products.ProductDetailDialog(context, product, "لوازم خانگی",
                                                                 window)
    row = fake.price_rows[0] if fake.price_rows else {}
    yield "map price row", lambda: pricelist.MapRowDialog(context, row, window)
    yield "add proxy", lambda: pricelist.AddProxyDialog(window)
    model = fake._catalog_out(fake.catalog_models[0])
    yield "pick product", lambda: cm.PickProductDialog(context, model, parent=window)
    yield "text dialog", lambda: cm.TextDialog("نام‌های دیگر", "هر نام در یک خط", "Galaxy S26",
                                                multiline=True, parent=window)
    # v2.11.0 «سایت» (local data, no server)
    from app.site.store import SiteStore
    from app.ui import site_dialogs as sd

    site = SiteStore(Path(context.store.path).parent / "site")
    yield "site phone new", lambda: sd.PhoneDialog(site, parent=window)
    yield "site phone edit", lambda: sd.PhoneDialog(site, site.get("galaxy-s26-ultra"), parent=window)
    yield "site accessory", lambda: sd.AccessoryDialog(site, site.get("anker-737-power-bank"),
                                                       parent=window)
    yield "site accessory pdf", lambda: sd.AccessoryPdfDialog(site, _placeholder_pdf(), window)
    from app.ui import site_import as si
    yield "site pdf import", lambda: si.PdfImportDialog(site, "powerbank", _placeholder_pdf(),
                                                        file_name="list.pdf", parent=window)
    from app.ui import site_look as sl

    yield "site pick featured", lambda: sl.PickPhonesDialog(
        [p for p in site.items("phone")] + [{"code": "x-long", "name": LONG_NAME}], 8, window)
    staff = [users_row for users_row in fake.staff.values()]
    yield "user form new", lambda: users.UserFormDialog(context, None, window)
    yield "user form edit", lambda: users.UserFormDialog(context, fake.staff_out(staff[1]), window)
    yield "reset password", lambda: users.ResetPasswordDialog(window, "sara")
    yield "transfer", lambda: users.TransferDialog(window, fake.staff_out(staff[1]),
                                                   [fake.staff_out(s) for s in staff[2:]])
    yield "notifications and look", lambda: NotificationDialog(context, window)
    from app.ui.password_dialog import ChangeOwnPasswordDialog

    yield "change password", lambda: ChangeOwnPasswordDialog(context, window)
    yield "message error", lambda: widgets.MessageDialog(
        window, "خطای اتصال", "ارتباط با سرور فروشگاه برقرار نشد.", "error",
        detail="نشانی سرور و اتصال شبکه را بررسی کنید.")
    yield "message info", lambda: widgets.MessageDialog(window, "قیمت فرستاده شد",
                                                        "قیمت در ربات برای مشتری فرستاده شد.",
                                                        "success")
    yield "confirm", lambda: widgets.ConfirmDialog(
        window, "لغو سفارش", "سفارش ۱۲ لغو شود؟", confirm_text="بله، لغو کن",
        cancel_text="انصراف", kind="warning")
    try:
        from app.ui.telegram_login import TelegramLoginDialog
    except ImportError:
        TelegramLoginDialog = None
    if TelegramLoginDialog is not None:
        yield "telegram login", lambda: TelegramLoginDialog(window)
        for step in (1, 2, 3):
            def make(step=step):
                dialog = TelegramLoginDialog(window)
                dialog._go(step)
                return dialog
            yield f"telegram login step {step}", make


def theme_color(value: str):
    from PySide6.QtGui import QColor

    return QColor(value)


def _show(app, widget, where: str):
    from app.ui import widgets

    if hasattr(widget, "exec") and hasattr(widget, "setModal"):
        widgets.make_responsive(widget)
    widget.show()
    settle(app)
    return where, widget


def _close(widget) -> None:
    try:
        widget.close()
        widget.deleteLater()
    except RuntimeError:
        pass


def iter_screens(app, tmp: Path, *, roles=("manager", "sales"),
                 sizes=((1360, 840), (1000, 700)), dialogs: bool = True,
                 extra: bool = True, tag: str = "") -> Iterator[tuple[str, QWidget]]:
    """Every screen, shown and settled; the caller checks it before the next one."""
    from PySide6.QtCore import QCoreApplication, QEvent

    from app.ui.main_window import NAV_ITEMS, MainWindow

    context, store, fake = build_context(tmp)
    sales_perms = perms.client_permissions(sorted(perms.SALES_SERVER_PERMISSIONS))
    try:
        for role in roles:
            if role == "sales":
                context.principal = replace(context.principal, role=ROLE_OPERATOR,
                                            permissions=sales_perms)
            for width, height in sizes:
                window = MainWindow(context)
                window.resize(width, height)
                window.show()
                settle(app)
                yield f"{tag} {role} {width} top/sidebar", window
                for key, _text, _icon, _perm in NAV_ITEMS:
                    if key not in window._pages:
                        continue
                    window.navigate(key)
                    settle(app)
                    yield f"{tag} {role} {width} {key}", window._pages[key]
                    # v2.14.0: «سایت › کالاها» on an accessory category (the other panel)
                    page = window._pages[key]
                    if hasattr(page, "tree") and hasattr(page, "_tree_items"):
                        for item in page._tree_items():
                            if list(item.data(0, Qt.ItemDataRole.UserRole))[0] == "group":
                                page.tree.setCurrentItem(item)
                                settle(app)
                                yield f"{tag} {role} {width} {key} accessories", page
                                page.tree.setCurrentItem(page.tree.topLevelItem(0))
                                settle(app)
                                break
                    # v2.11.0: every tab of a page with tabs («سایت»)
                    tabs = getattr(window._pages[key], "tabs", None)
                    for index in range(1, tabs.count() if tabs is not None else 0):
                        tabs.setCurrentIndex(index)
                        settle(app)
                        yield f"{tag} {role} {width} {key} tab {index}", window._pages[key]
                        # v2.12.0: the inner tabs of «ظاهر و چیدمان»
                        inner = getattr(tabs.currentWidget(), "tabs", None)
                        for sub in range(1, inner.count() if inner is not None else 0):
                            inner.setCurrentIndex(sub)
                            settle(app)
                            yield (f"{tag} {role} {width} {key} tab {index}.{sub}",
                                   window._pages[key])
                        if inner is not None:
                            inner.setCurrentIndex(0)
                    if tabs is not None:
                        tabs.setCurrentIndex(0)
                _close(window)
        if dialogs:
            context.principal = replace(context.principal, role="super_admin", permissions=None)
            window = MainWindow(context)
            window.resize(1360, 840)
            window.show()
            settle(app)
            for name, factory in _dialogs(context, fake, window):
                try:
                    dialog = factory()
                except Exception as exc:  # noqa: BLE001 - an audit never skips a screen
                    BUILD_PROBLEMS.append(f"{tag} dialog {name}: not built ({type(exc).__name__}: "
                                          f"{exc})")
                    continue
                yield _show(app, dialog, f"{tag} dialog {name}")
                _close(dialog)
            _close(window)
        if extra:
            yield from _extra_screens(app, tmp, tag)
    finally:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        store.close()


def _extra_screens(app, tmp: Path, tag: str) -> Iterator[tuple[str, QWidget]]:
    """Sign-in, the first-run wizard and every step of the server setup."""
    from app import server_setup as setup_module
    from app.api_client import ShopApiClient
    from app.auth import AuthService
    from app.store import Store
    from app.ui.forgot_dialog import ForgotPasswordDialog
    from app.ui.login_window import LoginWindow
    from app.ui.wizard import SetupWizard

    store = Store(tmp / "extra.db")
    try:
        store.configure_connection(rs.FAKE_BASE_URL)
        store.set_setting("wizard_completed", True)
        auth = AuthService(store, rs.client_for(rs.new_fake(), ""))
        login = LoginWindow(store, auth)
        login.resize(980, 640)
        yield _show(app, login, f"{tag} login")
        _close(login)
        forgot = ForgotPasswordDialog(auth, "sara")
        yield _show(app, forgot, f"{tag} dialog forgot password")
        _close(forgot)
        wizard_store = Store(tmp / "wizard.db")
        try:
            wizard = SetupWizard(wizard_store, AuthService(wizard_store, ShopApiClient()))
            wizard.resize(880, 720)
            for step in range(3):
                wizard._step = step
                wizard._update_step()
                yield _show(app, wizard, f"{tag} first-run wizard step {step + 1}")
            _close(wizard)
        finally:
            wizard_store.close()
        for name, value in (("is_admin", lambda: True),
                            ("odbc_driver_installed", lambda driver=None: True),
                            ("network_is_public", lambda: False),
                            ("existing_config_port", lambda: None),
                            ("read_current_config", lambda: None),
                            ("lan_addresses", lambda: ["192.168.1.10"]),
                            ("server_installed_here", lambda: False),
                            ("telegram_logged_in", lambda: False),
                            # v2.9.4: never the real ShopSystem / server in an audit
                            ("list_databases", lambda *a, **k: ["hesab5", "hesab5 t"]),
                            ("current_owners", lambda *a, **k: [{"username": "owner"}]),
                            ("cleanup_preview", lambda *a, **k: SAMPLE_CLEANUP),
                            ("order_status_codes", lambda *a, **k: SAMPLE_STATUS_CODES),
                            ("service_db_check", lambda *a, **k: None)):
            if hasattr(setup_module, name):
                setattr(setup_module, name, value)
        from app.ui.server_setup_wizard import ServerSetupWizard

        server_wizard = ServerSetupWizard()
        server_wizard.resize(900, 760)
        for index, key in enumerate(server_wizard._steps):
            server_wizard._step = index
            server_wizard._update()
            yield _show(app, server_wizard, f"{tag} server setup {key}")
        _close(server_wizard)
        # v2.9.4: «تنظیمات سرور» (current values, «مدیر کل فعلی», «ابزارها»)
        setup_module.read_current_config = lambda: setup_module.CurrentConfig(
            db_server=r".\SQLEXPRESS", db_name="hesab5", db_user="shopbot",
            db_password_set=True, allowed_databases=["hesab5 t"], write_databases=[])
        settings_wizard = ServerSetupWizard(mode="settings")
        settings_wizard.resize(900, 760)
        for index, key in enumerate(settings_wizard._steps):
            if key not in ("database", "admin", "tools"):
                continue
            settings_wizard._step = index
            settings_wizard._update()
            yield _show(app, settings_wizard, f"{tag} server settings {key}")
        from app.ui.cleanup_dialog import CleanupDialog
        from app.ui.status_codes import StatusCodesDialog

        dialog = StatusCodesDialog(settings_wizard, lambda: SAMPLE_STATUS_CODES)
        yield _show(app, dialog, f"{tag} dialog status codes")
        _close(dialog)
        dialog = CleanupDialog(settings_wizard, port=8443)
        yield _show(app, dialog, f"{tag} dialog cleanup")
        _close(dialog)
        _close(settings_wizard)
    finally:
        store.close()


def apply_look(app, look: tuple[str, str, str]) -> str:
    palette, mode, effects = look
    theme.apply_theme(app, mode, palette=palette, effects=effects)
    return f"[{palette}/{mode}/{effects}]"


def looks_from_argv(argv: list[str]) -> list[tuple[str, str, str]]:
    return [DEFAULT_LOOK] if "--quick" in argv else LOOKS


def app_instance() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)
