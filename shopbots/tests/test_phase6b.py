"""Phase 6b: the bot resolves site model references (REQUIREMENTS §9a) -
deep link m_<slug>, the copied «name + کد مدل» text, a bare slug or a name.
A hidden, unmapped or unknown model is never guessed: polite text + phone."""
from __future__ import annotations

from app import texts
from app.core import looks_like_model_ref, parse_product_ref

from .conftest import CUSTOMER_CHAT, own_contact, push_callback, push_message

NL = chr(10)
COPIED = "iPhone 17 Pro" + NL + "کد مدل: iphone-17-pro"


def _callbacks(api, chat_id):
    return [cb for row in api.buttons_for(chat_id) for _, cb in row]


def _models(shopapi):
    shopapi.models = {
        "iphone-17-pro": {"name": "iPhone 17 Pro", "items": [
            {"kala_code": 101, "label": "256 گیگ"}, {"kala_code": 102, "label": "512 گیگ"}]},
        "iphone-17": {"name": "iPhone 17", "items": [{"kala_code": 104, "label": "128 گیگ"}]},
        "galaxy-s25-ultra": {"name": "Galaxy S25 Ultra", "status": "unavailable"},
    }


def test_model_ref_shape():
    for sent in ("m_iphone-17-pro", COPIED, "كد مدل: x", "iphone-17-pro", "poco-x7"):
        assert looks_like_model_ref(sent), sent
        assert parse_product_ref(sent, allow_bare_code=True) is None
    for sent in ("سلام", "iphone", "kala_289", "289", "", None, "a" * 500):
        assert not looks_like_model_ref(sent), sent


def test_deep_link_with_one_product_opens_it(env, bot_apis, shopapi):
    _models(shopapi)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start m_iphone-17")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "کالای د" in body and "4,000" in body
        assert shopapi.resolve_texts == ["m_iphone-17"]

    env(scenario)


def test_model_with_several_products_offers_the_labels(env, bot_apis, shopapi):
    _models(shopapi)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text=COPIED)
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.MODEL_PICK_VARIANT.format(name="iPhone 17 Pro")
        labels = [label for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for label, _ in row]
        assert "256 گیگ" in labels and "512 گیگ" in labels
        assert {"kp:101", "kp:102"} <= set(_callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "kp:102")
        assert "کالای ب" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "add:102:1")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT)[0]["kala_code"] == 102

    env(scenario)


def test_bare_slug_and_ambiguous_name(env, bot_apis, shopapi):
    _models(shopapi)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="iphone-17")
        assert "کالای د" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        # an edited text: the name matches two models -> the customer chooses
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="iphone 17")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.MODEL_AMBIGUOUS
        assert {"mdl:0", "mdl:1"} <= set(_callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "mdl:1")
        assert shopapi.resolve_texts[-1] in ("m_iphone-17-pro", "m_iphone-17")
        # a stale option index never guesses
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "mdl:2")
        assert texts.MAIN_MENU in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_hidden_unmapped_or_unknown_model_gets_the_phone_not_a_guess(env, bot_apis, shopapi):
    _models(shopapi)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start m_galaxy-s25-ultra")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert body == texts.MODEL_UNAVAILABLE.format(name="Galaxy S25 Ultra")
        assert texts.SHOP.get("shop_phone", "") in body
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="کد مدل: nokia-3310")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.MODEL_UNKNOWN
        assert not any(cb.startswith(("kp:", "prod:", "add:"))
                       for cb in _callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        # plain chat that is not a model: the main menu, as before
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="سلام")
        assert texts.MAIN_MENU in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_model_typed_before_registration_is_shown_after_it(env, bot_apis, shopapi):
    _models(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text=COPIED)
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.MODEL_AFTER_CONTACT
        assert shopapi.resolve_texts == []          # resolved only after registration
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.MODEL_PICK_VARIANT.format(name="iPhone 17 Pro")

    env(scenario)


def test_deep_link_survives_registration(env, bot_apis, shopapi):
    _models(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start m_iphone-17")
        assert texts.ASK_CONTACT in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert "کالای د" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_shopapi_down_on_a_model_ref_says_so(env, bot_apis, shopapi):
    _models(shopapi)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        shopapi.down = True
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="m_iphone-17")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SERVICE_UNAVAILABLE

    env(scenario)
