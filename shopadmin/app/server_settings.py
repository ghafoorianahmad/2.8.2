"""Persian labels for the server settings a super admin may change remotely.

The list itself is decided by the server (``/admin/server/settings``); this
module only names and explains each key, and translates the server's
validation messages. A key the server sends but this table does not know is
shown with its raw name rather than hidden.
"""
from __future__ import annotations

import re

from .persian import to_persian_digits

#: key -> (label, help text, kind) ; kind: text | int | bool | secret
SETTINGS_FA: dict[str, tuple[str, str, str]] = {
    "BANK_ACCOUNT_TEXT": ("متن حساب بانکی", "پس از ثبت سفارش برای مشتری فرستاده می‌شود.", "text"),
    "RESERVE_HOURS": ("مهلت پرداخت (ساعت)", "کالای سفارش تا این مدت برای مشتری رزرو می‌ماند.", "int"),
    "MAX_ORDER_QTY": ("حداکثر تعداد هر قلم", "", "int"),
    "PRICE_LEVEL_BOT": ("سطح قیمت ربات‌ها (۱ تا ۵)", "۱ = قیمت اصلی (Gey).", "int"),
    "PRICE_LEVEL_SITE": ("سطح قیمت سایت (۱ تا ۵)", "", "int"),
    "STOCK_WAREHOUSES": ("انبارهای موجودی", "کد انبارها با کاما؛ خالی = همهٔ انبارها.", "text"),
    "ALLOW_SHARED_PERSON_CODE": ("اجازهٔ کد شخص مشترک", "دو مشتری به یک شخص حسابداری وصل شوند.", "bool"),
    "PENDING_MAX_ORDER_ITEMS": ("سقف تعداد کالای مشتری تأییدنشده", "۰ = مشتری تأییدنشده نمی‌تواند سفارش دهد.", "int"),
    "INVOICE_SYNC_SECONDS": ("بررسی فاکتور شدن سفارش‌ها (ثانیه)", "۰ = خاموش.", "int"),
    "ADMIN_CHAT_IDS": ("گفت‌وگوهای مدیران در ربات", "مثلاً bale:654321 — اعلان و تأیید داخل ربات بله.", "text"),
    "ADMIN_SWEEP_SECONDS": ("بررسی موارد جدید در ربات (ثانیه)", "", "int"),
    "STAFF_SESSION_HOURS": ("مدت ورود کارکنان (ساعت)", "", "int"),
    "STAFF_REMEMBER_DAYS": ("مدت «مرا به خاطر بسپار» (روز)", "", "int"),
    "LOGIN_MAX_ATTEMPTS": ("تعداد تلاش ناموفق تا قفل", "", "int"),
    "LOGIN_LOCK_MINUTES": ("مدت قفل حساب (دقیقه)", "", "int"),
    "BALE_TOKEN": ("توکن ربات بله", "فقط برای تغییر وارد کنید؛ مقدار فعلی هرگز نمایش داده نمی‌شود.", "secret"),
}

_PROBLEMS = (
    (re.compile(r"must be a whole number between (\d+) and (\d+)"), "باید عددی بین {0} تا {1} باشد"),
    (re.compile(r"must be true or false"), "باید «بله» یا «خیر» باشد"),
    (re.compile(r"must be at most (\d+) characters"), "حداکثر {0} نویسه"),
    (re.compile(r"must be a single line"), "باید یک خط باشد"),
    (re.compile(r"cannot be changed remotely"), "از راه دور قابل تغییر نیست"),
    (re.compile(r"does not look like a bot token"), "شبیه توکن ربات نیست"),
    (re.compile(r"use entries like"), "به شکل bale:123456 و با کاما جدا کنید"),
    (re.compile(r"use warehouse codes"), "کد انبارها را با کاما جدا کنید"),
)


def label(key: str) -> str:
    return SETTINGS_FA.get(key, (key, "", "text"))[0]


def translate_problem(problem: str) -> str:
    for pattern, template in _PROBLEMS:
        match = pattern.search(str(problem))
        if match:
            return to_persian_digits(template.format(*match.groups()))
    return "مقدار نامعتبر است"


def translate_field_errors(fields: dict) -> str:
    parts = [f"«{label(key)}»: {translate_problem(problem)}" for key, problem in fields.items()]
    return "تنظیمات ذخیره نشد. " + "؛ ".join(parts)
