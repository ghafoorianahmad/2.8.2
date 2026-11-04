"""v2.18.1 item 17 in ShopAdmin: the page calculates first, then everything can be edited, with the
difference always shown. The sums are the server's own module (a test there keeps them identical)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import installments as inst
from app import permissions as perms
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN
from app.ui.pages.installments import (
    CustomerPickDialog,
    InstallmentsPage,
    ItemPickDialog,
    QuoteHistoryDialog,
)
from app.ui.pages.shop_rules import ShopRulesPage
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


@pytest.fixture
def page(ui_context, admin_qapp):  # noqa: F811
    shown = InstallmentsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    yield shown
    shown.close()


def _example(page):
    page.price.setText("200000000")
    page.down_input.setText("100,000,000")
    page.months.setValue(5)
    page.rate.setText("8")


def test_the_ticks():
    assert {"installment.view", "installment.edit", "installment_rules.view",
            "installment_rules.edit"} <= perms.SECTION_PERMISSIONS
    assert not {"installment.view", "installment_rules.edit"} & perms.SALES_SERVER_PERMISSIONS


def test_the_owners_example_on_the_page(page):
    _example(page)
    assert page.quote.interest == 40_000_000
    assert page.checks == [28_000_000] * 5
    assert page.schedule.rowCount() == 5
    assert page.interest_value.text() == "۴۰٬۰۰۰٬۰۰۰ ریال"
    assert page.grand_edit.text() == "۲۴۰٬۰۰۰٬۰۰۰"
    assert "۵ چک × ۲۸٬۰۰۰٬۰۰۰" in page.each_value.text()
    assert "بدون اختلاف" in page.difference.text()


def test_persian_digits_and_a_percent(page):
    page.price.setText("۲۰۰٬۰۰۰٬۰۰۰")
    page.down_input.setText("۵۰٪")
    assert page.quote.down == 100_000_000
    assert "۱۰۰٬۰۰۰٬۰۰۰" in page.down_note.text()


def test_bad_inputs_say_why_and_show_no_result(page):
    page.price.setText("100")
    page.down_input.setText("200")
    assert page.quote is None and "کمتر" in page.problem.text()
    assert page.schedule.rowCount() == 0
    page.down_input.setText("چند")
    assert page.quote is None and page.problem.text()


def test_editing_a_check_recalculates_and_shows_the_difference(page):
    _example(page)
    page.schedule.item(0, 2).setText("۲۹٬۰۰۰٬۰۰۰")
    assert page.checks[0] == 29_000_000
    assert page.grand_edit.text() == "۲۴۱٬۰۰۰٬۰۰۰"
    assert page.interest_value.text() == "۴۱٬۰۰۰٬۰۰۰ ریال"
    assert "+۱٬۰۰۰٬۰۰۰" in page.difference.text()


def test_a_bad_amount_goes_back_and_says_why(page):
    _example(page)
    page.schedule.item(1, 2).setText("صفر")
    assert page.checks[1] == 28_000_000 and page.problem.text()
    assert page.schedule.item(1, 2).text() == "۲۸٬۰۰۰٬۰۰۰"


def test_editing_a_date(page):
    _example(page)
    page.schedule.item(2, 1).setText("۱۴۰۶/۰۱/۰۵")
    assert page.dates[2] == "1406/01/05"
    page.schedule.item(2, 1).setText("1406/13/01")
    assert page.dates[2] == "1406/01/05" and page.problem.text()


def test_editing_the_down_payment_and_the_totals(page):
    _example(page)
    page._down_edited("90,000,000")
    assert page.down == 90_000_000 and "−۱۰٬۰۰۰٬۰۰۰" in page.difference.text()
    page._recalculate()
    page._total_edited("۱۴۵٬۰۰۰٬۰۰۰")
    assert page.checks == [28_000_000] * 4 + [33_000_000]
    page._recalculate()
    page._grand_edited("250000000")
    assert page.checks[-1] == 38_000_000 and "+۱۰٬۰۰۰٬۰۰۰" in page.difference.text()


def test_back_to_the_first_calculation(page):
    _example(page)
    page.schedule.item(0, 2).setText("۲۹٬۰۰۰٬۰۰۰")
    page.reset_button.click()
    assert page.checks == [28_000_000] * 5 and "بدون اختلاف" in page.difference.text()


def test_rounding_is_only_a_suggestion_until_applied(page):
    page.price.setText("100000000")
    page.down_input.setText("0")
    page.months.setValue(3)
    page.rate.setText("8.33")
    before = list(page.checks)
    page.round_choice.setCurrentIndex(1)
    assert page.checks == before and "۴۱٬۷۰۰٬۰۰۰" in page.round_note.text()
    page.round_button.click()
    assert page.checks == [41_700_000] * 3 and page.difference.text().count("+") == 1


def test_the_comparison_table_and_picking_a_row(page):
    _example(page)
    assert page.compare.rowCount() == 12
    assert page.compare.item(4, 1).text() == "۲۸٬۰۰۰٬۰۰۰"
    page._compare_activated(2)
    assert page.months.value() == 3


def test_the_first_date_sets_the_schedule(page):
    from datetime import date
    _example(page)
    page.first_date.set_date(date(2026, 12, 6))     # ۱۴۰۵/۰۹/۱۵
    page._dates_from_first()                        # what the widget does when a person picks
    assert page.dates == inst.schedule("1405/09/15", 5)
    assert page.schedule.item(1, 1).text() == "۱۴۰۵/۱۰/۱۵"


def test_the_sheet_goes_as_edited(page):
    _example(page)
    page.phone_name.setText("Galaxy S25")
    page.schedule.item(0, 2).setText("۲۹٬۰۰۰٬۰۰۰")
    sheet = page.current_sheet()
    payload = page._payload(sheet)
    assert payload["checks"][0] == 29_000_000 and payload["phone_name"] == "Galaxy S25"
    assert payload["rate"] == "8" and len(payload["dates"]) == 5


def test_the_customers_copy_has_no_interest(page):
    from PySide6.QtGui import QGuiApplication
    page.price.setText("190000000")
    page.down_input.setText("100000000")
    page.rate.setText("8")
    page.months.setValue(5)
    page._copy_customer()
    text = QGuiApplication.clipboard().text()
    assert "سود" not in text and "نرخ" not in text and "۱۹۰٬۰۰۰٬۰۰۰" not in text
    page._copy_staff()
    assert "سود" in QGuiApplication.clipboard().text()


def test_a_changed_page_forgets_the_card(page):
    _example(page)
    page._got_card({"text": "متن", "png_b64": ""})
    assert not page.save_png_button.isEnabled()
    png = b"\x89PNG\r\n\x1a\n"
    import base64
    page._got_card({"text": "متن", "png_b64": base64.b64encode(png).decode()})
    assert page.card_png == png and page.save_png_button.isEnabled()
    page.schedule.item(0, 2).setText("۲۹٬۰۰۰٬۰۰۰")
    assert page.card_png == b"" and not page.save_png_button.isEnabled()


def test_a_saved_quote_comes_back_with_its_edits(page):
    page.show_quote({"phone_name": "Galaxy", "price": 200_000_000, "down": 100_000_000, "rate": "8",
                     "checks": [29_000_000, 28_000_000, 28_000_000, 28_000_000, 28_000_000],
                     "dates": inst.schedule("1405/09/15", 5)})
    assert page.phone_name.text() == "Galaxy" and page.months.value() == 5
    assert page.checks[0] == 29_000_000 and page.dates[0] == "1405/09/15"
    assert "+۱٬۰۰۰٬۰۰۰" in page.difference.text()


def test_without_the_change_tick_nothing_is_saved_or_sent(ui_context, admin_qapp):  # noqa: F811
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    shown = InstallmentsPage(context)
    assert shown.send_button.isHidden() and shown.save_quote_button.isHidden()
    assert shown.save_rate_button is None
    shown.close()


def test_the_rate_button_needs_the_rules_tick(page):
    assert page.save_rate_button is not None


def test_the_default_rate_comes_from_the_server(page):
    page._got_settings({"rate": "9.5", "customer_enabled": False})
    assert page.rate.text() == "9.5"


def test_the_dialogs_build(ui_context, admin_qapp):  # noqa: F811
    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    context.api.installment_items = lambda query="": []
    context.api.installment_quotes = lambda: []
    for dialog in (ItemPickDialog(context), CustomerPickDialog(context),
                   QuoteHistoryDialog(context)):
        dialog.close()


def test_the_customer_row_shows_two_digits(admin_qapp):
    text = CustomerPickDialog._row_text({"name": "علی", "platform": "bale", "phone_tail": "47"})
    assert "۴۷" in text and "بله" in text


def test_the_rules_page_has_the_switch_off_by_default(ui_context, admin_qapp):  # noqa: F811
    rules = ShopRulesPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert rules.installment_panel is not None
    rules._got_installment({"rate": "8", "customer_enabled": False})
    assert rules.installment_check.isChecked() is False and rules.installment_rate.text() == "۸"
    rules.close()


def test_the_mini_app_page_knows_no_rate():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "miniapp_installment.html").read_text(encoding="utf-8")
    built = (root / "app" / "assets" / "miniapp" / "app" / "installment" / "index.html"
             ).read_text(encoding="utf-8")
    assert source == built
    assert "rate" not in source.lower().replace("generate", "") and "سود" not in source
    assert "'installment'" in source
