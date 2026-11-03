"""v2.18.0 ShopAdmin: the same details rules as the server, the Sazeh name, the same-person question."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton



from app.ui.pages.customers import ApproveCustomerDialog, CustomerDetailsDialog, person_text


from app.statuses import ROLE_SUPER_ADMIN
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[2]


def _customer(**fields) -> dict:
    return {"id": 3, "name": "نام پروفایل", "platform": "bale", "phone": "09124445555",
            "status": "pending", "created_at": "2026-11-01T10:00:00+00:00", **fields}


def test_the_rules_are_the_servers_own():
    ours = (ROOT / "shopadmin" / "app" / "validators.py").read_bytes()
    theirs = (ROOT / "shopapi" / "app" / "validators.py").read_bytes()
    assert ours == theirs


def test_person_text():
    assert person_text({}) == "—"
    assert person_text({"person_code": 7001}) == "کد ۷۰۰۱"
    assert person_text({"person_code": 7001, "person_name": "رضا کریمی"}) == "رضا کریمی (کد ۷۰۰۱)"


def _dialog(ui_context) -> ApproveCustomerDialog:
    return ApproveCustomerDialog(make_context_with_role(ui_context, ROLE_SUPER_ADMIN),
                                 _customer(first_name="علی", last_name="رضایی"))


def _labels(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def test_the_whole_number_is_shown(ui_context, admin_qapp):
    assert "۰۹۱۲۴۴۴۵۵۵۵" in _labels(_dialog(ui_context))


def test_same_name_asks_and_links(ui_context, admin_qapp):
    dialog = _dialog(ui_context)
    dialog._got_candidates({"national_code": None, "candidates": [
        {"code": 501, "name": "علی رضایی", "score": 100, "verdict": "same", "phone_tail": "47"},
        {"code": 502, "name": "علی رضائی پور", "score": 84, "verdict": "similar",
         "phone_tail": ""}]})
    text = _labels(dialog.candidates_panel)
    assert "«علی رضایی» با شمارهٔ …۴۷ در حسابداری هست. همین شخص است؟" in text
    # «same» is suggested: the link is chosen, staff still see and may change it
    assert not dialog.creating and dialog.code_input.value() == 501
    other = [b for b in dialog.candidates_panel.findChildren(QPushButton)
             if b.text() == "شخص دیگری است"][0]
    other.click()
    assert dialog.creating and dialog.code_input.value() == 0
    same = [b for b in dialog.candidates_panel.findChildren(QPushButton)
            if b.text() == "همین شخص است"][1]
    same.click()
    assert not dialog.creating and dialog.code_input.value() == 502


def test_similar_only_asks(ui_context, admin_qapp):
    dialog = _dialog(ui_context)
    dialog.mode_create.setChecked(True)
    dialog._got_candidates({"national_code": None, "candidates": [
        {"code": 502, "name": "علی رضائی پور", "score": 84, "verdict": "similar"}]})
    assert dialog.creating and dialog.code_input.value() == 0


def test_national_code_links_by_itself(ui_context, admin_qapp):
    dialog = _dialog(ui_context)
    dialog.mode_create.setChecked(True)
    dialog._got_candidates({"national_code": {"code": 503, "name": "حسن کریمی"}, "candidates": []})
    assert not dialog.creating and dialog.code_input.value() == 503
    assert "کد ملی این مشتری" in _labels(dialog.candidates_panel)


def test_nothing_found_shows_no_panel(ui_context, admin_qapp):
    dialog = _dialog(ui_context)
    dialog._got_candidates({"national_code": None, "candidates": []})
    assert dialog.candidates_panel is None


@pytest.mark.parametrize("field,value,word", [
    ("first_name", "Ali", "حروف فارسی"),
    ("last_name", "رضایی2", "حروف فارسی"),
    ("national_code", "0084575949", "رقم کنترل"),
    ("address", "Valiasr street 12", "نشانی"),
])
def test_details_dialog_says_what_is_wrong(admin_qapp, field, value, word):
    dialog = CustomerDetailsDialog(_customer(
        first_name="علی", last_name="رضایی", national_code="0084575948",
        address="مشهد، خیابان نمونه، پلاک ۱"))
    dialog.fields.inputs[field].setText(value)
    dialog._submit()
    assert dialog.result() == 0 and word in dialog.error_label.text()


def test_details_dialog_needs_all_four(admin_qapp):
    dialog = CustomerDetailsDialog(_customer(first_name="علی", last_name="رضایی"))
    dialog._submit()
    assert dialog.result() == 0 and "الزامی" in dialog.error_label.text()
    dialog.fields.inputs["national_code"].setText("۰۰۸۴۵۷۵۹۴۸")
    dialog.fields.inputs["address"].setText("مشهد، خیابان نمونه، پلاک ۱")
    dialog._submit()
    assert dialog.values["national_code"] == "0084575948"


