"""v2.9.4: no raw English or technical text ever reaches the person using the program.

* :func:`validation_text` — one pydantic validation error of shopapi (HTTP 422,
  ``{"loc", "msg", "type", "ctx"}``) as a Persian sentence with the field's Persian
  name: «price_rial: Input should be less than or equal to 100000000000» becomes
  «قیمت نباید بیشتر از ۱۰۰٬۰۰۰٬۰۰۰٬۰۰۰ باشد».
* :func:`humanize` — the last guard where an error is shown (message boxes,
  toasts, background-task failures): Python exception names and English
  sentences are replaced by Persian; a message without any Persian becomes the
  generic sentence (the original goes to the program's log only).
"""
from __future__ import annotations

import logging
import re

from .persian import to_persian_digits

log = logging.getLogger("shopadmin.messages")

GENERIC = "کار انجام نشد؛ جزئیات فنی در گزارش برنامه ثبت شد. دوباره امتحان کنید یا به مدیر خبر دهید."

#: request field -> Persian name
FIELD_LABELS = {
    "price_rial": "قیمت", "price": "قیمت", "offer_price_rial": "قیمت", "unit_price": "قیمت واحد",
    "qty": "تعداد", "quantity": "تعداد", "kala_code": "کد کالا", "product_code": "کد کالا",
    "person_code": "کد شخص", "username": "نام کاربری", "password": "گذرواژه",
    "current_password": "گذرواژهٔ فعلی", "new_password": "گذرواژهٔ جدید",
    "full_name": "نام و نام خانوادگی", "reason": "دلیل", "text": "متن", "note": "یادداشت",
    "message": "پیام", "courier_name": "نام پیک", "courier_phone": "تلفن پیک",
    "card_number": "شمارهٔ کارت", "account_number": "شمارهٔ حساب", "sheba": "شبا",
    "holder": "به نام", "bank": "بانک", "description": "توضیح", "folder": "پوشه",
    "confirm": "متن تأیید", "server": "نام سرور", "database": "نام پایگاه‌داده",
    "role": "نقش", "staff_id": "کاربر", "to_staff_id": "کاربر", "mobile": "شمارهٔ موبایل",
    "phone": "تلفن", "name": "نام", "slug": "کد مدل", "label": "برچسب", "color": "رنگ",
    "part": "پارت", "url": "نشانی", "link": "پیوند", "values": "مقدارها", "row_key": "ردیف",
    "list_id": "لیست قیمت", "order_id": "سفارش", "channel_id": "کانال",
}


def _number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return to_persian_digits(value)
    if number.is_integer():
        return to_persian_digits(f"{int(number):,}").replace(",", "٬")
    return to_persian_digits(value)


def field_label(loc) -> str:
    parts = [str(p) for p in (loc or ()) if p not in ("body", "query", "path")]
    for part in reversed(parts):
        if not part.isdigit():
            return FIELD_LABELS.get(part, "یکی از مقدارها")
    return "یکی از مقدارها"


def validation_text(item: dict) -> str:
    """One pydantic error as «<field> <problem>» in Persian."""
    name = field_label(item.get("loc"))
    kind = str(item.get("type") or "")
    ctx = dict(item.get("ctx")) if isinstance(item.get("ctx"), dict) else {}
    # an older server sends no ctx: the limit is the number in its English text
    number = re.search(r"(-?\d+(?:\.\d+)?)\s*$", str(item.get("msg") or ""))
    if number and not ctx:
        for key in ("le", "lt", "ge", "gt", "max_length", "min_length"):
            ctx[key] = number.group(1)
    if kind in ("missing", "value_error.missing"):
        return f"«{name}» لازم است"
    if kind in ("less_than_equal", "less_than"):
        limit = ctx.get("le", ctx.get("lt"))
        return f"«{name}» نباید بیشتر از {_number(limit)} باشد"
    if kind in ("greater_than_equal", "greater_than"):
        limit = ctx.get("ge", ctx.get("gt"))
        if kind == "greater_than" and str(limit) in ("0", "0.0"):
            return f"«{name}» باید بیشتر از صفر باشد"
        return f"«{name}» نباید کمتر از {_number(limit)} باشد"
    if kind in ("string_too_long", "too_long"):
        return f"«{name}» حداکثر {_number(ctx.get('max_length'))} نویسه است"
    if kind in ("string_too_short", "too_short"):
        if str(ctx.get("min_length")) == "1":
            return f"«{name}» خالی است"
        return f"«{name}» دست‌کم {_number(ctx.get('min_length'))} نویسه است"
    if kind.startswith("int") or kind.startswith("float") or kind.startswith("decimal"):
        return f"«{name}» باید عدد باشد"
    if kind.startswith("bool"):
        return f"«{name}» باید بله یا خیر باشد"
    if kind in ("string_pattern_mismatch", "value_error", "enum", "literal_error"):
        return f"«{name}» درست نیست"
    if kind.startswith("string") or kind.startswith("str"):
        return f"«{name}» باید متن باشد"
    return f"«{name}» درست نیست"


def validation_errors_text(items: list) -> str:
    parts = []
    for item in items or []:
        if isinstance(item, dict):
            text = validation_text(item)
            if text not in parts:
                parts.append(text)
    if not parts:
        return "اطلاعات واردشده درست نیست."
    return "اطلاعات واردشده درست نیست: " + "؛ ".join(parts) + "."


# ---- the last guard ---------------------------------------------------------------
#: Python exception name -> Persian
EXCEPTIONS_FA = {
    "PermissionError": "دسترسی رد شد",
    "FileNotFoundError": "فایل یا پوشه پیدا نشد",
    "NotADirectoryError": "مسیر پوشه درست نیست",
    "IsADirectoryError": "به‌جای فایل، پوشه انتخاب شده",
    "FileExistsError": "فایل از قبل وجود دارد",
    "TimeoutError": "زمان انتظار تمام شد",
    "TimeoutExpired": "زمان انتظار تمام شد",
    "ConnectionError": "ارتباط برقرار نشد",
    "ConnectionRefusedError": "ارتباط پذیرفته نشد",
    "ConnectionResetError": "ارتباط قطع شد",
    "OSError": "خطای سیستم‌عامل",
    "UnicodeDecodeError": "متن فایل خوانده نشد",
    "JSONDecodeError": "پاسخ خوانا نبود",
    "ValueError": "مقدار نادرست",
    "KeyError": "مقدار لازم پیدا نشد",
    "RuntimeError": "خطای اجرا",
    "MemoryError": "حافظه کافی نیست",
}
_EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception|Expired))\b(?::\s*[^\n؛]*)?")
#: allowed Latin inside Persian text: names, paths, addresses, codes
_TECH_HINTS = ("Traceback", "Exception", "Errno", "WinError", "errno", "Input should",
               "field required", "value is not", "object has no attribute", "NoneType")
_PERSIAN = re.compile(r"[؀-ۿ]")


def humanize(text: object, *, log_original: bool = True) -> str:
    """The message as it may be shown: Persian, no exception names or English
    sentences. Latin names inside Persian (hesab5, NT SERVICE\\ShopServer, a path)
    stay."""
    raw = str(text or "").strip()
    if not raw:
        return GENERIC
    if "Input should" in raw or "field required" in raw:
        match = re.search(r"([A-Za-z_][A-Za-z0-9_.]*):\s*Input should be (less|greater) than"
                          r"(?: or equal to)? ([0-9.]+)", raw)
        if match:
            field, side, limit = match.groups()
            kind = "less_than_equal" if side == "less" else "greater_than_equal"
            key = "le" if side == "less" else "ge"
            return validation_text({"loc": field.split("."), "type": kind, "ctx": {key: limit}}) + "."
    if not _PERSIAN.search(raw):
        if log_original:
            log.warning("non-Persian message replaced: %s", raw[:300])
        return GENERIC
    cleaned = _EXCEPTION_RE.sub(lambda m: EXCEPTIONS_FA.get(m.group(1), "خطای فنی"), raw)
    if any(hint in cleaned for hint in _TECH_HINTS):
        if log_original:
            log.warning("technical message shortened: %s", raw[:300])
        persian = cleaned.split(":", 1)[0] if _PERSIAN.search(cleaned.split(":", 1)[0]) else ""
        return (persian.strip() + " (جزئیات در گزارش برنامه)") if persian else GENERIC
    return cleaned
