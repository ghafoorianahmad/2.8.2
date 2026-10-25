"""Activity log entries as simple Persian sentences (v2.8.0).

shopapi returns the actor's name only to the manager; a sales user gets
``is_me`` / ``to_me`` and sees «شما» or «همکار», never a name.
Example timeline: «احمد رسید را تأیید کرد ← به علی ارجاع داد ← علی ارسال کرد».
"""
from __future__ import annotations

from .persian import to_persian_digits

#: action -> sentence after the actor ({to} = the colleague it went to)
ACTION_FA = {
    "claim": "کار را برداشت",
    "assign": "به {to} ارجاع داد",
    "handover": "کار را به {to} سپرد",
    "customer_approve": "مشتری را تأیید کرد",
    "customer_reject": "مشتری را رد کرد",
    "receipt_approve": "رسید را تأیید کرد",
    "receipt_reject": "رسید را رد کرد",
    "ship": "ارسال کرد",
    "cancel": "سفارش را لغو کرد",
    "reply": "به مشتری پیام داد",
    "note": "یادداشت گذاشت",
    "request_status": "وضعیت درخواست را عوض کرد",
    "stock_confirm": "موجودی را تأیید کرد و سفارش ساخت",
    # v2.9.2: the price goes to the customer; the customer answers in the bot
    "price_offer": "قیمت را برای تأیید مشتری فرستاد",
    "offer_accept": "مشتری «تأیید و خرید» زد و سفارش ساخته شد",
    "offer_decline": "مشتری قیمت را نخواست («نمی‌خواهم»)",
    "stock_unavailable": "«ناموجود» اعلام کرد",
    "archive": "کارهای تمام‌شده را بایگانی کرد",
    "payment_info": "اطلاعات پرداخت را برای مشتری فرستاد",
}

TARGET_FA = {"order": "سفارش", "request": "درخواست", "customer": "مشتری", "archive": "بایگانی"}


def actor_fa(entry: dict) -> str:
    if entry.get("actor_name"):
        return str(entry["actor_name"])
    if entry.get("is_me"):
        return "شما"
    if entry.get("system"):
        return "سیستم"
    return "همکار"


def to_fa(entry: dict) -> str:
    if entry.get("to_name"):
        return str(entry["to_name"])
    return "شما" if entry.get("to_me") else "همکار"


#: v2.9.2: steps the customer took in the bot (the sentence names the customer)
CUSTOMER_ACTIONS = frozenset({"offer_accept", "offer_decline"})


def sentence(entry: dict, *, with_actor: bool = True) -> str:
    template = ACTION_FA.get(str(entry.get("action") or ""), "کاری انجام داد")
    if entry.get("action") in CUSTOMER_ACTIONS:
        return template
    if entry.get("from_name") and entry.get("action") == "assign":
        # v2.8.3 (manager only): whose work was moved
        template = "کار {from_} را به {to} ارجاع داد"
    text = template.format(to=to_fa(entry), from_=str(entry.get("from_name") or ""))
    return f"{actor_fa(entry)} {text}" if with_actor else text


def timeline_lines(entries: list[dict]) -> list[tuple[str, str]]:
    """v2.9.3: one (time, sentence) per action, oldest first, for the list in the
    order / request dialog; every sentence names who did it."""
    from .persian import format_datetime_shamsi

    out = []
    for entry in entries:
        stamp = entry.get("ts") or entry.get("at") or ""
        out.append((format_datetime_shamsi(stamp) if stamp else "—", sentence(entry)))
    return out


def timeline_text(entries: list[dict]) -> str:
    """«احمد رسید را تأیید کرد ← به علی ارجاع داد ← علی ارسال کرد»: the actor is
    named once while the same person keeps acting."""
    parts, last_actor = [], None
    for entry in entries:
        actor = actor_fa(entry)
        parts.append(sentence(entry, with_actor=actor != last_actor))
        last_actor = actor
        if entry.get("action") in ("assign", "handover"):
            last_actor = None
    return " ← ".join(parts) if parts else "هنوز کاری روی آن انجام نشده است."


def target_fa(entry: dict) -> str:
    kind = TARGET_FA.get(str(entry.get("target_type") or ""), "")
    ident = entry.get("target_id")
    return f"{kind} {to_persian_digits(ident)}" if ident is not None and kind else kind or "—"
