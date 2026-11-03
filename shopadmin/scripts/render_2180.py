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

from PySide6.QtWidgets import QPushButton  # noqa: E402

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

        # the finished orders with their ticks, then the archive
        for order in fake.orders:
            order["status"] = "written"
        window.navigate("orders")
        page = window._pages["orders"]
        for button in page.findChildren(QPushButton):
            if button.text() == "ثبت‌شده در حسابداری":
                button.click()
        screens.settle(app)
        if page.table.rowCount():
            page.table.set_check(0, True, keep_text=True)
        shot(window, "orders_written_ticks")
        window.navigate("archive")
        shot(window, "archive")

        # posts of the channel, with each result
        fake.price_notes = [
            {"id": 3, "kind": "correction", "posted_at": "2026-11-03T09:40:00",
             "text": "A17 128/8 مشکی 95,500", "result": {"applied": 1},
             "changes": [{"description": "Galaxy A17 128/8", "color": "مشکی",
                          "old_naghd": 92500, "new_naghd": 95500}]},
            {"id": 2, "kind": "uncertain", "posted_at": "2026-11-03T09:20:00",
             "text": "ردمی ۱۵ قیمت جدید 72,000", "result": {"items": [{"price": 72000}]}},
            {"id": 1, "kind": "ignored", "posted_at": "2026-11-03T09:00:00",
             "text": "صبح بخیر همکاران", "result": {}},
        ]
        fake.proxies = [
            {"id": 1, "host": "fast.example", "port": 443, "kind": "ee", "state": "main",
             "source": "manual", "stability": 0.93, "good_days": 14, "checked_days": 15,
             "last_ok_at": "2026-11-03T10:00:00", "failing_now": False},
            {"id": 2, "host": "collected.example", "port": 8443, "kind": "dd", "state": "probation",
             "source": "channel:@ProxyMTProto", "stability": 0.6, "good_days": 3, "checked_days": 5,
             "last_ok_at": "2026-11-02T22:00:00", "failing_now": False},
            {"id": 3, "host": "down.example", "port": 443, "kind": "ee", "state": "retired",
             "source": "channel:@ProxyMTProto", "stability": 0.0, "good_days": 0, "checked_days": 2,
             "last_ok_at": None, "failing_now": True},
        ]
        window.navigate("pricelist")
        page = window._pages["pricelist"]
        page.tabs.setCurrentIndex(2)
        screens.settle(app)
        shot(window, "price_notes")
        page.tabs.setCurrentIndex(3)
        screens.settle(app)
        page.proxy_table.set_check(2, True, keep_text=True)
        shot(window, "proxies")

        # the colleagues' chat
        api = context.api
        api.chat_rooms = lambda: {"rooms": [
            {"room": "public", "name": "گفت‌وگوی عمومی", "unread": 2},
            {"room": "dm:1:2", "name": "زهرا احمدی", "unread": 0}]}
        api.chat_messages = lambda room, after=0: [] if after else [
            {"id": 1, "sender_name": "زهرا احمدی", "created_at": "2026-11-03T09:10:00",
             "text": "فاکتور سفارش ۱۰۴۱ آماده است؟"},
            {"id": 2, "sender_name": "مالک فروشگاه", "mine": True,
             "created_at": "2026-11-03T09:12:00", "text": "بله، همین الان ثبت شد."},
            {"id": 3, "sender_name": "زهرا احمدی", "created_at": "2026-11-03T09:13:00",
             "voice": True, "voice_seconds": 8}]
        window.navigate("staff_chat")
        screens.settle(app)
        shot(window, "staff_chat")

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
