"""v2.18.1 item 13 in ShopAdmin: «پاسخ‌گوی خودکار»: the list, the switch, approving a suggestion."""
from __future__ import annotations

import pytest

from app import permissions as perms
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN
from app.ui.pages.faq import FaqItemDialog, FaqPage, item_state
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture

DATA = {"enabled": True, "placeholders": ["hours", "phone"],
        "items": [{"id": "a", "category": "ساعت کاری", "questions": ["ساعت کار؟", "کی بازید؟"],
                   "answer": "ساعت ما: {hours}", "needs_staff": False, "enabled": True,
                   "source": "builtin", "edited": False},
                  {"id": "custom_1", "category": "هدیه", "questions": ["هدیه دارید؟"],
                   "answer": "بله", "needs_staff": True, "enabled": False, "source": "custom",
                   "edited": True}],
        "suggestions": [{"id": 3, "question": "کیف می‌فروشید؟", "answer": "بله داریم",
                         "created_by": "mina", "created_at": "2026-11-04T09:00:00"}],
        "report": [{"created_at": "2026-11-04T09:00:00", "query": "ساعت کار؟", "faq_id": "a",
                    "score": 95}]}


@pytest.fixture
def page(ui_context, admin_qapp):  # noqa: F811
    shown = FaqPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    shown.run = lambda fn, **k: k.get("on_success", lambda _x: None)(fn())
    shown._loaded(DATA)
    yield shown
    shown.close()


def test_the_page_shows_everything(page):
    assert page.switch.isChecked()
    assert page.items_table.rowCount() == 2 and page.suggest_table.rowCount() == 1
    assert page.answered_table.rowCount() == 1
    assert "۱ پرسش و پاسخ روشن از ۲" in page.counts.text() and "۱ پیشنهاد" in page.counts.text()


def test_the_states():
    assert item_state(DATA["items"][0]) == "روشن"
    assert item_state(DATA["items"][1]) == "خاموش (افزوده)"
    assert "ویرایش" in item_state({"enabled": True, "source": "builtin", "edited": True})


def test_searching(page):
    page.search.setText("هدیه")
    assert page.items_table.rowCount() == 1
    page.items_table.setCurrentCell(0, 0)
    assert page._selected_item()["id"] == "custom_1"


def test_the_switch_goes_to_the_server(page):
    calls = []
    page.context.api.set_faq = lambda on: calls.append(on)
    page.context.api.faq_page = lambda: DATA
    page._switched(False)
    assert calls == [False]


def test_toggling_keeps_the_words(page):
    calls = []
    page.context.api.faq_save_item = lambda item_id, values: calls.append((item_id, values))
    page.context.api.faq_page = lambda: DATA
    page.items_table.setCurrentCell(0, 0)
    page._toggle()
    assert calls[0][0] == "a" and calls[0][1]["enabled"] is False
    assert calls[0][1]["questions"] == ["ساعت کار؟", "کی بازید؟"]


def test_rejecting_a_suggestion(page):
    calls = []
    page.context.api.faq_reject = lambda sid: calls.append(sid)
    page.context.api.faq_page = lambda: DATA
    page.suggest_table.setCurrentCell(0, 0)
    page._reject()
    assert calls == [3]


def test_the_dialog_reads_one_question_a_line(admin_qapp):
    dialog = FaqItemDialog(DATA["items"][1], DATA["placeholders"])
    dialog.questions.setPlainText(" پرسش یک \n\nپرسش دو")
    values = dialog.values()
    assert values["questions"] == ["پرسش یک", "پرسش دو"]
    assert values["needs_staff"] is True and values["enabled"] is False
    dialog.answer.setPlainText("  ")
    dialog._save()
    assert "پاسخ" in dialog.problem.text() and dialog.result() == 0


def test_without_the_change_tick_there_are_no_buttons(ui_context, admin_qapp):  # noqa: F811
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    shown = FaqPage(context)
    assert shown.add_button.isHidden() and shown.approve_button.isHidden()
    assert not shown.switch.isEnabled()
    shown.close()


def test_the_sidebar_tick():
    assert perms.FAQ_VIEW in perms.client_permissions({"faq.view"})
