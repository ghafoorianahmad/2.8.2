"""v2.18.0: pictures of the changed screens, from the same fake server as the audits, drawn by
the real Windows text engine (the sidebar's fault only shows there, not offscreen).

    set QT_QPA_PLATFORM=windows
    python scripts/render_2180.py [output_dir] [group]
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

LONG_ORDER = {"user_name": "محمدرضا طباطبایی نژاد اصفهانی", "total": 1_245_000_000,
              "sazeh_stage": "تحویل به فروش — فاکتور شد", "person_name": "محمدرضا طباطبایی نژاد",
              "user_person_code": 18421}


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens_2.18.0"
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    looks = [screens.DEFAULT_LOOK, ("aurora", "dark", "full")]
    tmp = Path(tempfile.mkdtemp(prefix="shot2180"))
    from app.ui.main_window import MainWindow
    from app.ui.pages import customers

    for look in looks:
        screens.apply_look(app, look)
        suffix = "" if look == screens.DEFAULT_LOOK else f"_{look[0]}_{look[1]}"
        context, _store, fake = screens.build_context(tmp)
        for order in fake.orders:
            order.update(LONG_ORDER)
        window = MainWindow(context)
        window.resize(1360, 900)
        window.show()
        screens.settle(app)

        def shot(widget, name: str) -> None:
            screens.settle(app, 30)
            widget.grab().save(str(out / f"{name}{suffix}.png"))
            print(name + suffix)

        for key in ("orders", "customers", "shop_rules"):
            window.navigate(key)
            page = window._pages[key]
            if hasattr(page, "refresh"):
                page.refresh()
            shot(window, key)

        dialog = customers.ApproveCustomerDialog(context, fake.customers[0], window)
        dialog.resize(760, 760)
        dialog.show()
        screens.settle(app)
        dialog._got_candidates({"national_code": None, "candidates": [
            {"code": 501, "name": "علی رضایی", "score": 100, "verdict": "same", "phone_tail": "47"},
            {"code": 502, "name": "علی رضائی پور", "score": 84, "verdict": "similar",
             "phone_tail": "12"}]})
        shot(dialog, "approve_same_person")
        dialog.close()
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
