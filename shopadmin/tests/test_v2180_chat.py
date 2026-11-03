"""v2.18.0 ShopAdmin: «گفت‌وگوی همکاران», voice without a library, «پاسخ‌گوی خودکار»."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from app import permissions as perms
from app import voice
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN
from app.ui.pages.shop_rules import ShopRulesPage
from app.ui.pages.staff_chat import StaffChatPage, room_title
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


def _page(ui_context, role=ROLE_SUPER_ADMIN):  # noqa: F811
    return StaffChatPage(make_context_with_role(ui_context, role))


def test_two_ticks():
    assert {"staff_chat.view", "staff_chat.edit", "faq.view", "faq.edit"} <= perms.SECTION_PERMISSIONS


def test_room_title():
    assert room_title({"name": "مینا", "unread": 0}) == "مینا"
    assert room_title({"name": "مینا", "unread": 3}) == "مینا (۳)"


def test_rooms_and_messages_show(ui_context, admin_qapp):  # noqa: F811
    page = _page(ui_context)
    page.run = lambda *a, **k: None       # nothing goes to a server here
    page._rooms_loaded({"rooms": [{"room": "public", "name": "گفت‌وگوی عمومی", "unread": 2},
                                  {"room": "dm:1:2", "name": "مینا", "unread": 0}]})
    assert page.room == "public" and page.room_label.text() == "گفت‌وگوی عمومی"
    page._messages_loaded("public", [
        {"id": 5, "mine": False, "sender_name": "مینا", "text": "سلام همکاران",
         "created_at": "2026-11-03T10:00:00+00:00"},
        {"id": 6, "mine": True, "sender_name": "من", "voice": True, "voice_seconds": 7,
         "created_at": "2026-11-03T10:01:00+00:00"}])
    assert page.last_id == 6
    labels = "\n".join(label.text() for label in page.messages_holder.findChildren(QLabel))
    assert "سلام همکاران" in labels
    buttons = [b.text() for b in page.messages_holder.findChildren(QPushButton)]
    assert buttons == ["پخش پیام صوتی (۷ ثانیه)"]
    # the same message again (a poll) is not shown twice; another room's answer is dropped
    page._messages_loaded("public", [{"id": 6, "mine": True, "text": "x"}])
    page._messages_loaded("dm:1:2", [{"id": 9, "mine": True, "text": "y"}])
    assert page.last_id == 6
    page.close()


def test_no_send_tick_no_input(ui_context, admin_qapp):  # noqa: F811
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    page = StaffChatPage(context)
    assert not page.can_send and not page.input.isVisibleTo(page)
    page.close()


class _FakeRecorder:
    recording = False

    def start(self):
        raise voice.VoiceError("میکروفون در دسترس نیست.")


def test_no_microphone_is_a_sentence_not_a_crash(ui_context, admin_qapp):  # noqa: F811
    page = _page(ui_context)
    page.room = "public"
    page.recorder = _FakeRecorder()
    page._toggle_record()
    assert "میکروفون" in page.status_label.text() and page.record_button.text() == "ضبط صدا"
    page.close()


def test_recorder_commands(monkeypatch):
    sent = []
    monkeypatch.setattr(voice, "_mci", lambda command: sent.append(command) or "")
    monkeypatch.setattr(voice.sys, "platform", "win32")
    recorder = voice.Recorder()
    recorder.start()
    assert recorder.recording
    assert any("samplespersec 16000" in c for c in sent) and any(c.startswith("record ") for c in sent)
    recorder.cancel()
    assert not recorder.recording and sent[-1].startswith("close ")


def test_stopping_without_a_recording_is_refused():
    try:
        voice.Recorder().stop()
    except voice.VoiceError as exc:
        assert "ضبط" in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_faq_panel(ui_context, admin_qapp):  # noqa: F811
    page = ShopRulesPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page._show_faq({"enabled": True, "values": {"phone": "0915", "hours": "۰۹:۰۰ تا ۲۱:۰۰"}})
    assert page.faq_check.isChecked()
    assert page.faq_inputs["phone"].text() == "0915" and page.faq_inputs["address"].text() == ""
    page.close()
