"""v2.18.1 items 14 and 15 in ShopAdmin: one click on a ready reply; a gap stops the message; the ticks
are the server's."""
from __future__ import annotations

from app import permissions as perms
from app.ui.pages.item_requests import TEMPLATE_GAP, TemplatePickDialog

DATA = {"categories": ["خوشامد", "اعلام قیمت"],
        "templates": [{"id": "greet", "category": "خوشامد", "title": "سلام", "missing": [],
                       "text": "سلام علی رضایی عزیز"},
                      {"id": "price", "category": "اعلام قیمت", "title": "قیمت روز",
                       "text": "قیمت {product} امروز", "missing": ["product"]}]}


def test_one_click_takes_the_text(admin_qapp):
    dialog = TemplatePickDialog(DATA)
    assert dialog.rows.count() == 2
    dialog._picked(dialog.rows.item(0))
    assert dialog.chosen == "سلام علی رضایی عزیز" and dialog.result() == dialog.DialogCode.Accepted


def test_search_and_category(admin_qapp):
    dialog = TemplatePickDialog(DATA)
    dialog.category.setCurrentIndex(2)
    assert [t["id"] for t in dialog.visible_templates()] == ["price"]
    dialog.category.setCurrentIndex(0)
    dialog.search.setText("علی")
    assert dialog.rows.count() == 1
    dialog.close()


def test_the_gap_pattern():
    assert TEMPLATE_GAP.findall("قیمت {product} با {price}") == ["product", "price"]
    assert TEMPLATE_GAP.findall("{other} {} متن") == []


def test_the_page_and_the_server_have_the_same_rows():
    import re
    from pathlib import Path

    server = (Path(__file__).resolve().parents[2] / "shopapi" / "app" / "staff.py").read_text(
        encoding="utf-8")
    keys = re.findall(r'^    \("([a-z_]+)", "', server, flags=re.M)
    assert keys == [row[0] for row in perms.ALL_SECTIONS]


def test_every_new_tick_reaches_the_screens():
    for name in ("customer_private.view", "customer_private.edit", "installment.view",
                 "installment.edit", "installment_rules.view", "installment_rules.edit",
                 "reply_templates.view", "price_notes.view", "price_notes.edit", "faq.view",
                 "faq.edit", "archive_manual.edit", "auto_quote.view", "product_alias.edit",
                 "staff_chat.view"):
        assert perms.client_permissions({name}) - perms.ALWAYS, name
    assert perms.SHOP_RULES_VIEW in perms.client_permissions({"installment_rules.view"})
