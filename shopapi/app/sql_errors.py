"""Plain-Persian explanations of SQL Server / ODBC errors (decision 2026-10-14).

pyodbc puts the SQLSTATE in ``exc.args[0]`` and the driver text, which carries
the native error number in brackets or parentheses (e.g. ``(18456)``), in
``exc.args[1]``. Only the number is used: the driver text can contain the
server name, the login or SQL and is never shown or logged by callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: native error number -> Persian message for the operator.
NATIVE_MESSAGES: dict[int, str] = {
    18456: "ورود به SQL Server ناموفق بود: نام کاربری یا گذرواژهٔ اتصال حسابداری نادرست است "
           "(یا ورود SQL روی سرور فعال نیست).",
    18452: "ورود به SQL Server ناموفق بود: این سرور فقط ورود ویندوزی را می‌پذیرد.",
    18470: "ورود به SQL Server ناموفق بود: حساب کاربری SQL غیرفعال است.",
    18486: "حساب کاربری SQL به‌خاطر تلاش‌های ناموفق قفل شده است.",
    18488: "گذرواژهٔ حساب کاربری SQL منقضی شده و باید عوض شود.",
    4060: "پایگاه‌دادهٔ حسابداری باز نشد: نام پایگاه‌داده (ACCOUNTING_DATABASE) اشتباه است "
          "یا این کاربر به آن دسترسی ندارد.",
    4064: "پایگاه‌دادهٔ پیش‌فرض کاربر SQL باز نشد.",
    229: "کاربر SQL برای این کار مجوز ندارد (نقش shop_app را بررسی کنید).",
    230: "کاربر SQL برای خواندن یکی از ستون‌ها مجوز ندارد (نقش shop_app را بررسی کنید).",
    208: "جدول یا نمای لازم در پایگاه‌دادهٔ حسابداری پیدا نشد (پایگاه‌دادهٔ اشتباه؟).",
    207: "ستون لازم در پایگاه‌دادهٔ حسابداری پیدا نشد (نسخهٔ نرم‌افزار حسابداری متفاوت است؟).",
    2812: "تابع یا رویهٔ لازم در پایگاه‌دادهٔ حسابداری پیدا نشد.",
    1222: "حسابداری مشغول است (قفل)؛ چند لحظه بعد دوباره تلاش کنید.",
    1205: "تداخل هم‌زمان در حسابداری (deadlock)؛ دوباره تلاش کنید.",
    53: "سرور SQL پیدا نشد یا در دسترس نیست (نام سرور، شبکه یا دیوار آتش).",
    2: "سرور SQL پیدا نشد یا در دسترس نیست (نام سرور یا نمونهٔ SQL اشتباه است).",
    17: "سرور SQL وجود ندارد یا دسترسی رد شد.",
    10060: "اتصال به سرور SQL در زمان مقرر برقرار نشد (شبکه یا دیوار آتش).",
    10061: "سرور SQL اتصال را نپذیرفت (سرویس SQL خاموش است یا پورت بسته است).",
    9002: "فایل لاگ پایگاه‌دادهٔ حسابداری پر است؛ به مسئول SQL خبر دهید.",
    1105: "فضای پایگاه‌دادهٔ حسابداری پر است؛ به مسئول SQL خبر دهید.",
}

#: SQLSTATE -> Persian message (when no native number is recognised).
SQLSTATE_MESSAGES: dict[str, str] = {
    "28000": "ورود به SQL Server ناموفق بود (نام کاربری/گذرواژه یا نوع ورود).",
    "08001": "به سرور SQL وصل نشد (نام سرور، سرویس SQL، شبکه یا دیوار آتش را بررسی کنید).",
    "08S01": "ارتباط با سرور SQL قطع شد.",
    "HYT00": "پاسخ پایگاه‌دادهٔ حسابداری بیش از حد طول کشید.",
    "HYT01": "اتصال به سرور SQL در زمان مقرر برقرار نشد.",
    "IM002": "درایور ODBC SQL Server روی این رایانه نصب نیست (ODBC Driver 17 for SQL Server).",
    "42000": "کاربر SQL برای این کار مجوز ندارد یا پایگاه‌داده در دسترس نیست.",
    "42S02": "جدول لازم در پایگاه‌دادهٔ حسابداری پیدا نشد.",
    "42S22": "ستون لازم در پایگاه‌دادهٔ حسابداری پیدا نشد.",
}

GENERIC_MESSAGE = "پایگاه‌دادهٔ حسابداری در دسترس نیست."

# "(18456)" or "[18456]" or "Error 18456" / "error: 4060"
_NATIVE_RE = re.compile(r"(?:\((\d{1,6})\)|\[(\d{1,6})\]|error[ :]+(\d{1,6}))", re.I)
_SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")


@dataclass(frozen=True)
class SqlErrorInfo:
    #: Native SQL Server error number (None = unknown).
    native: int | None
    sqlstate: str
    message_fa: str

    @property
    def code(self) -> str:
        return str(self.native) if self.native is not None else (self.sqlstate or "")


def _native_numbers(text: str) -> list[int]:
    out = []
    for match in _NATIVE_RE.finditer(text):
        value = next(g for g in match.groups() if g)
        out.append(int(value))
    return out


def describe(exc: BaseException) -> SqlErrorInfo:
    """Persian explanation of a pyodbc (or similar) error. Never raises."""
    args = getattr(exc, "args", ()) or ()
    sqlstate = ""
    if args and isinstance(args[0], str) and _SQLSTATE_RE.match(args[0].strip().upper()):
        sqlstate = args[0].strip().upper()
    text = " ".join(str(a) for a in args)
    for number in _native_numbers(text):
        if number in NATIVE_MESSAGES:
            return SqlErrorInfo(number, sqlstate, NATIVE_MESSAGES[number])
    if sqlstate in SQLSTATE_MESSAGES:
        return SqlErrorInfo(None, sqlstate, SQLSTATE_MESSAGES[sqlstate])
    return SqlErrorInfo(None, sqlstate, GENERIC_MESSAGE)
