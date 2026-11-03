"""v2.17.0 in the bot: the customer's details, the order's address, staff notifications."""
from __future__ import annotations

import pytest

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_v280 import _shop


@pytest.fixture
def details(shopapi):
    """The real server's answers on top of the bots' fake shopapi."""
    state = {"missing": ["first_name", "last_name", "national_code", "address"], "address": "",
             "asked": False, "known": True, "saved": [], "orders": [], "links": {},
             "due": [], "claims": [], "refuse": set()}
    original = shopapi.handler

    def handler(request):
        import json

        import httpx

        path = request.url.path
        method = request.method
        body = json.loads(request.content or b"null") if request.content else None

        def reply(status, payload):
            return httpx.Response(status, json=payload, request=request)

        def view():
            out = {k: state[k] for k in ("missing", "address", "asked", "known")}
            if state.get("prefill"):
                out["prefill"] = state["prefill"]
            return out

        if path.endswith("/details") and path.startswith("/users/"):
            if method == "POST":
                for field, value in (body or {}).items():
                    if field == "finished":
                        state["asked"] = bool(value)
                        continue
                    if field in state["refuse"]:
                        return reply(422, {"detail": state.get("refuse_text") or "Invalid value"})
                    state["saved"].append((field, value))
                    state["missing"] = [f for f in state["missing"] if f != field]
                    if field == "address":
                        state["address"] = value
            return reply(200, view())
        if method == "POST" and path == "/orders" and body and "ship_address" in body:
            state["orders"].append(body["ship_address"])
        if method == "PUT" and path.endswith("/address"):
            state["orders"].append(body["address"])
            return reply(200, {"ship_address": body["address"]})
        if path == "/staff-links":
            name = state["links"].get(body["phone"])
            return reply(200, {"linked": True, "name": name} if name else {"linked": False})
        if path == "/admin/staff-alerts/due":
            due, state["due"] = state["due"], []
            return reply(200, {"items": due})
        if path == "/admin/staff-alerts/claim":
            state["claims"].append(body)
            return reply(200, state.get("claim_answer") or {"claimed": True})
        return original(request)

    shopapi.handler = handler
    return state


def _texts(bot_apis, platform="bale", chat=CUSTOMER_CHAT):
    return [m["text"] for m in bot_apis[platform].sent if str(m.get("chat_id")) == str(chat)]


async def _contact(engine, update_id, chat, phone="09121112222"):
    await push_message(engine, "bale", update_id, chat, contact={
        "phone_number": phone, "user_id": int(chat), "first_name": "نام"})


# ---- #9 asking -----------------------------------------------------------------------------------
def test_new_customer_is_asked_after_sharing_the_phone(env, bot_apis, shopapi, details):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        said = _texts(bot_apis)
        assert texts.DETAILS_INTRO in said and said[-1].startswith(texts.ASK_FIRST_NAME)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="علی")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_LAST_NAME)
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="رضایی")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_NATIONAL_CODE)
        await push_message(engine, "bale", 5, CUSTOMER_CHAT, text="0499370899")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_ADDRESS)
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, text="تهران، ولیعصر، پلاک 1")
        said = _texts(bot_apis)
        assert texts.DETAILS_DONE in said
        assert details["asked"] is True
        assert [f for f, _v in details["saved"]] == ["first_name", "last_name", "national_code",
                                                     "address"]

    env(scenario)


def test_only_what_is_missing_is_asked(env, bot_apis, shopapi, details):
    details["missing"] = ["national_code"]

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        said = "\n".join(_texts(bot_apis))
        assert texts.ASK_NATIONAL_CODE in said and texts.ASK_FIRST_NAME not in said

    env(scenario)


def test_a_bad_national_code_is_asked_again(env, bot_apis, shopapi, details):
    details["missing"] = ["national_code"]
    details["refuse"] = {"national_code"}

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="1111111111")
        assert _texts(bot_apis)[-1].startswith(texts.INVALID_NATIONAL_CODE)
        assert details["saved"] == [] and details["asked"] is False

    env(scenario)


def test_there_is_no_later_any_more(env, bot_apis, shopapi, details):
    """v2.18.0: an old «فعلاً نه» button and every /start ask again until all four are there."""
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert "BTN_DETAILS_LATER" not in vars(texts)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "dno")
        assert details["asked"] is False
        assert _texts(bot_apis)[-1].startswith(texts.ASK_FIRST_NAME)
        count = len(_texts(bot_apis))
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="/start")
        assert texts.ASK_FIRST_NAME in "\n".join(_texts(bot_apis)[count:])

    env(scenario)


def test_start_during_the_questions_asks_again_from_where_it_stands(env, bot_apis, shopapi, details):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="علی")
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="/start")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_LAST_NAME)

    env(scenario)


def test_unknown_details_ask_nothing(env, bot_apis, shopapi, details):
    details["known"] = False
    details["missing"] = []

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert texts.DETAILS_INTRO not in _texts(bot_apis)
        assert texts.MAIN_MENU in _texts(bot_apis)[-1]

    env(scenario)


# ---- #10 the address of an order --------------------------------------------------------------------
async def _cart(engine):
    await push_message(engine, "bale", 10, CUSTOMER_CHAT, text="101")
    await push_callback(engine, "bale", 11, CUSTOMER_CHAT, "add:101:1")


def _registered(shopapi, details):
    shopapi.users[("bale", str(CUSTOMER_CHAT))] = {
        "id": 1, "platform": "bale", "chat_id": str(CUSTOMER_CHAT), "name": "علی",
        "phone": "09121112222", "status": "approved", "person_code": 7001}
    details["asked"] = True
    details["missing"] = []


def test_no_saved_address_is_asked_and_goes_on_the_order(env, bot_apis, shopapi, details):
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _cart(engine)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "checkout")
        assert _texts(bot_apis)[-1].startswith(texts.CHECKOUT_ASK_ADDRESS)
        assert details["orders"] == [] and not shopapi.orders
        await push_message(engine, "bale", 13, CUSTOMER_CHAT, text="کم")
        assert _texts(bot_apis)[-1].startswith(texts.INVALID_ADDRESS)
        await push_message(engine, "bale", 14, CUSTOMER_CHAT, text="تهران، ولیعصر، پلاک 1")
        assert details["orders"] == ["تهران، ولیعصر، پلاک 1"]

    env(scenario)


def test_saved_address_is_offered(env, bot_apis, shopapi, details):
    _shop(shopapi)
    _registered(shopapi, details)
    details["address"] = "آدرس ثبت‌شده"

    async def scenario(engine, adapters, api):
        await _cart(engine)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "checkout")
        assert "آدرس ثبت‌شده" in _texts(bot_apis)[-1]
        assert not shopapi.orders
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "cok")
        assert details["orders"] == ["آدرس ثبت‌شده"]

    env(scenario)


def test_new_address_is_for_this_order(env, bot_apis, shopapi, details):
    _shop(shopapi)
    _registered(shopapi, details)
    details["address"] = "آدرس ثبت‌شده"

    async def scenario(engine, adapters, api):
        await _cart(engine)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "checkout")
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "cnew")
        assert _texts(bot_apis)[-1].startswith(texts.CHECKOUT_NEW_ADDRESS)
        await push_message(engine, "bale", 14, CUSTOMER_CHAT, text="مشهد، احمدآباد، پلاک 2")
        assert details["orders"] == ["مشهد، احمدآباد، پلاک 2"]

    env(scenario)


def test_leaving_the_address_question_never_places_an_order(env, bot_apis, shopapi, details):
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _cart(engine)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "checkout")
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "cart")     # the prompt's button
        await push_message(engine, "bale", 14, CUSTOMER_CHAT, text="کالای الف را می‌خواهم")
        assert details["orders"] == [] and not shopapi.orders

    env(scenario)


def test_leaving_the_questions_keeps_a_later_text_out_of_the_answers(env, bot_apis, shopapi,
                                                                     details):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "menu")
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="آیفون")
        assert details["saved"] == []
        assert details["asked"] is False            # asked again next time

    env(scenario)


def test_a_location_is_not_an_address(env, bot_apis, shopapi, details):
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _cart(engine)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "checkout")
        await push_message(engine, "bale", 13, CUSTOMER_CHAT, text="")
        assert _texts(bot_apis)[-1].startswith(texts.INVALID_ADDRESS)
        assert details["orders"] == []

    env(scenario)


# ---- #12 staff ------------------------------------------------------------------------------------------
def test_staff_link_by_sharing_the_phone(env, bot_apis, shopapi, details):
    details["links"]["09121112222"] = "مینا"

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        said = _texts(bot_apis)
        assert "مینا" in said[-1] and "وصل شد" in said[-1]
        assert ("bale", str(CUSTOMER_CHAT)) not in shopapi.users   # no customer account
        assert texts.DETAILS_INTRO not in said

    env(scenario)


def test_staff_command_links_an_existing_customer_chat(env, bot_apis, shopapi, details):
    _registered(shopapi, details)
    details["links"]["09121112222"] = "مینا"

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/staff")
        assert _texts(bot_apis)[-1].startswith(texts.STAFF_ASK_CONTACT)
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert "مینا" in _texts(bot_apis)[-1]

    env(scenario)


def test_staff_command_with_a_strangers_number(env, bot_apis, shopapi, details):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/staff")
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert _texts(bot_apis)[-1] == texts.STAFF_NOT_FOUND

    env(scenario)


def test_someone_elses_contact_links_nothing(env, bot_apis, shopapi, details):
    details["links"]["09121112222"] = "مینا"

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/staff")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact={
            "phone_number": "09121112222", "user_id": 999999, "first_name": "x"})
        assert "مینا" not in _texts(bot_apis)[-1]

    env(scenario)


def test_alerts_reach_every_chat_with_a_claim_button(env, bot_apis, shopapi, details):
    details["due"] = [{"kind": "order", "target_type": "order", "target_id": 12, "total": 1000.0,
                       "label": "گوشی", "repeat": 0, "chats": ["501", "502"]}]

    async def scenario(engine, adapters, api):
        assert await engine.deliver_staff_alerts() == 2
        for chat in ("501", "502"):
            sent = _texts(bot_apis, chat=chat)
            assert len(sent) == 1 and "سفارش تازه" in sent[0] and "گوشی" in sent[0]
        last = bot_apis["bale"].sent[-1]
        assert "sao:12" in str(last.get("reply_markup"))

    env(scenario)


def test_a_repeat_says_so(env, bot_apis, shopapi, details):
    details["due"] = [{"kind": "receipt", "target_type": "order", "target_id": 12, "total": 1.0,
                       "label": "x", "repeat": 3, "chats": ["501"]}]

    async def scenario(engine, adapters, api):
        await engine.deliver_staff_alerts()
        said = _texts(bot_apis, chat="501")[0]
        assert texts.STAFF_ALERT_REPEAT in said and "رسید تازه" in said

    env(scenario)


def test_summary_has_counts_and_no_button(env, bot_apis, shopapi, details):
    details["due"] = [{"kind": "summary", "counts": {"order": 2, "receipt": 1, "request": 0},
                       "chats": ["501"]}]

    async def scenario(engine, adapters, api):
        await engine.deliver_staff_alerts()
        last = bot_apis["bale"].sent[-1]
        assert "خلاصه" in last["text"] and not last.get("reply_markup")

    env(scenario)


def test_request_alert_uses_its_own_button(env, bot_apis, shopapi, details):
    details["due"] = [{"kind": "request", "target_type": "request", "target_id": 7, "total": 0,
                       "label": "آیفون", "repeat": 0, "chats": ["501"]}]

    async def scenario(engine, adapters, api):
        await engine.deliver_staff_alerts()
        assert "sar:7" in str(bot_apis["bale"].sent[-1].get("reply_markup"))

    env(scenario)


@pytest.mark.parametrize("answer,text", [
    ({"claimed": True}, "STAFF_CLAIMED"),
    ({"claimed": False, "reason": "taken"}, "STAFF_CLAIM_TAKEN"),
    ({"claimed": False, "reason": "gone"}, "STAFF_CLAIM_GONE"),
    ({"claimed": False, "reason": "not_allowed"}, "STAFF_CLAIM_DENIED"),
])
def test_claim_answers(env, bot_apis, shopapi, details, answer, text):
    details["claim_answer"] = answer

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, "501", "sao:12")
        assert details["claims"] == [{"platform": "bale", "chat_id": "501",
                                      "target_type": "order", "target_id": 12}]
        edited = [c for c in bot_apis["bale"].calls if c[0] in ("edit_text", "editMessageText")]
        assert getattr(texts, text) in str(edited or bot_apis["bale"].calls)

    env(scenario)


def test_a_customer_cannot_claim(env, bot_apis, shopapi, details):
    """The server decides: a chat without a link gets not_linked; no customer action runs."""
    details["claim_answer"] = {"claimed": False, "reason": "not_linked"}

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "sao:12")
        assert ("bale", str(CUSTOMER_CHAT)) not in shopapi.users

    env(scenario)


# ---- #2 --------------------------------------------------------------------------------------------------
def test_admin_chat_is_told_when_nothing_was_written():
    assert "ثبت نشد" in texts.ADMIN_PAYMENT_NOT_WRITTEN
    assert "ثبت در حسابداری" in texts.ADMIN_PAYMENT_NOT_WRITTEN
