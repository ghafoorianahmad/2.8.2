"""v2.18.0 ShopAdmin: channel posts, proxy ticks, manual archive, automatic quotes, shifts."""
from __future__ import annotations

from app import permissions as perms
from app.statuses import ROLE_SUPER_ADMIN
from app.ui.pages import pricelist
from app.ui.pages.archive import ArchivePage
from app.ui.pages.orders import OrdersPage
from app.ui.pages.pricelist import ApplyNoteDialog, PriceListPage, change_lines, note_summary
from app.ui.pages.shop_rules import ShopRulesPage, hours_text
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


def _boss(ui_context):  # noqa: F811
    return make_context_with_role(ui_context, ROLE_SUPER_ADMIN)


# ---- posts of the channel --------------------------------------------------------------------
def test_results_read_applied_uncertain_not_recognized():
    assert pricelist.NOTE_RESULT_FA["correction"] == "اعمال شد"
    assert pricelist.NOTE_RESULT_FA["uncertain"] == "نامطمئن"
    assert pricelist.NOTE_RESULT_FA["ignored"] == "شناخته نشد"
    assert "اعمال دستی" in note_summary({"kind": "uncertain", "result": {}})
    assert "TCH" in note_summary({"kind": "ignored", "result": {"brand_header": "TCH"}})


def test_old_and_new_prices_are_shown():
    text = change_lines({"changes": [
        {"description": "A17 256GB", "color": "Blue", "old_naghd": 95000, "new_naghd": 95500,
         "held": False},
        {"description": "A55", "color": "", "old_naghd": 100, "new_naghd": 200, "held": True}]})
    assert "A17 256GB Blue" in text and "۹۵,۰۰۰" in text.replace("٬", ",") and "←" in text
    assert "منتظر تأیید" in text
    assert change_lines({"changes": []}) == ""


def test_apply_dialog_reads_rows_and_prices(admin_qapp):
    rows = [{"row_key": "a", "description": "A17 256GB", "color": "Blue"}]
    dialog = ApplyNoteDialog({"id": 1, "text": "A17", "result": {"items": [{"price": 95500}]}},
                             rows)
    dialog._submit()
    assert dialog.picks == [] and "دست‌کم" in dialog.error_label.text()
    dialog.lines[0][0].setCurrentIndex(1)
    assert dialog.lines[0][1].text() == "۹۵٬۵۰۰"
    dialog._submit()
    assert dialog.picks == [("a", 95500)]


def test_apply_dialog_refuses_a_row_without_a_price(admin_qapp):
    rows = [{"row_key": "a", "description": "A17", "color": ""}]
    dialog = ApplyNoteDialog({"id": 1, "text": "A17", "result": {}}, rows)
    dialog.lines[0][0].setCurrentIndex(1)
    dialog._submit()
    assert dialog.picks == [] and "قیمت" in dialog.error_label.text()


# ---- proxies ---------------------------------------------------------------------------------
def test_proxy_source_words():
    assert pricelist.proxy_source_fa("manual") == "دستی"
    assert pricelist.proxy_source_fa("channel:ProxyMTProto") == "خودکار"
    assert pricelist.proxy_source_fa(None) == "خودکار"


def test_proxy_rows_can_be_ticked(ui_context, admin_qapp):  # noqa: F811
    page = PriceListPage(_boss(ui_context))
    page._on_proxies([
        {"id": 7, "host": "a.example", "port": 443, "source": "manual", "state": "main"},
        {"id": 8, "host": "b.example", "port": 443, "source": "channel", "state": "retired"}])
    assert page.proxy_table.item(0, 3).text() == "دستی"
    assert page.proxy_table.item(1, 8).text() == "قطع"
    page.proxy_table.set_all_checked(True)
    assert page.proxy_table.checked_keys() == [7, 8]
    page.close()


# ---- manual archive --------------------------------------------------------------------------
def test_the_tick_is_there():
    assert "archive_manual.edit" in perms.SECTION_PERMISSIONS
    assert perms.ARCHIVE_MANUAL == "archive_manual.edit"


def test_orders_have_ticks_only_with_the_permission(ui_context, admin_qapp, fake_api):  # noqa: F811
    from app.statuses import ROLE_OPERATOR

    page = OrdersPage(make_context_with_role(ui_context, ROLE_OPERATOR))
    assert not page.can_archive and not page.archive_button.isVisibleTo(page)
    page.close()
    page = OrdersPage(_boss(ui_context))
    assert page.can_archive
    page.close()


def test_archive_page_has_restore(ui_context, admin_qapp):  # noqa: F811
    page = ArchivePage(_boss(ui_context))
    assert page.can_restore
    page._orders_loaded([{"id": 5, "status": "written", "total": 1}])
    page.orders_table.set_all_checked(True)
    assert page.orders_table.checked_keys() == [5]
    assert page.orders_table.item(0, 0).text() == "۵"
    page.close()


# ---- rules -----------------------------------------------------------------------------------
def test_shifts_on_the_page(ui_context, admin_qapp):  # noqa: F811
    page = ShopRulesPage(_boss(ui_context))
    page._show_hours({"start": "09:00", "end": "21:00", "days": [0],
                      "shifts": [{"start": "09:00", "end": "13:00"},
                                 {"start": "16:00", "end": "21:00"}]})
    assert page.shift_inputs[1][0].text() == "16:00" and page.shift_inputs[2][0].text() == ""
    page.close()
    text = hours_text({"days": [0], "shifts": [{"start": "09:00", "end": "13:00"},
                                               {"start": "16:00", "end": "21:00"}]})
    assert "۱۳:۰۰" in text and "۱۶:۰۰" in text and "دوشنبه" in text


def test_auto_quote_panel(ui_context, admin_qapp):  # noqa: F811
    page = ShopRulesPage(_boss(ui_context))
    page._show_quote({"enabled": False, "report": [
        {"created_at": "2026-11-03T10:00:00+00:00", "query": "ایفون", "description": "17 Pro",
         "color": "Black", "price_rial": 5000}]})
    assert not page.quote_check.isChecked()
    assert page.quote_table.rowCount() == 1 and page.quote_table.item(0, 1).text() == "ایفون"
    page.close()
