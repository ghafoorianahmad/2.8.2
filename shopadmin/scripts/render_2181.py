"""v2.18.1: pictures of the changed screens, from the same fake server as the audits, drawn by the
real Windows text engine.

    set QT_QPA_PLATFORM=windows
    python scripts/render_2181.py [output_dir]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_screens as screens  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens_2.18.1"
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    tmp = Path(tempfile.mkdtemp(prefix="shot2181"))
    from PySide6.QtWidgets import QScrollArea

    from app.ui.main_window import MainWindow
    from app.ui.pages import customers
    from app.ui.pages.installments import QuoteHistoryDialog

    card = out / "installment_card.png"
    for look in (screens.DEFAULT_LOOK, ("aurora", "dark", "full")):
        screens.apply_look(app, look)
        suffix = "" if look == screens.DEFAULT_LOOK else f"_{look[0]}_{look[1]}"
        context, _store, fake = screens.build_context(tmp)
        window = MainWindow(context)
        window.resize(1360, 900)
        window.show()
        screens.settle(app)

        def shot(widget, name: str) -> None:
            screens.settle(app, 30)
            widget.grab().save(str(out / f"{name}{suffix}.png"))

        window.navigate("installments")
        page = window._pages["installments"]
        page.phone_name.setText("Galaxy S25 Ultra 512 مشکی")
        page.price.setText("200000000")
        page.down_input.setText("100000000")
        page.months.setValue(5)
        page.rate.setText("8")
        screens.settle(app)
        shot(window, "installments_1_inputs")
        scroll = page.findChild(QScrollArea)
        bar = scroll.verticalScrollBar()
        page.schedule.item(0, 2).setText("۲۹٬۰۰۰٬۰۰۰")
        page.round_choice.setCurrentIndex(2)
        bar.setValue(page.reset_button.mapTo(scroll.widget(), page.reset_button.rect().topLeft()).y() - 340)
        shot(window, "installments_2_edited")
        bar.setValue(page.schedule.mapTo(scroll.widget(), page.schedule.rect().topLeft()).y() - 60)
        shot(window, "installments_3_schedule")
        bar.setValue(page.compare.mapTo(scroll.widget(), page.compare.rect().topLeft()).y() - 60)
        shot(window, "installments_4_compare")
        if card.is_file():
            page.card_preview.setVisible(True)
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPixmap
            page.card_preview.setPixmap(QPixmap(str(card)).scaledToWidth(
                420, Qt.TransformationMode.SmoothTransformation))
            screens.settle(app)
        bar.setValue(bar.maximum())
        shot(window, "installments_5_output")

        history = QuoteHistoryDialog(context, window)
        history._got([{"created_at": "2026-11-04T09:12:00", "actor": "زهرا احمدی", "customer_name": "علی رضایی",
                       "phone_name": "Galaxy S25 Ultra", "down": 100_000_000, "checks": [28_000_000] * 5,
                       "interest": 40_000_000, "grand_total": 240_000_000, "status": "sent"},
                      {"created_at": "2026-11-04T08:40:00", "actor": "مالک فروشگاه", "customer_name": "",
                       "phone_name": "iPhone 17 Pro", "down": 300_000_000, "checks": [55_000_000] * 12,
                       "interest": 180_000_000, "grand_total": 960_000_000, "status": "saved"}])
        history.show()
        shot(history, "installments_history")
        history.close()

        window.navigate("shop_rules")
        rules = window._pages["shop_rules"]
        rules._got_installment({"rate": "8", "customer_enabled": False})
        rules._scroll.ensureWidgetVisible(rules.installment_panel)
        shot(window, "shop_rules_installment")

        # item 16: without the tick
        dialog = customers.ApproveCustomerDialog(context, {
            **fake.customers[0], "first_name": "علی", "last_name": "رضایی",
            "national_code": "••••••••99", "address": "", "national_code_on_file": True,
            "address_on_file": True, "private_hidden": True}, window)
        dialog.resize(760, 700)
        dialog.show()
        shot(dialog, "customer_private_hidden")
        dialog.close()
        window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
