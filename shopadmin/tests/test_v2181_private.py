"""v2.18.1 item 16 in ShopAdmin and the form: without the tick the two private fields stay out of
the form and its checks; the page never takes a value from a link."""
from __future__ import annotations

from pathlib import Path

from app import permissions as perms
from app.ui.pages.customers import CustomerFields

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "app" / "assets" / "miniapp" / "app" / "form"


def test_the_tick_exists_and_is_not_a_default():
    assert "customer_private.view" in perms.SECTION_PERMISSIONS
    assert "customer_private.edit" in perms.SECTION_PERMISSIONS
    assert "customer_private.view" not in perms.SALES_SERVER_PERMISSIONS
    assert perms.CUSTOMER_PRIVATE_VIEW in perms.client_permissions({"customer_private.view"})


def test_without_the_tick_the_fields_are_locked(admin_qapp):
    fields = CustomerFields({"first_name": "علی", "last_name": "رضایی",
                             "national_code": "••••••••99", "address": "",
                             "national_code_on_file": True, "address_on_file": True,
                             "private_hidden": True})
    code, address = fields.inputs["national_code"], fields.inputs["address"]
    assert not code.isEnabled() and not address.isEnabled()
    assert "99" in code.text() or "۹۹" in code.text()
    assert "بدون دسترسی" in address.text()
    # the locked ones are not checked and never sent
    assert fields.problem(required=True) == ("", None)
    assert set(fields.values()) == {"first_name", "last_name"}


def test_nothing_on_file_says_the_customer_writes_it(admin_qapp):
    fields = CustomerFields({"first_name": "علی", "last_name": "رضایی", "private_hidden": True})
    assert "ربات" in fields.inputs["national_code"].text()
    assert fields.problem(required=True) == ("", None)


def test_with_the_tick_all_four_are_editable(admin_qapp):
    fields = CustomerFields({"first_name": "علی", "last_name": "رضایی",
                             "national_code": "0084575948", "address": "مشهد، خیابان نمونه، پلاک ۱"})
    assert all(box.isEnabled() for box in fields.inputs.values())
    assert set(fields.values()) == set(fields.inputs)


def test_the_form_never_takes_a_value_from_a_link():
    js = (FORM / "validators.js").read_text(encoding="utf-8")
    html = (FORM / "index.html").read_text(encoding="utf-8")
    assert "params.get('nc')" not in js and "params.get('addr')" not in js
    assert "query.get('need')" in html
    assert "ALL_FIELDS" in html


def test_the_build_script_and_the_built_form_agree():
    script = (ROOT / "scripts" / "build_miniapp.py").read_text(encoding="utf-8")
    html = (FORM / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = script.index('FORM_SCRIPT = """') + len('FORM_SCRIPT = """')
    assert script[start:script.index('"""', start)].replace("\r\n", "\n").strip() in html
