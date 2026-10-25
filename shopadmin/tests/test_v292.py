"""v2.9.2: «سرور فروشگاه» never shows «هنوز پراکسی‌ای در استخر نیست» over the rows,
«جمع‌آوری اکنون», the price offer in «درخواست کالا» and its history."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import activity, notifications  # noqa: E402
from app.statuses import ROLE_SUPER_ADMIN  # noqa: E402

from .test_ui import make_context_with_role, ui_context  # noqa: E402,F401


def _pump(rounds: int = 50, until=None) -> None:
    for _ in range(rounds):
        QApplication.processEvents()
        if until is not None and until():
            return


def test_pool_rows_are_not_hidden_by_the_empty_message(ui_context, admin_qapp, fake_api):
    from app.ui.pages.server import ServerPage

    fake_api.proxies = [
        {"id": i, "host": f"10.0.0.{i}", "port": 443, "kind": "dd", "state": "main",
         "source": "manual", "last_ok_at": "2026-10-25T08:00:00+00:00", "failing_now": False}
        for i in (1, 2, 3)]
    page = ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page.load()
    _pump(until=lambda: page.proxy_table.rowCount())
    table = page.proxy_table
    assert table.rowCount() == 3
    assert table._empty_widget is None or not table._empty_widget.isVisible()


def test_collect_now_asks_the_server(ui_context, admin_qapp, fake_api, monkeypatch):
    from app.ui.pages import server as server_mod

    monkeypatch.setattr(server_mod.QTimer, "singleShot", lambda *_a, **_k: None)
    page = server_mod.ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert page.collect_button.isVisibleTo(page)
    page._collect_now()
    _pump(until=lambda: fake_api.collect_requests)
    assert fake_api.collect_requests == 1
    _pump(until=lambda: page.collect_button.isEnabled())
    assert page.collect_button.isEnabled()


def test_collection_texts_requested_and_stored():
    from app.ui.pages.server import telegram_details

    rows = telegram_details({"connected": True, "collect": {
        "at": "2026-10-25T09:58:48+00:00", "found": 54, "tested": 9, "added": 4,
        "via": "account", "requested": True}}, {"target": 5, "working": 7})
    assert "در صف" in rows["collect"][0] and "۵۴ پیوند" in rows["collect"][0]
    assert "۴ سالم اضافه شد" in rows["collect"][0]


def test_offer_history_and_notices():
    entries = [{"action": "price_offer", "is_me": True},
               {"action": "offer_accept", "system": True, "actor_name": "service:admin"}]
    text = activity.timeline_text(entries)
    assert "قیمت را برای تأیید مشتری فرستاد" in text
    assert "مشتری «تأیید و خرید» زد" in text and "service" not in text
    notice = notifications.notice_for({"kind": "purchase_offer_declined", "ref_id": 4})
    assert notice is not None and notice.target == ("item_requests", "done")
    held = notifications.notice_for({"kind": "price_held", "ref_id": 1})
    assert "قیمت قبلی فروخته نمی‌شود" in held.body


def test_wizard_turns_a_share_of_this_computer_into_its_folder(admin_qapp, monkeypatch):
    from app import localshare
    from app import server_setup as setup

    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "existing_config_port", lambda: None)
    monkeypatch.setattr(localshare, "this_computer_names", lambda: {"shopsrv"})
    monkeypatch.setattr(localshare, "share_folders", lambda: {"backups": r"G:\Backups"})
    from app.ui.server_setup_wizard import ServerSetupWizard

    wizard = ServerSetupWizard()
    try:
        wizard.backup_dir.setText(r"\\SHOPSRV\Backups\Shop")
        assert wizard._local_backup_folder() is True
        assert wizard.backup_dir.text() == r"G:\Backups\Shop"
        assert "همین رایانهٔ سرور" in wizard.backup_result.text()
        wizard.backup_dir.setText(r"\\NAS\Backups")
        assert wizard._local_backup_folder() is False
        assert wizard.config_extra()["backup_copy_dir"] == r"\\NAS\Backups"
    finally:
        wizard.close()
        wizard.deleteLater()
