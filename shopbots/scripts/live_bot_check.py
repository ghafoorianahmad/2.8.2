"""v2.18.1: the real bot engine against the real shopapi over real HTTP (accounting and Bale are fake:
``shopapi/scripts/live_fake_accounting.py`` first). What the fakes of each side's tests cannot prove:
that the two really agree.

    python scripts/live_bot_check.py 18765
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

from app import texts  # noqa: E402
from app.config import Settings  # noqa: E402
from app.engine import BotEngine  # noqa: E402
from app.platforms import BaleAdapter  # noqa: E402
from app.shopapi import ShopApiClient  # noqa: E402
from app.store import Store  # noqa: E402
from tests.conftest import FakeBotApi, push_callback, push_message  # noqa: E402

CODE = "0499370899"
ADDRESS = "تهران، خیابان ولیعصر، پلاک ۱۲"
BOSS = {"Authorization": "Bearer live-check-boss"}
checks: list[tuple[str, bool]] = []


def check(what: str, ok: bool) -> None:
    checks.append((what, bool(ok)))
    print(("ok  " if ok else "FAIL"), what, flush=True)


def said(bot) -> list[str]:
    return [str(m.get("text") or "") for m in bot.sent]


def links(bot) -> list[str]:
    found = []
    for message in bot.sent:
        markup = message.get("reply_markup")
        markup = json.loads(markup) if isinstance(markup, str) else markup
        for row in (markup or {}).get("keyboard") or ():
            for button in row:
                if isinstance(button, dict) and button.get("web_app"):
                    found.append(button["web_app"]["url"])
    return found


async def contact(engine, update_id: int, chat: str, phone: str) -> None:
    await push_message(engine, "bale", update_id, chat, contact={
        "phone_number": phone, "user_id": int(chat), "first_name": "نام"})


async def run(base: str) -> None:
    settings = Settings(shopapi_base_url=base, bot_api_key="bot-key", admin_api_key="admin-key",
                        bale_token="FAKE", bale_api_base="https://bale.test", sqlite_path=":memory:",
                        poll_timeout=1, miniapp_url="https://shop.test/app/")
    bot = FakeBotApi()
    bale = httpx.AsyncClient(transport=httpx.MockTransport(bot.handler))
    api = ShopApiClient(settings)
    engine = BotEngine(settings, Store(":memory:"), api,
                       {"bale": BaleAdapter(token="FAKE", api_base="https://bale.test", client=bale)})
    staff = httpx.AsyncClient(base_url=base, headers=BOSS, timeout=120)
    chat = "7001"

    # ---- a new customer: only what is missing, nothing else before it, no value ever echoed
    await push_message(engine, "bale", 1, chat, text="/start")
    await contact(engine, 2, chat, "09121112222")
    check("a new customer is asked for the first name", said(bot)[-1].startswith(texts.ASK_FIRST_NAME))
    query = parse_qs(urlparse(links(bot)[-1]).query)
    check("the form link has no national code or address", not {"nc", "addr"} & set(query))
    check("the link says both are needed", query.get("need") == ["nc,addr"])
    await push_callback(engine, "bale", 3, chat, "menu")
    check("a button waits for the details", said(bot)[-1].startswith(texts.ASK_FIRST_NAME))
    for update_id, answer in ((4, "علی"), (5, "رضایی")):
        await push_message(engine, "bale", update_id, chat, text=answer)
    check("then the national code", said(bot)[-1].startswith(texts.ASK_NATIONAL_CODE))
    await push_message(engine, "bale", 6, chat, text="1111111111")
    check("the server refuses a bad national code", "کد ملی" in said(bot)[-1])
    await push_message(engine, "bale", 7, chat, text=CODE)
    check("then the address", said(bot)[-1].startswith(texts.ASK_ADDRESS))
    await push_message(engine, "bale", 8, chat, text=ADDRESS)
    details = await api.customer_details("bale", chat)
    check("nothing is missing now", details.get("missing") == [] and details.get("has_address"))
    check("the answer holds no value", CODE not in str(details) and "ولیعصر" not in str(details))
    user = await api.get_user("bale", chat)
    check("the user towards the bot holds no value",
          not user.get("national_code") and not user.get("address")
          and user.get("national_code_on_file") and user.get("address_on_file"))

    # ---- on file: a page cannot change it
    await api.save_customer_details("bale", chat, national_code="1234567891", address="مشهد، احمدآباد")
    row = (await staff.get(f"/admin/users/{user['id']}")).json()
    check("what is on file stays", row["national_code"] == CODE and "ولیعصر" in row["address"])

    # ---- an order
    product = (await staff.get("/products/101")).json()
    engine.cart.add("bale", chat, 101, product["name"], 1, product["unit_price"])
    await push_callback(engine, "bale", 9, chat, "checkout")
    check("the address is offered without saying it", said(bot)[-1].startswith(
        texts.CHECKOUT_CONFIRM_ADDRESS))
    await push_callback(engine, "bale", 10, chat, "cok")
    orders = await api.list_orders("bale", chat) if hasattr(api, "list_orders") else []
    placed = (await staff.get("/admin/orders", params={"status": "awaiting_payment"})).json()
    check("the order took the saved address", placed and "ولیعصر" in placed[0]["ship_address"])
    check("the bot's copy of it does not", not [o for o in orders if o.get("ship_address")])
    everything = json.dumps(bot.sent, ensure_ascii=False)
    check("no message or link ever held either value",
          CODE not in everything and "ولیعصر" not in everything)

    # ---- a person on file in «سازه حساب»: nothing is asked
    other = "7002"
    await push_message(engine, "bale", 20, other, text="/start")
    await contact(engine, 21, other, "09121113333")
    answer = await api.customer_details("bale", other)
    who = await api.get_user("bale", other)
    await staff.post(f"/admin/users/{who['id']}/approve", json={"person_code": 7001})
    answer = await api.customer_details("bale", other)
    check("a person with all four is not asked", answer.get("missing") == [])

    # ---- the customers' calculator: off, then on
    engine._installment_state = (-1000.0, False)
    await push_callback(engine, "bale", 30, chat, "menu")
    menu = json.dumps(bot.sent[-1], ensure_ascii=False)
    check("off: no button", texts.BTN_INSTALLMENT not in menu)
    await push_callback(engine, "bale", 31, chat, "inst")
    check("off: an old button says so", said(bot)[-1].startswith(texts.INSTALLMENT_OFF))
    await staff.put("/admin/installments/settings", json={"customer_enabled": True})
    engine._installment_state = (-1000.0, False)
    await push_callback(engine, "bale", 32, chat, "menu")
    check("on: the button", texts.BTN_INSTALLMENT in json.dumps(bot.sent[-1], ensure_ascii=False))
    await push_message(engine, "bale", 33, chat, text="/aghsat")
    check("on: the page is offered", any("app/installment/" in link for link in links(bot)))
    photos = len(bot.photos)
    for update_id, answer_text in ((34, "۲۰۰٬۰۰۰٬۰۰۰"), (35, "50%"), (36, "5")):
        await push_message(engine, "bale", update_id, chat, text=answer_text)
    got_photo = len(bot.photos) > photos
    check("the customer gets the card (image, or its text without a browser)",
          got_photo or "۲۴۰٬۰۰۰٬۰۰۰" in said(bot)[-1])
    print("     card sent as", "an image" if got_photo else "text", flush=True)
    check("no rate or interest said", all("سود" not in t and "نرخ" not in t for t in said(bot)[-3:]))

    # ---- a card staff send
    sheet = {"phone_name": "Galaxy S25", "price": 200_000_000, "down": 100_000_000, "rate": "8",
             "checks": [28_000_000] * 5, "dates": ["1405/09/15", "1405/10/15", "1405/11/15",
                                                   "1405/12/15", "1406/01/15"]}
    sent = (await staff.post("/admin/installments/send",
                             json={"user_id": user["id"], "sheet": sheet})).json()
    check("the quote waits for the bot", sent.get("status") == "pending")
    await engine._deliver_installment_card(int(sent["id"]))
    rows = (await staff.get("/admin/installments/quotes")).json()
    check("the bot delivered it and said so", rows[0]["id"] == sent["id"] and rows[0]["status"] == "sent")
    check("staff see the interest in the history", rows[0]["interest"] == 40_000_000)

    # ---- a reply
    made = await api.create_item_request("bale", chat, text="کیف چرمی برای تبلت دارید؟")
    request_id = made["id"]
    url = f"/admin/item-requests/{request_id}/messages"
    r = await staff.post(url, json={"text": "مدل {product} موجود شد"})
    check("a reply with a gap is refused", r.status_code == 422)
    r = await staff.post(url, json={"text": f"کد ملی شما {CODE} است"})
    check("a reply with the national code is refused", r.status_code == 422)
    templates = (await staff.get(f"/admin/item-requests/{request_id}/reply-templates")).json()
    check("the ready replies are filled", "علی رضایی" in next(
        t["text"] for t in templates["templates"] if t["id"] == "greet"))
    r = await staff.post(url, json={"text": "بله، کیف چرمی برای تبلت موجود داریم."})
    check("a plain reply goes", r.status_code == 201)
    page = (await staff.get("/admin/faq")).json()
    check("it became a suggestion for the auto-responder", any(
        s["request_id"] == request_id for s in page["suggestions"]))

    await bale.aclose()
    await staff.aclose()


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "18765"
    asyncio.run(run(f"http://127.0.0.1:{port}"))
    good = sum(1 for _what, ok in checks if ok)
    print(f"{good} of {len(checks)}")
    return 0 if good == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
