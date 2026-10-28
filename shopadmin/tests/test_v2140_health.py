"""v2.14.0 «سلامت سیستم» page."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.ui.main_window import NAV_ITEMS  # noqa: E402
from app.ui.pages import health  # noqa: E402

from .test_ui import ui_context  # noqa: E402,F401


def test_page_shows_checks_and_journal(admin_qapp, ui_context):
    assert any(key == "health" for key, *_rest in NAV_ITEMS)
    page = health.HealthPage(ui_context)
    page._loaded({"checked_at": "2026-10-28T10:00:00+00:00", "checks": [
        {"check": "sql", "label": "SQL", "ok": True, "down": False, "fix": "x"},
        {"check": "disk", "label": "فضای دیسک سرور", "ok": False, "down": True, "fix": "جابه‌جا"}],
        "journal": [{"at": "2026-10-28T10:00:00+00:00", "kind": "fixed", "label": "کارگر تلگرام",
                     "text": "دوباره راه‌اندازی شد", "fix": ""},
                    {"at": "2026-10-28T09:00:00+00:00", "kind": "needs_you", "label": "فضای دیسک",
                     "text": "کم است", "fix": "جابه‌جا"}]})
    assert page.checks_table.rowCount() == 2 and page.checks_table.item(1, 2).text() == "جابه‌جا"
    assert page.journal_table.rowCount() == 2
    assert "خودکار برطرف شد: ۱" in page.counts.text()
    assert health.state_of({"ok": None}) == ("بررسی نمی‌شود", "")
