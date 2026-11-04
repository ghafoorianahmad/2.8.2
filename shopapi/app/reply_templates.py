"""v2.18.1 ready replies for staff (``data/reply_templates.json``, the owner's 56 templates).

The server fills what it knows; what it does not know stays as ``{product}`` for staff to write, and
a reply with such a gap is not sent. Item 16 holds here too: the customer's national code and
address never go into a message. Where a template speaks of the customer's own address it says
«نشانی ثبت‌شدهٔ شما»; ``{address}`` and ``{phone}`` elsewhere are the shop's. A template asking for
something that is already on file is not offered at all.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).with_name("data") / "reply_templates.json"
PLACEHOLDERS = ("customer_name", "product", "color", "price", "order_no", "address", "phone", "hours")
#: what these say about the customer's own address (the rest: the shop's)
CUSTOMER_ADDRESS = frozenset({"delivery_courier_sent", "delivery_post_tracking",
                              "delivery_coord_time", "delivery_driver_call", "ask_address_confirm"})
#: where ``{phone}`` is the customer's own number (it is theirs: it may be said to them)
CUSTOMER_PHONE = frozenset({"stock_out_notify", "delivery_driver_call", "ask_address_confirm"})
ADDRESS_ON_FILE = "نشانی ثبت‌شدهٔ شما"
#: offered only while the customer's value is missing
ASKS_NATIONAL_CODE = "درخواست کد ملی"
ASKS_ADDRESS = "درخواست آدرس و مشخصات"
#: this one asks to confirm what is on file: only when there is one
CONFIRMS_ADDRESS = "ask_address_confirm"
_GAP = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


@lru_cache(maxsize=1)
def load_data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def gaps(text: str) -> list[str]:
    """The placeholders still in a text (none = it may be sent)."""
    return _GAP.findall(str(text or ""))


def offered(template: dict, *, has_national_code: bool, has_address: bool) -> bool:
    """Item 16: never ask a customer for what is on file."""
    if template["id"] == CONFIRMS_ADDRESS:
        return has_address
    if template["category"] == ASKS_NATIONAL_CODE:
        return not has_national_code
    if template["category"] == ASKS_ADDRESS:
        return not has_address
    return True


def fill(template: dict, values: dict) -> str:
    """The template's text with what is known; the rest stays as ``{name}``."""
    template_id = template["id"]

    def one(match: re.Match) -> str:
        key = match.group(1)
        if key == "address":
            return ADDRESS_ON_FILE if template_id in CUSTOMER_ADDRESS else values.get("shop_address", "") or match.group(0)
        if key == "phone":
            source = "customer_phone" if template_id in CUSTOMER_PHONE else "shop_phone"
            return values.get(source, "") or match.group(0)
        return str(values.get(key) or "") or match.group(0)

    return _GAP.sub(one, str(template["text"]))


def build(values: dict, *, has_national_code: bool = True, has_address: bool = True) -> dict:
    """What ShopAdmin shows for this customer: {"categories": [...], "templates": [...]}."""
    out, categories = [], []
    for template in load_data()["templates"]:
        if not offered(template, has_national_code=has_national_code, has_address=has_address):
            continue
        text = fill(template, values)
        if template["category"] not in categories:
            categories.append(template["category"])
        out.append({"id": template["id"], "category": template["category"],
                    "title": template["title"], "text": text, "missing": gaps(text)})
    return {"categories": categories, "templates": out}


def mentions_private(text: str, national_code: object, address: object) -> bool:
    """A reply that holds this customer's national code or address word for word."""
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    flat = "".join(str(text or "").translate(digits).split())
    code = "".join(str(national_code or "").translate(digits).split())
    place = "".join(str(address or "").translate(digits).split())
    return bool((code and code in flat) or (len(place) >= 8 and place in flat))
