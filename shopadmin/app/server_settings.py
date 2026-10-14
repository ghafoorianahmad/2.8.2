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
    "PAYMENT_CARD_NUMBER": ("شمارهٔ کارت پرداخت", "۱۶ رقم؛ پس از ثبت سفارش برای مشتری فرستاده می‌شود. الزامی: بدون کارت معتبر ربات سفارش نهایی را نمی‌پذیرد.", "text"),
    "PAYMENT_SHEBA": ("شمارهٔ شبا", "به شکل IR و ۲۴ رقم؛ خالی = نمایش داده نمی‌شود.", "text"),
    "PAYMENT_OWNER": ("نام صاحب حساب", "روی پیش‌فاکتور تصویری نمایش داده می‌شود.", "text"),
    "ACCOUNTING_STATUS_CODE": ("کد وضعیت سفارش در حسابداری (Status)", "کد وضعیتی که سفارش ثبت‌شده در «سازه حساب» می‌گیرد (KalaOrder.Status)؛ الزامی، عدد صحیح؛ ۶۸۰۸ معتبر نیست. پس از آزمایش در «سازه حساب» تعیین کنید.", "int"),
    "RECEIPT_DEADLINE_MINUTES": ("مهلت ارسال رسید (دقیقه)", "پس از این مدت سفارش بدون رسید خودکار لغو می‌شود (فقط در سرور فروشگاه، نه در حسابداری).", "int"),
    "SALES_WINDOWS_ENABLED": ("فروش گوشی طبق لیست قیمت", "بله = فروش گوشی فقط پس از لیست صبح (تا ۱۳:۳۰) یا عصر (تا ۲۰:۳۰)؛ جمعه بسته. لوازم جانبی همیشه قابل سفارش است.", "bool"),
    "SALES_MORNING_CLOSE": ("پایان فروش گوشی (لیست صبح)", "مثلاً 13:30 (ساعت ایران).", "text"),
    "SALES_EVENING_CLOSE": ("پایان فروش گوشی (لیست عصر)", "مثلاً 20:30 (ساعت ایران).", "text"),
    "MAX_ORDER_QTY": ("حداکثر تعداد هر قلم", "", "int"),
    "PRICE_LEVEL_BOT": ("سطح قیمت ربات‌ها (۱ تا ۵)", "۱ = قیمت اصلی (Gey).", "int"),
    "PRICE_LEVEL_SITE": ("سطح قیمت سایت (۱ تا ۵)", "", "int"),
    "STOCK_WAREHOUSES": ("انبارهای موجودی", "کد انبارها با کاما؛ خالی = همهٔ انبارها.", "text"),
    "ALLOW_SHARED_PERSON_CODE": ("اجازهٔ کد شخص مشترک", "دو مشتری به یک شخص حسابداری وصل شوند.", "bool"),
    "PENDING_MAX_ORDER_ITEMS": ("سقف تعداد کالای مشتری تأییدنشده", "۰ = مشتری تأییدنشده نمی‌تواند سفارش دهد.", "int"),
    "INVOICE_SYNC_SECONDS": ("بررسی فاکتور شدن سفارش‌ها (ثانیه)", "۰ = خاموش.", "int"),
    "HEALTH_CHECK_SECONDS": ("پایش سلامت سرور هر (ثانیه)", "SQL، ربات بله و کارگر تلگرام؛ ۰ = خاموش.", "int"),
    "HEALTH_FAIL_THRESHOLD": ("هشدار پس از چند خطای پیاپی", "هشدار در بله و کنار ساعت ویندوز.", "int"),
    "PRICELIST_MAX_CHANGE_PCT": ("سقف تغییر قیمت لیست پخش (درصد)", "تغییر بیشتر = لیست نگه داشته می‌شود تا تأیید کنید.", "int"),
    "PRICELIST_MAX_AGE_HOURS": ("اعتبار لیست قیمت گوشی (ساعت)", "لیست قدیمی‌تر = فقط استعلام؛ ۰ = بدون محدودیت.", "int"),
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
    (re.compile(r"must be a 16-digit card number"), "شمارهٔ کارت باید ۱۶ رقم باشد"),
    (re.compile(r"must be a sheba"), "شبا باید IR و ۲۴ رقم باشد"),
    (re.compile(r"does not look like a bot token"), "شبیه توکن ربات نیست"),
    (re.compile(r"use entries like"), "به شکل bale:123456 و با کاما جدا کنید"),
    (re.compile(r"use warehouse codes"), "کد انبارها را با کاما جدا کنید"),
    (re.compile(r"must be a time like"), "ساعت را به شکل 13:30 بنویسید"),
    (re.compile(r"ACCOUNTING_STATUS_CODE is required"), "کد وضعیت الزامی است"),
    (re.compile(r"(\d+) is not a valid status code"), "کد وضعیت {0} معتبر نیست"),
)

#: Same rule as the server (shopapi ``control._status_code`` /
#: ``Settings.status_code_problem``): required, a whole number, not a known-invalid code.
INVALID_STATUS_CODES = frozenset({6808})


def local_problem(key: str, value: str) -> str | None:
    """The server's message for a value it would refuse, checked before sending
    (only where the rule is fixed; the server checks everything again)."""
    if key == "ACCOUNTING_STATUS_CODE":
        value = value.strip()
        if value == "":
            return "ACCOUNTING_STATUS_CODE is required"
        if not re.fullmatch(r"\d{1,9}", value):
            return "must be a whole number between 0 and 999999999"
        if int(value) in INVALID_STATUS_CODES:
            return f"{int(value)} is not a valid status code"
    return None


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
