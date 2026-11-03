"""v2.17.0: pictures of the new screens, from the same fake server as the audits.

    python scripts/render_2170.py [output_dir]
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import audit_screens as screens
from app import permissions as perms
from app.statuses import ROLE_OPERATOR

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens_2.17.0"
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    screens.apply_look(app, screens.DEFAULT_LOOK)
    tmp = Path(tempfile.mkdtemp(prefix="shot2170"))
    context = screens.build_context(tmp)[0]
    from app.ui.main_window import MainWindow
    from app.ui.pages import item_requests, orders, users

    window = MainWindow(context)
    window.resize(1360, 900)
    window.show()
    screens.settle(app)

    def shot(widget, name: str) -> None:
        screens.settle(app, 30)
        widget.grab().save(str(out / f"{name}.png"))
        print(name)

    for key, name in (("shop_rules", "shop_rules"), ("dashboard", "dashboard_alerts"),
                      ("orders", "orders_stage"), ("users", "users_mobile")):
        window.navigate(key)
        page = window._pages[key]
        page.refresh() if hasattr(page, "refresh") else None
        shot(window, name)

    order = {"id": 123, "status": "approved", "total": 245000000, "items": [],
             "accounting_pending": True, "created_at": "2026-11-02T10:00:00+00:00",
             "ship_address": "تهران، خیابان ولیعصر، بالاتر از میدان ونک، کوچهٔ بهار، پلاک 12",
             "payer_name": "حسین احمدی", "user_name": "علی رضایی", "owned": True,
             "owned_by_me": True}
    dialog = orders.OrderDetailDialog(context, order, window)
    dialog.resize(1000, 860)
    dialog.show()
    shot(dialog, "order_waits_for_accounting")
    dialog.close()

    first = orders.FirstReceiptDialog(window, "علی رضایی")
    first.show()
    shot(first, "first_receipt_1")
    first._different()
    first.payer_input.setText("حسین احمدی")
    shot(first, "first_receipt_2_not_the_same")
    first.close()

    closing = item_requests.CloseRequestDialog(window, {"product_name": "آیفون ۱۷ پرو مکس"})
    closing.show()
    shot(closing, "close_request_asks_for_message")
    closing.close()

    form = users.UserFormDialog(context, None, window)
    form.resize(820, 900)
    form.show()
    shot(form, "user_form_all_ticks")
    form.close()
    window.close()

    # a new sales user: daily work only
    sales = screens.build_context(Path(tempfile.mkdtemp(prefix="shot2170s")))[0]
    sales.principal = replace(sales.principal, role=ROLE_OPERATOR, permissions=perms.client_permissions(
        sorted(perms.with_implied(perms.SALES_SERVER_PERMISSIONS))))
    window = MainWindow(sales)
    window.resize(1360, 900)
    window.show()
    shot(window, "new_sales_user_menu")
    window.close()
    print("saved in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
