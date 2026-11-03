"""v2.18.0: staff chat (rooms, privacy, voice) and the bot's automatic answers."""
from __future__ import annotations

import base64

import pytest

from app import faq

from .conftest import h
from .test_v2170 import staff

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40


def _room(a, b) -> str:
    low, high = sorted((a, b))
    return f"dm:{low}:{high}"


@pytest.fixture
def people(db):
    from app import staff as staff_mod

    def person(name):
        headers = staff(db, "operator", name)
        user = db.get_staff_by_username(name)
        db.update_staff(user["id"], perm_grant="staff_chat.view,staff_chat.edit")
        return headers, user["id"]

    assert staff_mod.P_STAFF_CHAT_SEND == "staff_chat.edit"
    return person("mina"), person("sara"), person("reza")


def test_public_room_for_everyone(client, people):
    (mina, _), (sara, _), _ = people
    sent = client.post("/admin/chat/messages", json={"room": "public", "text": "سلام همکاران"},
                       headers=mina)
    assert sent.status_code == 201 and sent.json()["sender_name"]
    rooms = client.get("/admin/chat/rooms", headers=sara).json()
    assert rooms["unread"] == 1 and rooms["rooms"][0]["room"] == "public"
    got = client.get("/admin/chat/messages", params={"room": "public"}, headers=sara).json()
    assert got[0]["text"] == "سلام همکاران"
    assert client.get("/admin/chat/rooms", headers=sara).json()["unread"] == 0   # now read
    assert client.get("/admin/chat/messages", params={"room": "public", "after": got[0]["id"]},
                      headers=sara).json() == []


def test_a_private_room_is_for_its_two_people(client, people):
    (mina, mina_id), (sara, sara_id), (reza, _) = people
    room = _room(mina_id, sara_id)
    assert client.post("/admin/chat/messages", json={"room": room, "text": "خصوصی"},
                       headers=mina).status_code == 201
    assert client.get("/admin/chat/rooms", headers=sara).json()["unread"] == 1
    assert client.get("/admin/chat/rooms", headers=reza).json()["unread"] == 0
    assert client.get("/admin/chat/messages", params={"room": room}, headers=reza).status_code == 404
    assert client.post("/admin/chat/messages", json={"room": room, "text": "x"},
                       headers=reza).status_code == 404
    assert client.get("/admin/chat/messages", params={"room": room},
                      headers=sara).json()[0]["text"] == "خصوصی"


@pytest.mark.parametrize("room", ["dm:1:1", "dm:9:8", "dm:x:y", "other"])
def test_made_up_rooms_are_refused(client, people, room):
    (mina, _), _, _ = people
    assert client.post("/admin/chat/messages", json={"room": room, "text": "x"},
                       headers=mina).status_code == 404


def test_it_needs_the_tick_and_a_staff_session(client, db):
    outsider = staff(db, "operator", "no_tick")
    assert client.get("/admin/chat/rooms", headers=outsider).status_code == 403
    assert client.get("/admin/chat/rooms", headers=h("admin")).status_code in (401, 403)
    assert client.get("/admin/chat/rooms", headers=h("bot")).status_code in (401, 403)


def test_voice_round_trip(client, people, settings, tmp_path):
    settings.receipts_dir = str(tmp_path / "receipts")
    (mina, mina_id), (sara, sara_id), (reza, _) = people
    room = _room(mina_id, sara_id)
    r = client.post("/admin/chat/voice", headers=mina, json={
        "room": room, "seconds": 4, "data_b64": base64.b64encode(WAV).decode("ascii")})
    assert r.status_code == 201 and r.json()["voice"] and r.json()["voice_seconds"] == 4
    assert r.json()["mine"] is True
    message = r.json()["id"]
    got = client.get(f"/admin/chat/voice/{message}", headers=sara).json()
    assert base64.b64decode(got["data_b64"]) == WAV
    assert client.get(f"/admin/chat/voice/{message}", headers=reza).status_code == 404


def test_voice_kinds_and_size(client, people):
    (mina, _), _, _ = people
    assert client.post("/admin/chat/voice", headers=mina, json={
        "room": "public", "content_type": "application/x-msdownload",
        "data_b64": "eA=="}).status_code == 415
    assert client.post("/admin/chat/voice", headers=mina, json={
        "room": "public", "data_b64": "!!!"}).status_code == 422


# ---- the bank of answers --------------------------------------------------------------------
CASES = [
    ("ساعتکاریتون چنده", ("hours", "hours_holidays")),
    ("ادرستونکجاست تو مشهد", ("address", "in_person_visit")),
    ("شمارهتلفن مغازه رو بدین", ("phone",)),
    ("پیج اینستاتون چیه", ("instagram",)),
    ("لینک کانال تلگرامتون", ("telegram",)),
    ("ادرس وبسایتتون چیه", ("website",)),
    ("اقساتی با چک صیادی دارین؟", ("installment_sale",)),
    ("گوشی ها گارانتی شرکتی دارن؟", ("warranty",)),
    ("اجناستون اصلی و پلمپه؟", ("original_genuine", "not_active_status")),
    ("ارسالمشهد با پیک دارین؟", ("delivery_mashhad",)),
    ("چجوری تو بات سفارش بدم", ("how_to_order_bot",)),
    ("کارتبهکارت کردم فیششو کجا بفرستم", ("payment_card_receipt",)),
    ("وضعیت سفارشم به کجا رسید", ("order_status",)),
    ("واسه رجستری کدملی لازمه؟", ("registration_national_code",)),
    ("شرایط مرجوعی و تعویض کالا چیه", ("return_exchange",)),
    ("گوشیکارکرده تمیز دارین؟", ("used_phones", "used_phone_health")),
    ("معاوضهگوشی قدیم با جدید دارین", ("trade_in",)),
    ("انتقالاطلاعات به گوشی جدید انجام میدین", ("data_transfer",)),
    ("قاب و گلس و لوازم جانبی دارین", ("accessories_case_glass", "accessories")),
    ("این مدل گوشی رو الان موجود دارین؟", ("stock_availability",)),
]


@pytest.mark.parametrize("query,expected", CASES)
def test_matcher_cases_of_the_bundle(query, expected):
    assert faq.find(query).item["id"] in expected


def test_every_item_of_the_bank():
    data = faq.load_data()
    assert len(data["items"]) >= 40
    for item in data["items"]:
        assert len(item["questions"]) >= 12 and isinstance(item["needs_staff"], bool)
    # no price in any answer: they hold only placeholders
    assert not [i["id"] for i in data["items"] if any(c.isdigit() for c in i["answer"])]


def test_every_question_of_the_bank_finds_a_confident_answer():
    weak = [q for item in faq.load_data()["items"] for q in item["questions"][::5]
            if faq.find(q).score < faq.MIN_SCORE]
    assert not weak


def test_the_answer_uses_the_shops_values(db):
    found = faq.answer(db, "ساعت کاری چنده")
    assert found["id"] in ("hours", "hours_holidays")
    assert "{" not in found["answer"] and "۰۹:۰۰" in found["answer"]
    assert faq.answer(db, "چجوری تو بات سفارش بدم")["id"] == "how_to_order_bot"


def test_an_unset_value_means_no_answer(db):
    assert faq.render("تلفن: {phone}", {"phone": ""}) is None
    assert faq.render("تلفن: {phone}", {"phone": "1"}) == "تلفن: 1"


def test_a_wild_text_is_not_answered(db):
    assert faq.answer(db, "کلمهٔ بی‌ربط") == {}
    assert faq.answer(db, "   ") == {}


def test_switch_values_and_report(client, db):
    boss = staff(db, "super_admin", "boss")
    rules = client.get("/admin/shop-rules", headers=boss).json()["faq"]
    assert rules["enabled"] and rules["values"]["phone"]
    assert client.get("/faq/answer", params={"q": "ساعت کاری چنده"}, headers=h("bot")).json()["id"]
    assert client.get("/admin/shop-rules", headers=boss).json()["faq"]["report"][0]["faq_id"]
    r = client.put("/admin/shop-rules/faq", headers=boss,
                   json={"enabled": False, "values": {"phone": "0511"}})
    assert r.json()["values"]["phone"] == "0511" and r.json()["enabled"] is False
    assert client.get("/faq/answer", params={"q": "ساعت کاری چنده"}, headers=h("bot")).json() == {}


def test_only_the_bot_asks(client, db):
    assert client.get("/faq/answer", params={"q": "سلام"}, headers=h("site")).status_code == 403
    mina = staff(db, "operator", "mina2")
    assert client.put("/admin/shop-rules/faq", json={"enabled": False},
                      headers=mina).status_code == 403
