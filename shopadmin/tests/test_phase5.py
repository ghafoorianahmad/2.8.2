"""Phase 5: backup status row and tray texts for backup / security alerts."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.notifications import notice_for  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.pages.server import backup_text, health_text  # noqa: E402

AT = "2026-10-12T03:00:00+00:00"


def test_backup_notices():
    down = notice_for({"kind": "health_backup_down"})
    assert down.warning and down.is_server and "پشتیبان" in down.body
    up = notice_for({"kind": "health_backup_up"})
    assert not up.warning and "موفق" in up.body
    alert = notice_for({"kind": "security_alert"})
    assert alert.warning and alert.is_server and "مشکوک" in alert.body


def test_backup_row():
    key, text, color = backup_text(None)
    assert key == "backup" and "هنوز" in text and color is None
    _, text, color = backup_text({"at": AT, "ok": True, "verified": True,
                                  "offsite_configured": True, "offsite_ok": True})
    assert "آزموده" in text and "سالم" in text and color == theme.SUCCESS_DARK
    _, text, color = backup_text({"at": AT, "ok": True, "offsite_configured": False})
    assert "BACKUP_COPY_DIR" in text and color == theme.WARNING_TEXT
    _, text, color = backup_text({"at": AT, "ok": False, "error": "off-server copy failed",
                                  "offsite_error": "OSError: denied", "last_success_at": AT})
    assert "OSError: denied" in text and "آخرین پشتیبان موفق" in text and color == theme.DANGER


def test_health_row_names_backup():
    _, text, color = health_text({"checks": {"backup": {"ok": False, "down": True, "fails": 2}}})
    assert "پشتیبان‌گیری" in text and color == theme.DANGER
