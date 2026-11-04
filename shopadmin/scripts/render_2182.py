"""v2.18.2: pictures of the changed screens, from the same fake server as the audits, drawn by the
real Windows text engine.

    set QT_QPA_PLATFORM=windows
    python scripts/render_2182.py [output_dir]
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
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens_2.18.2"
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    tmp = Path(tempfile.mkdtemp(prefix="shot2182"))
    from PySide6.QtWidgets import QScrollArea

    from app.ui.main_window import MainWindow

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
        page.rate.setText("8")
        shot(window, "installments_top")
        page.findChild(QScrollArea).verticalScrollBar().setValue(10_000)
        shot(window, "installments_bottom")

        api = context.api                   # made-up people, no accounting data
        api.ledger_databases = lambda: [{"name": "hesab5", "current": True},
                                        {"name": "hesab4", "current": False},
                                        {"name": "hesab3", "current": False}]
        api.ledger_persons = lambda _db, _q="": {"total": 2, "items": [
            {"code": 1201, "name": "مشتری نمونهٔ یک", "national_code": "••••••••۷۸", "phone_tail": "67"},
            {"code": 1202, "name": "مشتری نمونهٔ دو", "national_code": "", "phone_tail": ""}]}
        api.ledger_statement = lambda db, _c: {
            "database": db, "balance": 18_000_000, "side": "debtor", "rows": [
                {"date": "1404/02/11", "kind": "فاکتور فروش", "doc_no": "4410", "description": "فروش کالا",
                 "debit": 25_000_000, "credit": 0, "balance": 25_000_000, "side": "debtor"},
                {"date": "1404/03/02", "kind": "سند", "doc_no": "4522", "description": "دریافت وجه",
                 "debit": 0, "credit": 7_000_000, "balance": 18_000_000, "side": "debtor"}]}
        window.navigate("ledger")
        ledger = window._pages["ledger"]
        screens.settle(app, 800)
        import time
        for _ in range(40):
            time.sleep(0.05)
            screens.settle(app, 5)
        ledger.person_table.select_row(0)
        for _ in range(40):
            time.sleep(0.05)
            screens.settle(app, 5)
        screens.settle(app, 800)
        shot(window, "ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
