"""v2.15.0 #1: the yellow «حالت آزمایشی» banner.

Cause found: the banner kept the server flags read when ShopAdmin started (or the
dashboard last loaded); «تنظیمات سرور فروشگاه» read fresh ones. After «ثبت
واقعی» was switched on (the service restarts), that page said «فعال» while the
banner still said «حالت آزمایشی». Now every fresh status updates it, it is read
again every minute and after a reconnection, and it names exactly what is
missing (with a button to that setting); with nothing missing it is hidden."""
from __future__ import annotations

import pytest

from app.api_client import SystemInfo
from app.statuses import ROLE_OPERATOR

from .test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


def _info(**kw) -> SystemInfo:
    base = dict(accounting_write_enabled=True, reachable=True, status_code_configured=True,
                accounting_database="hesab5 t")
    base.update(kw)
    extra = {"write_block_reason": base.pop("reason")} if "reason" in base else {}
    info = SystemInfo(**base)
    info.extra.update(extra)
    return info


@pytest.fixture
def window(ui_context, admin_qapp):  # noqa: F811
    from app.ui.main_window import MainWindow

    win = MainWindow(ui_context)
    win.show()
    admin_qapp.processEvents()
    yield win
    win.allow_close = True
    win.close()


def test_all_conditions_met_no_banner(window, ui_context, admin_qapp):
    ui_context.apply_system_info(_info())
    admin_qapp.processEvents()
    assert not window.banner.isVisible()


def test_missing_status_code_is_named_with_a_button(window, ui_context, admin_qapp, fake_api):
    fake_api.server_settings["ACCOUNTING_STATUS_CODE"] = ""
    ui_context.apply_system_info(_info(status_code_configured=False))
    admin_qapp.processEvents()
    assert window.banner.isVisible()
    text = window.banner_label.text()
    assert "«کد وضعیت سفارش» تنظیم نشده" in text and "حالت آزمایشی" not in text
    assert window.banner_buttons["status_code"].isVisible()
    assert not window.banner_buttons["server_settings"].isVisible()
    window.banner_buttons["status_code"].click()
    admin_qapp.processEvents()
    # v2.17.0: the codes live in «قواعد فروشگاه» (their own tick)
    assert window.current_key() == "shop_rules"


@pytest.mark.parametrize("reason, words", [
    ("write_off", "«ثبت واقعی» برای «hesab5 t» روشن نیست"),
    ("not_allowed", "«hesab5 t» در فهرست پایگاه‌داده‌های مجاز نیست"),
    ("no_database", "پایگاه‌دادهٔ حسابداری انتخاب نشده"),
])
def test_write_off_says_why(window, ui_context, admin_qapp, reason, words):
    ui_context.apply_system_info(_info(accounting_write_enabled=False, reason=reason))
    admin_qapp.processEvents()
    assert window.banner.isVisible()
    assert "حالت آزمایشی" in window.banner_label.text() and words in window.banner_label.text()
    assert window.banner_buttons["server_settings"].isVisible()


def test_fresh_server_status_replaces_the_start_up_state(window, ui_context, admin_qapp,
                                                         monkeypatch):
    """The exact 2.14.0 case: started while writing was off, switched on later."""
    ui_context.apply_system_info(_info(accounting_write_enabled=False, reason="write_off"))
    admin_qapp.processEvents()
    assert window.banner.isVisible()
    status = {"accounting_write_enabled": True, "status_code_configured": True,
              "accounting_database": "hesab5 t", "write_block_reason": None,
              "accounting": {"ok": True, "latency_ms": 5}, "components": {}, "counts": {}}
    monkeypatch.setattr(ui_context.api, "server_status", lambda: status)
    window.navigate("server")
    for _ in range(40):
        admin_qapp.processEvents()
        if not window.banner.isVisible():
            break
    assert not window.banner.isVisible()


def test_banner_is_read_again_by_itself(window, ui_context, admin_qapp, fake_api):
    ui_context.apply_system_info(_info(accounting_write_enabled=False, reason="write_off"))
    fake_api.write_enabled = True
    window.refresh_system_info()
    for _ in range(40):
        admin_qapp.processEvents()
        if not window.banner.isVisible():
            break
    assert not window.banner.isVisible()
    assert window._info_timer.isActive() and window._info_timer.interval() == 60_000


def test_sales_user_sees_the_reason_but_no_settings_button(ui_context, admin_qapp):  # noqa: F811
    from app.ui.main_window import MainWindow

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    context.apply_system_info(_info(status_code_configured=False))
    win = MainWindow(context)
    win.show()
    admin_qapp.processEvents()
    try:
        assert win.banner.isVisible()
        assert not any(b.isVisible() for b in win.banner_buttons.values())
    finally:
        win.allow_close = True
        win.close()
