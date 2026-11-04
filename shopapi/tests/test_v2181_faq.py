"""v2.18.1 item 13: placeholders, the polite sentence for a colleague's question, the bank as managers
edit it, and suggestions from what staff answer (used only after approval)."""
from __future__ import annotations

from app import faq

from .conftest import h, seed_products
from .test_phase3 import staff


def _item(**changes) -> dict:
    return {"category": "آزمایشی", "questions": ["آیا هدیه هم می‌دهید؟"],
            "answer": "با خرید گوشی بسته هدیه می‌دهیم.", "needs_staff": False, "enabled": True,
            **changes}


def test_placeholders_come_from_the_shops_values(db):
    faq.save_values(db, {"phone": "02112345678", "address": "مشهد، آدرس آزمایشی"}, "x")
    found = faq.answer(db, "آدرس فروشگاه کجاست")
    assert "مشهد، آدرس آزمایشی" in found["answer"] and "{" not in found["answer"]


def test_a_colleagues_question_says_so(db):
    found = faq.answer(db, "فروش اقساطی دارید")
    assert found["needs_staff"] is True and found["answer"].endswith(faq.STAFF_NOTE)


def test_a_colleagues_question_with_no_value_still_gets_the_sentence(db, monkeypatch):
    faq.save_item(db, None, category="x", questions=["شمارهٔ کارشناس فروش چنده"],
                  answer_text="با {phone} تماس بگیرید", needs_staff=True, enabled=True, actor="x")
    monkeypatch.setattr(faq, "values", lambda _db: {"phone": ""})
    found = faq.answer(db, "شمارهٔ کارشناس فروش چنده")
    assert found["needs_staff"] is True and found["answer"] == faq.STAFF_NOTE


def test_an_answer_with_no_value_and_no_colleague_says_nothing(db, monkeypatch):
    monkeypatch.setattr(faq, "values", lambda _db: {key: "" for key in faq.PLACEHOLDERS})
    assert faq.answer(db, "آدرس فروشگاه کجاست") == {}


def test_an_edit_of_a_built_in_is_used_and_kept_apart(db):
    item = next(i for i in faq.all_items(db) if i["id"] == "address")
    faq.save_item(db, "address", category=item["category"], questions=item["questions"],
                  answer_text="نشانی تازه: {address}", needs_staff=False, enabled=True, actor="x")
    assert faq.answer(db, "آدرس فروشگاه کجاست")["answer"].startswith("نشانی تازه")
    assert next(i for i in faq.load_data()["items"] if i["id"] == "address")["answer"] != ""
    faq.remove_item(db, "address")
    assert not faq.answer(db, "آدرس فروشگاه کجاست")["answer"].startswith("نشانی تازه")


def test_a_switched_off_item_is_not_used(db):
    item = next(i for i in faq.all_items(db) if i["id"] == "address")
    faq.save_item(db, "address", category=item["category"], questions=item["questions"],
                  answer_text=item["answer"], needs_staff=False, enabled=False, actor="x")
    assert faq.answer(db, "آدرس فروشگاه کجاست").get("id") != "address"


def test_a_new_item_is_answered(db):
    faq.save_item(db, None, category="هدیه", questions=["آیا هدیه هم می‌دهید؟"],
                  answer_text="بله، بسته هدیه داریم.", needs_staff=False, enabled=True, actor="x")
    assert faq.answer(db, "آیا هدیه هم می‌دهید؟")["answer"] == "بله، بسته هدیه داریم."


def test_a_bad_item_says_why(db):
    for kwargs, word in (({"questions": []}, "پرسش"), ({"answer_text": " "}, "پاسخ"),
                         ({"answer_text": "با {nothing}"}, "جای‌خالی")):
        values = dict(category="x", questions=["یک پرسش"], answer_text="پاسخ", needs_staff=False,
                      enabled=True, actor="x")
        values.update(kwargs)
        try:
            faq.save_item(db, None, **values)
        except ValueError as exc:
            assert word in str(exc)
        else:
            raise AssertionError(kwargs)


def test_a_long_number_stays_out_of_the_log(db):
    faq.answer(db, "آدرس فروشگاه کجاست 0499370899")
    assert "0499370899" not in str(faq.report(db))


# ---- learning ----------------------------------------------------------------------------------
def test_a_reply_becomes_a_suggestion(db):
    row = faq.suggest(db, "کیف چرمی مخصوص تبلت را چطور بشویم", "با کد سریال هم پیگیری می‌شود.", 3, "mina")
    assert row["status"] == "pending" and faq.suggestions(db)[0]["id"] == row["id"]


def test_not_for_a_price_or_a_long_number(db):
    question = "کیف چرمی مخصوص تبلت را چطور بشویم"
    assert faq.suggest(db, question, "قیمتش ۲۵٬۰۰۰٬۰۰۰ است.", 3, "m") is None
    assert faq.suggest(db, question, "می‌شود ۵۰۰ هزار تومان", 3, "m") is None
    assert faq.suggest(db, question, "کارت 6037991234567890 را بزنید", 3, "m") is None
    assert faq.suggest(db, "کد ملی من 0499370899 است چکار کنم", "ثبت شد برای شما", 3, "m") is None
    assert faq.suggestions(db) == []


def test_not_what_the_bank_answers_and_not_twice(db):
    assert faq.suggest(db, "آدرس فروشگاه کجاست", "مشهد است، خیابان اصلی", 3, "m") is None
    question = "کیف چرمی مخصوص تبلت را چطور بشویم"
    assert faq.suggest(db, question, "با کد سریال پیگیری می‌شود.", 3, "m") is not None
    assert faq.suggest(db, question, "پاسخ دیگری برای همین", 4, "s") is None


def test_a_suggestion_is_not_used_until_approved(db):
    question = "کیف چرمی مخصوص تبلت را چطور بشویم"
    faq.suggest(db, question, "با کد سریال پیگیری می‌شود.", 3, "m")
    assert "سریال" not in str(faq.answer(db, question).get("answer") or "")


def _reply(client, db, text: str, question: str = "کیف چرمی مخصوص تبلت را چطور بشویم"):
    client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "5", "name": "x", "phone": "09120000005"})
    request_id = client.post("/item-requests", headers=h("bot"), json={
        "platform": "bale", "chat_id": "5", "text": question}).json()["id"]
    boss = staff(db, "super_admin", "boss")
    r = client.post(f"/admin/item-requests/{request_id}/messages", json={"text": text}, headers=boss)
    assert r.status_code == 201, r.text
    return boss


def test_a_real_reply_makes_a_suggestion_and_approving_teaches(client, db, reader):
    seed_products(reader)
    boss = _reply(client, db, "با کد سریال هم پیگیری می‌شود.")
    page = client.get("/admin/faq", headers=boss).json()
    assert page["enabled"] is True and len(page["items"]) >= 42
    suggestion = page["suggestions"][0]
    question = suggestion["question"]
    r = client.post(f"/admin/faq/suggestions/{suggestion['id']}/approve", headers=boss, json={
        "category": "گارانتی", "questions": [question], "answer": suggestion["answer"]})
    assert r.status_code == 200 and r.json()["source"] == "custom"
    assert client.get("/admin/faq", headers=boss).json()["suggestions"] == []
    assert "سریال" in faq.answer(db, question)["answer"]
    r = client.post(f"/admin/faq/suggestions/{suggestion['id']}/reject", headers=boss)
    assert r.status_code == 409


def test_rejecting_teaches_nothing(client, db, reader):
    seed_products(reader)
    boss = _reply(client, db, "با کد سریال هم پیگیری می‌شود.")
    suggestion = client.get("/admin/faq", headers=boss).json()["suggestions"][0]
    assert client.post(f"/admin/faq/suggestions/{suggestion['id']}/reject",
                       headers=boss).status_code == 200
    assert client.get("/admin/faq", headers=boss).json()["suggestions"] == []


def test_the_page_needs_its_ticks(client, db):
    mina = staff(db, "operator", "mina")
    assert client.get("/admin/faq", headers=mina).status_code == 403
    db._conn.execute("UPDATE staff_users SET perm_grant='faq.view' WHERE username='mina'")
    db._conn.commit()
    assert client.get("/admin/faq", headers=mina).status_code == 200
    assert client.post("/admin/faq/items", json=_item(), headers=mina).status_code == 403
    db._conn.execute("UPDATE staff_users SET perm_grant='faq.edit' WHERE username='mina'")
    db._conn.commit()
    answer = client.post("/admin/faq/items", json=_item(), headers=mina)
    assert answer.status_code == 201
    r = client.put(f"/admin/faq/items/{answer.json()['id']}", json=_item(answer="پاسخ {nothing}"),
                   headers=mina)
    assert r.status_code == 422
    assert client.put("/admin/faq/items/none", json=_item(), headers=mina).status_code == 404
    assert client.delete(f"/admin/faq/items/{answer.json()['id']}", headers=mina).status_code == 200


def test_the_switch_turns_all_of_it_off(client, db):
    boss = staff(db, "super_admin", "boss")
    client.put("/admin/shop-rules/faq", json={"enabled": False}, headers=boss)
    assert faq.answer(db, "آدرس فروشگاه کجاست") == {}
