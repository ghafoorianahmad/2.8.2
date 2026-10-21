"""HTTP client for shopapi.

This is the ONLY way this desktop app talks to the shop's data. It never opens a
SQL Server connection and never touches shopapi's SQLite file.

Staff sign in with a username and password; the server returns a session token
that is sent as ``Authorization: Bearer``. No shared API key lives on a client:
roles and permissions are enforced by the server.

Every failure is turned into an :class:`ApiError` carrying a Persian message so
the UI can show it verbatim, with no English text and no stack traces.
"""
from __future__ import annotations

import base64
import hashlib
import re
import ssl
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx

from .logging_setup import get_logger
from .persian import to_persian_digits

log = get_logger("api")

DEFAULT_TIMEOUT = 15.0
#: Used only for the one-time server bootstrap, on the server machine itself.
API_KEY_HEADER = "X-API-Key"

# --- order statuses accepted by GET /admin/orders -------------------------
ORDER_STATUSES = (
    "awaiting_payment",
    "receipt_uploaded",
    "approved",
    "rejected",
    "expired",
    "written",
    "cancelled",
)
CUSTOMER_STATUSES = ("pending", "approved", "rejected")

MSG_CONNECTION_FAILED = ("برنامه به رایانهٔ اصلی فروشگاه وصل نشد. اتصال شبکه را بررسی کنید و چند لحظه بعد «به‌روزرسانی» را بزنید؛ اگر درست نشد به مدیر خبر دهید.")
MSG_TIMEOUT = "پاسخی نرسید. چند لحظه صبر کنید و دوباره امتحان کنید؛ اگر تکرار شد به مدیر خبر دهید."
MSG_INVALID_KEY = "کلید سرویس نامعتبر است."
MSG_FORBIDDEN = ("شما اجازهٔ این کار را ندارید. اگر لازم است، از مدیر بخواهید این دسترسی را در «کاربران سیستم» برایتان فعال کند.")
MSG_SESSION_EXPIRED = "نشست شما به پایان رسیده است. لطفاً دوباره وارد شوید."
MSG_BAD_CREDENTIALS = "نام کاربری یا گذرواژه نادرست است."
MSG_LOCKED = "حساب کاربری به دلیل تلاش‌های ناموفق موقتاً قفل شده است. کمی بعد دوباره تلاش کنید."
MSG_DISABLED = "این حساب کاربری غیرفعال شده است. با مدیر فروشگاه تماس بگیرید."
MSG_TOO_MANY = "تعداد تلاش‌های ورود از این رایانه بیش از حد مجاز است. چند دقیقه بعد دوباره تلاش کنید."
MSG_MUST_CHANGE = "ابتدا باید گذرواژهٔ خود را تغییر دهید."
MSG_NOT_FOUND = "این مورد پیدا نشد؛ شاید حذف یا عوض شده است. «به‌روزرسانی» را بزنید."
MSG_SERVER_ERROR = "کار انجام نشد. چند لحظه بعد دوباره امتحان کنید؛ اگر تکرار شد به مدیر خبر دهید."
MSG_UNAVAILABLE = ("برنامهٔ حسابداری یا رایانهٔ اصلی فروشگاه فعلاً پاسخ نمی‌دهد. چند دقیقه بعد دوباره امتحان کنید؛ اگر درست نشد به مدیر خبر دهید.")
MSG_BAD_RESPONSE = "پاسخ سرور فروشگاه قابل خواندن نبود."
MSG_UNEXPECTED = "خطای پیش‌بینی‌نشده در ارتباط با سرور فروشگاه رخ داد."
MSG_TLS_MISMATCH = (
    "گواهی امنیتی سرور با گواهی ثبت‌شده در این رایانه یکی نیست. ممکن است کسی در "
    "شبکه خود را جای سرور جا زده باشد. تا بررسی مدیر، وارد نشوید."
)
MSG_TLS_NOT_PINNED = "گواهی امنیتی سرور هنوز روی این رایانه ثبت نشده است. تنظیمات اولیه را دوباره انجام دهید."


def fingerprint_of_pem(pem: str) -> str:
    """SHA-256 of the DER certificate as 'AB:CD:…' — same format the server shows."""
    der = ssl.PEM_cert_to_DER_cert(pem)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def short_fingerprint(fingerprint: str) -> str:
    """The first 8 bytes, grouped for reading aloud: 'AB12 CD34 EF56 7890'."""
    hexes = fingerprint.replace(":", "")[:16]
    return " ".join(hexes[i:i + 4] for i in range(0, 16, 4))


def fetch_server_certificate(base_url: str, timeout: float = 8.0) -> tuple[str, str]:
    """Download the certificate an HTTPS server presents (trust on first use).

    Returns (pem, fingerprint). The caller must show the fingerprint to the
    owner, who compares it with the one displayed on the server, before it is
    stored and trusted.
    """
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        raise ApiError("آدرس سرور باید با https:// شروع شود.", kind="tls")
    try:
        pem = ssl.get_server_certificate((parts.hostname, parts.port or 443), timeout=timeout)
    except (OSError, ssl.SSLError) as exc:
        raise ApiConnectionError(raw=str(exc)) from exc
    return pem, fingerprint_of_pem(pem)


def pinned_context(pem: str) -> ssl.SSLContext:
    """Trust exactly this certificate and nothing else.

    The host name is not checked: the pin is stronger than a name (the server's
    LAN address may change, its certificate does not).
    """
    context = ssl.create_default_context(cadata=pem)
    context.check_hostname = False
    return context

# shopapi's English ``detail`` strings -> Persian shown to the operator.
_DETAIL_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"insufficient stock for product (\d+)", re.I),
     "موجودی کافی نیست (کد کالا: {0})."),
    (re.compile(r"person_code (\d+) not found", re.I),
     "کد شخص {0} در حسابداری یافت نشد."),
    (re.compile(r"person_code (\d+) is already linked to another user", re.I),
     "کد شخص {0} قبلاً به مشتری دیگری متصل شده است."),
    (re.compile(r"order in status (\w+); cannot approve", re.I),
     "این سفارش در وضعیت «{0}» است و قابل تأیید نیست."),
    (re.compile(r"order in status (\w+); cannot reject", re.I),
     "این سفارش در وضعیت «{0}» است و قابل رد کردن نیست."),
    (re.compile(r"order in status (\w+); receipt not expected", re.I),
     "این سفارش در وضعیت «{0}» است و فیش برای آن پذیرفته نمی‌شود."),
    (re.compile(r"user is not approved", re.I), "این مشتری هنوز تأیید نشده است."),
    (re.compile(r"customer is not approved yet", re.I),
     "مشتری این سفارش هنوز تأیید نشده است؛ اول مشتری را تأیید کنید."),
    (re.compile(r"accounting writes are disabled; the person was not created", re.I),
     "ثبت در حسابداری خاموش است (حالت آزمایشی)؛ شخص ساخته نشد. "
     "می‌توانید مشتری را به یک کد شخص موجود وصل کنید."),
    (re.compile(r"last_name is required", re.I), "برای ساخت شخص، نام خانوادگی لازم است."),
    (re.compile(r"mobile belongs to several persons", re.I),
     "این شماره در حسابداری به چند شخص تعلق دارد؛ کد شخص درست را دستی وارد کنید."),
    (re.compile(r"accounting is busy", re.I), "حسابداری مشغول است؛ چند لحظه بعد دوباره تلاش کنید."),
    (re.compile(r"order in status (\w+); cannot ship", re.I),
     "این سفارش در وضعیت «{0}» است و هنوز قابل ارسال نیست."),
    (re.compile(r"no receipt image", re.I), "برای این سفارش تصویر رسیدی ذخیره نشده است."),
    (re.compile(r"order exceeds the limit for customers awaiting approval", re.I),
     "سفارش از سقف مجاز مشتری تأییدنشده بیشتر است."),
    (re.compile(r"user not found", re.I), "مشتری یافت نشد."),
    (re.compile(r"order not found", re.I), "سفارش یافت نشد."),
    (re.compile(r"product (\d+) is not available for sale", re.I),
     "کالای {0} قابل فروش نیست."),
    (re.compile(r"quantity for product (\d+) exceeds the maximum", re.I),
     "مقدار سفارش کالای {0} از حد مجاز بیشتر است."),
    (re.compile(r"no matching person", re.I), "شخصی با این شمارهٔ موبایل در حسابداری پیدا نشد."),
    (re.compile(r"accounting database unavailable", re.I),
     "سرویس حسابداری در دسترس نیست. اتصال سرور فروشگاه به حسابداری را بررسی کنید."),
    (re.compile(r"own database unavailable", re.I), "پایگاه‌دادهٔ سرور فروشگاه در دسترس نیست."),
    # ---- v2.5.0: order flow and accounting guards ----
    (re.compile(r"sales are closed", re.I),
     "فروش گوشی در حال حاضر بسته است (لیست قیمت به‌روز نشده، ساعت پایان فروش، جمعه یا "
     "تعطیلی). لوازم جانبی و سایر کالاها قابل سفارش‌اند."),
    (re.compile(r"receipt deadline passed", re.I),
     "مهلت ارسال رسید این سفارش گذشته و سفارش لغو شده است."),
    (re.compile(r"order status code is not configured", re.I),
     "کد وضعیت سفارش حسابداری (ACCOUNTING_STATUS_CODE) روی سرور تنظیم نشده است؛ "
     "سفارش در حسابداری ثبت نشد. پس از آزمایش G2 مقدار درست را در تنظیمات سرور وارد کنید."),
    # ---- v2.7.0: shipping and cancel ----
    (re.compile(r"invalid courier phone", re.I),
     "شمارهٔ تلفن پیک درست نیست. فقط رقم بنویسید، مثلاً ۰۹۱۲۳۴۵۶۷۸۹؛ یا آن را خالی بگذارید."),
    (re.compile(r"cannot be cancelled", re.I),
     "این سفارش دیگر قابل لغو نیست (پرداختش تأیید یا ثبت شده است). اگر لازم است به مدیر خبر دهید."),
    (re.compile(r"cannot ship", re.I),
     "فقط سفارشی که پرداختش تأیید شده «ارسال شد» می‌شود. اول رسید را تأیید کنید."),
    # ---- v2.6.1: item requests ----
    (re.compile(r"customer has no messenger", re.I),
     "این مشتری پیام‌رسانی ندارد؛ پیام قابل ارسال نیست."),
    (re.compile(r"only staff can message customers", re.I),
     "فقط کاربران برنامهٔ مدیریت می‌توانند به مشتری پیام بدهند."),
    (re.compile(r"message is empty", re.I), "متن پیام خالی است."),
    (re.compile(r"request not found", re.I), "این درخواست پیدا نشد."),
    (re.compile(r"duplicate accounting order number", re.I),
     "شمارهٔ سفارش در حسابداری تکراری بود؛ چیزی ثبت نشد. چند لحظه بعد دوباره تأیید کنید."),
    # ---- v2.8.0: ownership, archive, purchase requests ----
    (re.compile(r"another colleague is working on this", re.I),
     "همکار دیگری زودتر روی این مورد کار کرد و آن را برداشت؛ کار شما انجام نشد. "
     "این مورد از فهرست شما برداشته می‌شود."),
    # ---- v2.8.2: payment details per order ----
    (re.compile(r"card_number must be a 16-digit", re.I), "شمارهٔ کارت باید ۱۶ رقم باشد."),
    (re.compile(r"sheba must be a sheba", re.I), "شبا باید IR و ۲۴ رقم باشد."),
    (re.compile(r"account_number must be digits", re.I), "شمارهٔ حساب فقط رقم است."),
    (re.compile(r"enter a card, account or sheba number", re.I),
     "دست‌کم یکی از شمارهٔ کارت، شمارهٔ حساب یا شبا را وارد کنید."),
    (re.compile(r"payment details not needed", re.I),
     "این سفارش دیگر منتظر پرداخت نیست؛ اطلاعات پرداخت فرستاده نشد."),
    (re.compile(r"order is finished and read-only", re.I),
     "این سفارش تمام شده و دیگر در این برنامه تغییر نمی‌کند (تغییرات فقط در «سازه حساب»)."),
    (re.compile(r"request is finished and read-only", re.I),
     "این درخواست بسته شده و دیگر تغییر نمی‌کند."),
    (re.compile(r"not permitted to reassign", re.I),
     "شما اجازهٔ ارجاع این مورد را ندارید. فقط مدیر، صاحب کار یا کسی با دسترسی "
     "«ارجاع سفارش» می‌تواند ارجاع دهد."),
    (re.compile(r"unknown colleague", re.I), "همکار انتخاب‌شده پیدا نشد یا غیرفعال است."),
    (re.compile(r"managers only", re.I), "این بخش فقط برای «مدیر» است."),
    (re.compile(r"choose the product", re.I),
     "این ردیف لیست قیمت هنوز به کالایی در «سازه حساب» وصل نیست؛ کالا را انتخاب کنید."),
    (re.compile(r"enter the price", re.I), "قیمت را وارد کنید."),
    (re.compile(r"not a purchase request", re.I), "این درخواست، درخواست خرید نیست."),
    (re.compile(r"answer the purchase request", re.I),
     "درخواست خرید را با «تأیید موجودی» یا «ناموجود» ببندید تا به مشتری خبر داده شود."),
    (re.compile(r"customer cannot order", re.I), "این مشتری ردشده است و نمی‌تواند سفارش بدهد."),
    (re.compile(r"payment details are not configured", re.I),
     "شمارهٔ کارت پرداخت روی سرور تنظیم نشده؛ سفارش ساخته نشد."),
    (re.compile(r"product not found in accounting", re.I),
     "این کالا در «سازه حساب» پیدا نشد یا غیرفعال است."),
    (re.compile(r"row not found in the current list", re.I),
     "این ردیف در لیست قیمت فعلی نیست."),
    # ---- sign-in and staff accounts ----
    (re.compile(r"invalid username or password", re.I), MSG_BAD_CREDENTIALS),
    (re.compile(r"account temporarily locked", re.I), MSG_LOCKED),
    (re.compile(r"account disabled", re.I), MSG_DISABLED),
    (re.compile(r"too many login attempts", re.I), MSG_TOO_MANY),
    (re.compile(r"session expired or invalid|sign-in required|missing x-api-key", re.I),
     MSG_SESSION_EXPIRED),
    (re.compile(r"password change required", re.I), MSG_MUST_CHANGE),
    (re.compile(r"not permitted for this account|admin key required", re.I), MSG_FORBIDDEN),
    (re.compile(r"api key not accepted from this address", re.I),
     "کلید سرویس فقط روی خود رایانهٔ سرور قابل استفاده است."),
    (re.compile(r"invalid api key", re.I), MSG_INVALID_KEY),
    (re.compile(r"username already exists", re.I), "این نام کاربری قبلاً استفاده شده است."),
    (re.compile(r"username must be", re.I),
     "نام کاربری باید ۳ تا ۳۲ نویسهٔ انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد."),
    (re.compile(r"password must be at least (\d+)", re.I), "گذرواژه باید حداقل {0} نویسه باشد."),
    (re.compile(r"password must contain letters and digits", re.I),
     "گذرواژه باید هم حرف و هم عدد داشته باشد."),
    (re.compile(r"password is too long", re.I), "گذرواژه بیش از حد طولانی است."),
    (re.compile(r"current password is wrong", re.I), "گذرواژهٔ فعلی نادرست است."),
    (re.compile(r"new password must differ", re.I),
     "گذرواژهٔ جدید باید با گذرواژهٔ فعلی متفاوت باشد."),
    (re.compile(r"cannot remove the last super admin", re.I),
     "حداقل یک «مدیر» فعال باید باقی بماند."),
    (re.compile(r"cannot delete your own account", re.I),
     "نمی‌توانید حساب کاربری خودتان را حذف کنید."),
    (re.compile(r"staff account not found", re.I), "کاربر مورد نظر یافت نشد."),
    (re.compile(r"staff accounts already exist", re.I),
     "حساب «مدیر» قبلاً ساخته شده است. با همان حساب وارد شوید."),
    # ---- server control ----
    (re.compile(r"restart not available", re.I),
     "سرور در حالت سرویس اجرا نمی‌شود و از راه دور راه‌اندازی دوباره نمی‌شود."),
    (re.compile(r"settings file not available", re.I),
     "فایل تنظیمات سرور در دسترس نیست (سرور در حالت سرویس اجرا نمی‌شود)."),
    (re.compile(r"log file not available", re.I), "فایل گزارش سرور در دسترس نیست."),
    (re.compile(r"nothing to change", re.I), "تغییری برای ذخیره وجود ندارد."),
)

_STATUS_FA = {
    "awaiting_payment": "در انتظار پرداخت",
    "receipt_uploaded": "رسید رسیده",
    "approved": "تأییدشده",
    "rejected": "ردشده",
    "written": "ثبت‌شده در حسابداری",
    "cancelled": "لغو‌شده",
    "expired": "منقضی",
    "pending": "در انتظار تأیید",
    "ok": "سالم",
}


def _fa_status(token: str) -> str:
    return _STATUS_FA.get(str(token or "").strip().lower(), str(token))


class ApiError(Exception):
    """Any failure while talking to shopapi, with a Persian message."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 kind: str = "error", raw: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.kind = kind
        self.raw = raw


class ApiConnectionError(ApiError):
    def __init__(self, message: str = MSG_CONNECTION_FAILED, *, raw: str = "") -> None:
        super().__init__(message, status_code=None, kind="connection", raw=raw)


class ApiAuthError(ApiError):
    def __init__(self, message: str = MSG_SESSION_EXPIRED, *, status_code: int = 401,
                 raw: str = "") -> None:
        super().__init__(message, status_code=status_code, kind="auth", raw=raw)


def translate_detail(detail: Any, status_code: int | None = None) -> str:
    """Turn shopapi's ``{"detail": ...}`` into a Persian sentence.

    ``detail`` may be a string (HTTPException) or a list of pydantic validation
    errors (422). Unknown English text is never shown to the user as-is.
    """
    if isinstance(detail, dict) and isinstance(detail.get("fields"), dict):
        from .server_settings import translate_field_errors

        return translate_field_errors(detail["fields"])

    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                location = ".".join(str(p) for p in item.get("loc", ()) if p != "body")
                message = str(item.get("msg", "")).strip()
                if location:
                    parts.append(f"{location}: {message}")
                elif message:
                    parts.append(message)
        if parts:
            return "اطلاعات ارسال‌شده نامعتبر است: " + "؛ ".join(parts)
        return "اطلاعات ارسال‌شده نامعتبر است."

    text = str(detail or "").strip()
    if not text:
        if status_code == 404:
            return MSG_NOT_FOUND
        if status_code == 503:
            return MSG_UNAVAILABLE
        return MSG_SERVER_ERROR

    for pattern, template in _DETAIL_MAP:
        match = pattern.search(text)
        if match:
            groups = tuple(_fa_status(g) for g in match.groups())
            try:
                # Persian digits: codes and quantities must never show as ASCII.
                return to_persian_digits(template.format(*groups))
            except (IndexError, KeyError):
                return to_persian_digits(template)

    # Persian text coming from the server (already localized) is kept.
    if re.search(r"[؀-ۿ]", text):
        return to_persian_digits(text)

    if status_code == 404:
        return MSG_NOT_FOUND
    return "خطای سرور فروشگاه: " + to_persian_digits(text)


@dataclass
class SystemInfo:
    """Operational flags reported by ``GET /admin/system-info``."""

    accounting_write_enabled: bool = False
    write_allowed_on_host: bool = False
    #: Connected to a listed test database: everything is enabled.
    test_mode: bool = False
    price_level_bot: int = 3
    price_level_site: int = 3
    #: v2.5.0: the customer sends the receipt within this many minutes, then
    #: the order is cancelled on the server (no 12-hour hold any more).
    receipt_deadline_minutes: int = 30
    #: The accounting database orders are written to.
    accounting_database: str = ""
    #: ACCOUNTING_STATUS_CODE is set (orders can be committed).
    status_code_configured: bool = True
    max_order_qty: int = 10000
    allow_shared_person_code: bool = False
    bank_account_text: Optional[str] = None
    reachable: bool = True
    #: False when the server does not implement the endpoint (older build).
    supported: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def write_mode_known(self) -> bool:
        """True when the server actually told us whether writes are enabled."""
        return self.reachable and self.supported

    @classmethod
    def from_payload(cls, payload: dict) -> "SystemInfo":
        known = {f for f in cls.__dataclass_fields__
                 if f not in {"reachable", "supported", "extra"}}
        data = {k: v for k, v in (payload or {}).items() if k in known}
        extra = {k: v for k, v in (payload or {}).items() if k not in known}
        return cls(**data, reachable=True, supported=True, extra=extra)

    @classmethod
    def unavailable(cls, *, supported: bool = True) -> "SystemInfo":
        return cls(reachable=False, supported=supported)


class ShopApiClient:
    """Thin, typed wrapper over the shopapi REST surface for staff clients."""

    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        server_cert_pem: str = "",
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()
        self.server_cert_pem = str(server_cert_pem or "")
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.Client | None = None
        #: Called (possibly from a worker thread) when the server rejects our
        #: session, so the UI can send the user back to the login window.
        self.on_session_invalid: Optional[Callable[[], None]] = None

    # ---- lifecycle -------------------------------------------------------
    def configure(self, base_url: str, token: str | None = None) -> None:
        """Point at a server; ``token=None`` keeps the current session token."""
        self.base_url = str(base_url or "").strip().rstrip("/")
        if token is not None:
            self.token = str(token or "").strip()
        self.close()

    def set_token(self, token: str) -> None:
        self.token = str(token or "").strip()

    def set_server_cert(self, pem: str) -> None:
        self.server_cert_pem = str(pem or "")
        self.close()

    @property
    def uses_tls(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    @property
    def has_session(self) -> bool:
        return bool(self.token)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # pragma: no cover - defensive
                pass
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "base_url": self.base_url or "http://127.0.0.1:8000",
                "timeout": self.timeout,
                "headers": {"Accept": "application/json"},
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            elif self.uses_tls:
                if not self.server_cert_pem:
                    raise ApiError(MSG_TLS_NOT_PINNED, kind="tls")
                kwargs["verify"] = pinned_context(self.server_cert_pem)
            self._client = httpx.Client(**kwargs)
        return self._client

    # ---- request core ----------------------------------------------------
    def _headers(self, with_auth: bool = True) -> dict[str, str]:
        if with_auth and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        with_auth: bool = True,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not self.base_url:
            raise ApiConnectionError("آدرس سرور فروشگاه تنظیم نشده است. به صفحهٔ تنظیمات بروید.")
        # Drop empty params so shopapi applies its own defaults.
        clean_params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        all_headers = self._headers(with_auth)
        all_headers.update(headers or {})
        try:
            response = self._http().request(
                method,
                path,
                params=clean_params or None,
                json=json_body,
                headers=all_headers,
            )
        except httpx.TimeoutException as exc:
            log.warning("shopapi timeout: %s %s", method, path)
            raise ApiError(MSG_TIMEOUT, kind="timeout", raw=str(exc)) from exc
        except httpx.ConnectError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                log.error("TLS: the server certificate does not match the pinned one")
                raise ApiError(MSG_TLS_MISMATCH, kind="tls", raw="certificate mismatch") from exc
            log.warning("shopapi connection error: %s %s (ConnectError)", method, path)
            raise ApiConnectionError(raw=str(exc)) from exc
        except httpx.HTTPError as exc:
            log.warning("shopapi connection error: %s %s (%s)", method, path, type(exc).__name__)
            raise ApiConnectionError(raw=str(exc)) from exc

        return self._handle(response, method, path, with_auth=with_auth)

    def _handle(self, response: httpx.Response, method: str, path: str,
                *, with_auth: bool = True) -> Any:
        status_code = response.status_code
        if 200 <= status_code < 300:
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise ApiError(MSG_BAD_RESPONSE, status_code=status_code, kind="decode",
                               raw=response.text[:200]) from exc

        detail: Any = None
        server_fa = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail", payload)
                # v2.5.0: SQL errors come with a Persian explanation (18456, 4060, ...)
                server_fa = str(payload.get("message_fa") or "").strip()
        except ValueError:
            detail = response.text[:300]

        message = translate_detail(detail, status_code)
        if server_fa:
            message = to_persian_digits(server_fa)
        if status_code == 401:
            if with_auth and self.token:
                # The server no longer accepts our session (expired, revoked,
                # role changed, password reset…). Forget it and tell the UI.
                self.token = ""
                callback = self.on_session_invalid
                if callback is not None:
                    try:
                        callback()
                    except Exception:  # noqa: BLE001 - never break the caller
                        log.exception("session-invalid callback failed")
            raise ApiAuthError(message, status_code=status_code, raw=str(detail)[:200])
        if status_code == 403:
            raise ApiAuthError(message or MSG_FORBIDDEN, status_code=status_code,
                               raw=str(detail)[:200])
        if status_code == 422:
            log.info("shopapi validation error on %s %s", method, path)
        elif status_code == 503:
            message = message or MSG_UNAVAILABLE
        log.warning("shopapi error %s on %s %s", status_code, method, path)
        raise ApiError(message, status_code=status_code, kind="http", raw=str(detail)[:300])

    # ---- endpoints -------------------------------------------------------
    def health(self) -> dict:
        """``GET /health`` — needs no sign-in."""
        return self._request("GET", "/health", with_auth=False) or {}

    def system_info(self) -> SystemInfo:
        """``GET /admin/system-info`` — read-only operational flags.

        Older shopapi builds do not expose this endpoint. That is not an error
        for the operator: the app simply cannot tell whether accounting writes
        are enabled, so it reports the flag as unknown instead of failing the
        whole connection check. ``SystemInfo.supported`` records which happened.
        """
        try:
            payload = self._request("GET", "/admin/system-info")
        except ApiError as exc:
            if exc.status_code == 404:
                log.info("this shopapi build has no /admin/system-info endpoint; "
                         "the dry-run banner cannot be shown")
                return SystemInfo.unavailable(supported=False)
            raise
        if not isinstance(payload, dict):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return SystemInfo.from_payload(payload)

    def list_customers(self, status: str | None = None) -> list[dict]:
        """``GET /admin/users`` — CUSTOMERS, not staff accounts."""
        payload = self._request("GET", "/admin/users", params={"status": status})
        return list(payload or [])

    def match_person(self, mobile: str) -> Optional[dict]:
        """``GET /admin/persons/match`` — suggested accounting person by mobile."""
        try:
            payload = self._request("GET", "/admin/persons/match", params={"mobile": mobile})
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def approve_customer(self, user_id: int, person_code: Optional[int],
                         *, first_name: str = "", last_name: str = "") -> dict:
        """Link to an existing person, or (``person_code=None``) create one in
        the accounting software with the given, staff-corrected name."""
        if person_code is not None:
            body: dict[str, Any] = {"person_code": int(person_code)}
        else:
            body = {"first_name": first_name or None, "last_name": last_name}
        return self._request("POST", f"/admin/users/{int(user_id)}/approve", json_body=body)

    def reject_customer(self, user_id: int, reason: str = "") -> dict:
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/reject", json_body={"reason": reason or None}
        )

    def list_orders(self, status: str | None = None, *, mine: bool = False) -> list[dict]:
        """``GET /admin/orders``.

        shopapi defaults ``status`` to ``receipt_uploaded``, so an explicit
        value is always sent when the caller asks for one. v2.8.0: ``mine`` =
        only the orders this user owns («کارهای من»).
        """
        params = {"status": status}
        if mine:
            params["mine"] = "true"
        payload = self._request("GET", "/admin/orders", params=params)
        return list(payload or [])

    # ---- v2.8.0: ownership, handover, timeline, activity, archive -----------------
    def get_order(self, order_id: int) -> dict:
        return self._request("GET", f"/admin/orders/{int(order_id)}") or {}

    def order_timeline(self, order_id: int) -> list[dict]:
        return list(self._request("GET", f"/admin/orders/{int(order_id)}/timeline") or [])

    def send_payment_info(self, order_id: int, info: dict) -> dict:
        """v2.8.2: «ارسال اطلاعات پرداخت»: card / account / Sheba / holder / bank /
        note (empty ones left out) go to the customer through the bot."""
        fields = ("card_number", "account_number", "sheba", "holder", "bank", "note")
        body = {key: str(info.get(key) or "").strip() for key in fields}
        return self._request("POST", f"/admin/orders/{int(order_id)}/payment-info",
                             json_body=body) or {}

    def assign_order(self, order_id: int, staff_id: int) -> dict:
        return self._request("POST", f"/admin/orders/{int(order_id)}/assign",
                             json_body={"staff_id": int(staff_id)}) or {}

    def list_assignees(self) -> list[dict]:
        return list(self._request("GET", "/admin/assignees") or [])

    def payment_info_due(self) -> list[dict]:
        """v2.8.3: orders still waiting for «ارسال اطلاعات پرداخت» that this user
        must be reminded of (their own, or nobody's yet)."""
        return list(self._request("GET", "/admin/orders/payment-info-due") or [])

    def transfer_open_work(self, from_staff_id: int, to_staff_id: int) -> dict:
        """v2.8.3 (manager): every open order / request of one user to another."""
        return self._request("POST", f"/admin/staff/{int(from_staff_id)}/transfer-open",
                             json_body={"staff_id": int(to_staff_id)}) or {}

    def activity(self, *, staff_id: int | None = None, customer_id: int | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 limit: int = 1000) -> list[dict]:
        params = {"staff_id": staff_id, "customer_id": customer_id, "date_from": date_from,
                  "date_to": date_to, "limit": limit}
        return list(self._request("GET", "/admin/activity", params=params) or [])

    def archived_orders(self, q: str = "", accounting_db: str = "") -> list[dict]:
        params = {"q": q or None, "accounting_db": accounting_db or None}
        return list(self._request("GET", "/admin/archive/orders", params=params) or [])

    def archived_item_requests(self, q: str = "", accounting_db: str = "") -> list[dict]:
        params = {"q": q or None, "accounting_db": accounting_db or None}
        return list(self._request("GET", "/admin/archive/item-requests", params=params) or [])

    def run_archive(self) -> dict:
        return self._request("POST", "/admin/archive/run") or {}

    def approve_payment(self, order_id: int) -> dict:
        return self._request("POST", f"/admin/orders/{int(order_id)}/approve-payment")

    def reject_payment(self, order_id: int, reason: str = "") -> dict:
        return self._request(
            "POST", f"/admin/orders/{int(order_id)}/reject-payment", json_body={"reason": reason or None}
        )

    def expire_orders(self) -> dict:
        return self._request("POST", "/admin/orders/expire") or {}

    def ship_order(self, order_id: int, courier_name: str = "", courier_phone: str = "") -> dict:
        """«ارسال شد»; v2.7.0: with an optional courier name and phone for the customer."""
        return self._request("POST", f"/admin/orders/{int(order_id)}/ship", json_body={
            "courier_name": str(courier_name or "").strip()[:60],
            "courier_phone": str(courier_phone or "").strip()[:30]})

    def cancel_order(self, order_id: int) -> dict:
        """v2.7.0: cancel an order that is not confirmed yet (local only)."""
        return self._request("POST", f"/admin/orders/{int(order_id)}/cancel") or {}

    def receipt_image(self, order_id: int) -> Optional[bytes]:
        """``GET /admin/orders/{id}/receipt`` — the stored receipt image, or None."""
        if not self.base_url:
            raise ApiConnectionError("آدرس سرور فروشگاه تنظیم نشده است. به صفحهٔ تنظیمات بروید.")
        path = f"/admin/orders/{int(order_id)}/receipt"
        try:
            response = self._http().get(path, headers=self._headers())
        except httpx.HTTPError as exc:
            log.warning("shopapi connection error: GET %s (%s)", path, type(exc).__name__)
            raise ApiConnectionError(raw=str(exc)) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            self._handle(response, "GET", path)
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return response.content

    def shop_state(self) -> dict:
        return self._request("GET", "/admin/shop/state") or {"closed": False}

    def set_shop_closed(self, closed: bool) -> dict:
        return self._request("PUT", "/admin/shop/state", json_body={"closed": bool(closed)}) or {}

    def sales_action(self, action: str) -> dict:
        """«تعطیلی امروز» (holiday) / «بستن فروش» (close) / «باز کردن فروش» (open).
        Stored and audited on the server; returns the new sales state."""
        if action not in ("holiday", "close", "open"):
            raise ValueError(action)
        return self._request("POST", "/admin/sales/action", json_body={"action": action}) or {}

    def list_groups(self) -> list[dict]:
        payload = self._request("GET", "/groups")
        return list(payload or [])

    def list_products(
        self,
        *,
        query: str | None = None,
        group: int | None = None,
        in_stock: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        payload = self._request(
            "GET",
            "/products",
            params={
                "q": query,
                "group": group,
                "in_stock": "true" if in_stock else "false",
                "page": page,
                "page_size": page_size,
            },
        )
        if not isinstance(payload, dict):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return payload

    # ---- distributor price list / mapping / proxies (Phase 3) -----------------
    def list_pricelists(self, limit: int = 50) -> list[dict]:
        return list(self._request("GET", "/admin/pricelists", params={"limit": limit}) or [])

    def upload_pricelist(self, data: bytes, file_name: str = "") -> dict:
        """Manual upload of a distributor PDF (also the fallback when Telegram is down)."""
        body = {"data_b64": base64.b64encode(data).decode("ascii"),
                "source_ref": (file_name or "")[:200]}
        return self._request("POST", "/admin/pricelists", json_body=body) or {}

    def approve_pricelist(self, list_id: int) -> dict:
        return self._request("POST", f"/admin/pricelists/{int(list_id)}/approve") or {}

    def reject_pricelist(self, list_id: int, reason: str = "") -> dict:
        return self._request(
            "POST", f"/admin/pricelists/{int(list_id)}/reject", json_body={"reason": reason}
        ) or {}

    def pricelist_rows(self, *, filter_key: str = "all", section: str | None = None) -> dict:
        payload = self._request(
            "GET", "/admin/pricelists/rows", params={"filter": filter_key, "section": section}
        )
        if not isinstance(payload, dict):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return payload

    def map_price_row(self, row_key: str, kala_code: int, color_label: str = "") -> dict:
        return self._request("PUT", "/admin/price-mappings", json_body={
            "row_key": row_key, "action": "map", "kala_code": int(kala_code),
            "color_label": color_label,
        }) or {}

    def ignore_price_rows(self, row_keys: list[str]) -> dict:
        return self._request(
            "POST", "/admin/price-mappings/ignore", json_body={"row_keys": list(row_keys)}
        ) or {}

    def delete_price_mapping(self, mapping_id: int) -> None:
        self._request("DELETE", f"/admin/price-mappings/{int(mapping_id)}")

    def confirm_price_mapping(self, mapping_id: int) -> dict:
        """v2.6.2: accept an automatic mapping (it becomes an ordinary one)."""
        return self._request("POST", f"/admin/price-mappings/{int(mapping_id)}/confirm") or {}

    def mapping_suggestions(self, row_key: str) -> dict:
        """v2.8.0: the 3 products whose names best match a price-list row."""
        payload = self._request("GET", "/admin/price-mappings/suggestions",
                                params={"row_key": row_key})
        return payload if isinstance(payload, dict) else {"items": []}

    def auto_match_prices(self) -> dict:
        """v2.6.2: match the newest list against every earlier decision now."""
        return self._request("POST", "/admin/price-mappings/auto") or {}

    # ---- site catalog models (Phase 6b, REQUIREMENTS §9a) -----------------------
    def _dict(self, payload) -> dict:
        if not isinstance(payload, dict):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return payload

    def list_catalog_models(self) -> dict:
        return self._dict(self._request("GET", "/admin/catalog-models"))

    def import_catalog_models(self, models: list[dict]) -> dict:
        return self._dict(self._request("POST", "/admin/catalog-models/import",
                                        json_body={"models": list(models)}))

    def check_catalog_models(self) -> dict:
        return self._dict(self._request("POST", "/admin/catalog-models/check"))

    def catalog_model(self, model_id: int) -> dict:
        return self._dict(self._request("GET", f"/admin/catalog-models/{int(model_id)}"))

    def update_catalog_model(self, model_id: int, **fields) -> dict:
        return self._dict(self._request("PATCH", f"/admin/catalog-models/{int(model_id)}",
                                        json_body=fields))

    def catalog_suggestions(self, model_id: int, query: str = "", limit: int = 15) -> list[dict]:
        params = {"limit": limit, "q": query.strip() or None}
        return list(self._request("GET", f"/admin/catalog-models/{int(model_id)}/suggestions",
                                  params=params) or [])

    def add_catalog_item(self, model_id: int, kala_code: int, label: str = "") -> dict:
        return self._dict(self._request(
            "POST", f"/admin/catalog-models/{int(model_id)}/items",
            json_body={"kala_code": int(kala_code), "label": label}))

    def update_catalog_item(self, item_id: int, *, kala_code: int | None = None,
                            label: str | None = None) -> dict:
        body = {k: v for k, v in (("kala_code", kala_code), ("label", label)) if v is not None}
        return self._dict(self._request("PATCH", f"/admin/catalog-models/items/{int(item_id)}",
                                        json_body=body))

    def accept_catalog_item(self, item_id: int) -> dict:
        return self._dict(self._request("POST",
                                        f"/admin/catalog-models/items/{int(item_id)}/accept"))

    def delete_catalog_item(self, item_id: int) -> dict:
        return self._dict(self._request("DELETE", f"/admin/catalog-models/items/{int(item_id)}"))

    def confirm_catalog_model(self, model_id: int) -> dict:
        return self._dict(self._request("POST",
                                        f"/admin/catalog-models/{int(model_id)}/confirm"))

    # ---- v2.6.0: product groups and unavailable item requests ----
    def product_groups(self) -> list[dict]:
        """Accounting groups with «show in bot» / «phone group»."""
        return list(self._request("GET", "/admin/product-groups") or [])

    def save_product_groups(self, groups: list[dict]) -> list[dict]:
        body = {"groups": [{"code": int(g["code"]), "show_in_bot": bool(g.get("show_in_bot")),
                            "is_phone": bool(g.get("is_phone")),
                            "price_on_inquiry": bool(g.get("price_on_inquiry"))}
                           for g in groups]}
        return list(self._request("PUT", "/admin/product-groups", json_body=body) or [])

    def list_item_requests(self, status: str | None = None,
                           kind: str | None = None, *, mine: bool = False) -> list[dict]:
        params = {"status": status, "kind": kind}
        if mine:
            params["mine"] = "true"
        return list(self._request("GET", "/admin/item-requests", params=params) or [])

    def item_request_timeline(self, request_id: int) -> list[dict]:
        return list(self._request("GET", f"/admin/item-requests/{int(request_id)}/timeline")
                    or [])

    def assign_item_request(self, request_id: int, staff_id: int) -> dict:
        return self._request("POST", f"/admin/item-requests/{int(request_id)}/assign",
                             json_body={"staff_id": int(staff_id)}) or {}

    def confirm_purchase_stock(self, request_id: int, kala_code: int | None = None,
                               price_rial: int | None = None) -> dict:
        """«تأیید موجودی»: a normal order awaiting the customer's payment."""
        body = {"kala_code": int(kala_code) if kala_code else None,
                "price_rial": int(price_rial) if price_rial else None}
        return self._request("POST", f"/admin/item-requests/{int(request_id)}/confirm-stock",
                             json_body=body) or {}

    def mark_purchase_unavailable(self, request_id: int) -> dict:
        return self._request("POST", f"/admin/item-requests/{int(request_id)}/unavailable") or {}

    def get_item_request(self, request_id: int) -> dict:
        return self._request("GET", f"/admin/item-requests/{int(request_id)}") or {}

    def set_item_request_note(self, request_id: int, note: str) -> dict:
        return self._request("PUT", f"/admin/item-requests/{int(request_id)}/note",
                             json_body={"note": str(note or "")[:1000]}) or {}

    def item_request_messages(self, request_id: int) -> list[dict]:
        """v2.6.1: the staff replies sent to the customer (with delivery state)."""
        return list(self._request("GET", f"/admin/item-requests/{int(request_id)}/messages")
                    or [])

    def send_item_request_message(self, request_id: int, text: str) -> dict:
        """Queue a reply; the bot of the customer's messenger delivers it."""
        return self._request("POST", f"/admin/item-requests/{int(request_id)}/messages",
                             json_body={"text": str(text)}) or {}

    def set_item_request_status(self, request_id: int, status: str) -> dict:
        if status not in ("new", "seen", "done"):
            raise ValueError(status)
        return self._request("POST", f"/admin/item-requests/{int(request_id)}/status",
                             json_body={"status": status}) or {}

    def list_inquiries(self, limit: int = 100) -> list[dict]:
        return list(self._request("GET", "/admin/inquiries", params={"limit": limit}) or [])

    def list_proxies(self) -> list[dict]:
        return list(self._request("GET", "/admin/proxies") or [])

    def add_proxy(self, link: str, main: bool = False) -> dict:
        return self._request("POST", "/admin/proxies",
                             json_body={"link": link.strip(), "main": bool(main)}) or {}

    def set_proxy_state(self, proxy_id: int, state: str) -> dict:
        return self._request("POST", f"/admin/proxies/{int(proxy_id)}/state",
                             json_body={"state": state}) or {}

    def delete_proxy(self, proxy_id: int) -> None:
        self._request("DELETE", f"/admin/proxies/{int(proxy_id)}")

    def test_connection(self) -> SystemInfo:
        """Health check + system info (needs a signed-in session)."""
        self.health()
        return self.system_info()

    def probe_server(self) -> dict:
        """Before sign-in: is the server up, and does it still need a first admin?"""
        self.health()
        return self.auth_status()

    # ---- staff sign-in ---------------------------------------------------
    def auth_status(self) -> dict:
        """``GET /auth/status`` — public; tells whether the first admin is missing."""
        return self._request("GET", "/auth/status", with_auth=False) or {}

    def login(self, username: str, password: str, *, remember: bool = False,
              client_name: str = "") -> dict:
        """``POST /auth/login``; on success the token is kept for later calls."""
        payload = self._request(
            "POST", "/auth/login", with_auth=False,
            json_body={"username": username, "password": password,
                       "remember": bool(remember), "client": str(client_name or "")[:100]},
        )
        if not isinstance(payload, dict) or not payload.get("token"):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        self.token = str(payload["token"])
        return payload

    def logout(self) -> None:
        """Best effort: the local token is dropped even if the server is away."""
        if not self.token:
            return
        try:
            self._request("POST", "/auth/logout")
        except ApiError:
            pass
        finally:
            self.token = ""

    def me(self) -> dict:
        return self._request("GET", "/auth/me") or {}

    def change_password(self, current_password: str, new_password: str) -> None:
        self._request("POST", "/auth/change-password", json_body={
            "current_password": current_password, "new_password": new_password})

    # ---- forgot password (public until approved) ---------------------------
    def forgot_password(self, username: str) -> dict:
        return self._request("POST", "/auth/forgot", with_auth=False,
                             json_body={"username": username}) or {}

    def forgot_status(self, request_id: int, token: str) -> str:
        payload = self._request("POST", "/auth/forgot/status", with_auth=False, json_body={
            "request_id": int(request_id), "token": token}) or {}
        return str(payload.get("status") or "pending")

    def forgot_complete(self, request_id: int, token: str, new_password: str) -> None:
        self._request("POST", "/auth/forgot/complete", with_auth=False, json_body={
            "request_id": int(request_id), "token": token, "new_password": new_password})

    def list_password_requests(self) -> list[dict]:
        return list(self._request("GET", "/admin/password-requests") or [])

    def decide_password_request(self, request_id: int, approve: bool) -> None:
        action = "approve" if approve else "reject"
        self._request("POST", f"/admin/password-requests/{int(request_id)}/{action}")

    def reset_staff_default(self, staff_id: int) -> dict:
        return self._request("POST", f"/admin/staff/{int(staff_id)}/reset-default") or {}

    # ---- server edition: no sign-in screen ---------------------------------
    def console_login(self, service_key: str) -> dict:
        """Session for the server edition (loopback + the server's own service key)."""
        payload = self._request(
            "POST", "/auth/console-login", with_auth=False,
            headers={API_KEY_HEADER: str(service_key or "").strip()},
        )
        if not isinstance(payload, dict) or not payload.get("token"):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        self.token = str(payload["token"])
        return payload

    def bootstrap(self, service_key: str, username: str, full_name: str, password: str) -> dict:
        """Create the first super admin. Works only on the server machine itself."""
        return self._request(
            "POST", "/auth/bootstrap", with_auth=False,
            headers={API_KEY_HEADER: str(service_key or "").strip()},
            json_body={"username": username, "full_name": full_name, "password": password},
        )

    # ---- staff management (super admin) ------------------------------------
    def list_staff(self) -> list[dict]:
        return list(self._request("GET", "/admin/staff") or [])

    def create_staff(self, username: str, full_name: str, role: str, password: str,
                     *, must_change_password: bool = True,
                     extra_permissions: list[str] | None = None,
                     removed_permissions: list[str] | None = None) -> dict:
        body = {"username": username, "full_name": full_name, "role": role,
                "password": password, "must_change_password": must_change_password}
        if extra_permissions is not None:
            body["extra_permissions"] = sorted(extra_permissions)
        if removed_permissions is not None:
            body["removed_permissions"] = sorted(removed_permissions)
        return self._request("POST", "/admin/staff", json_body=body)

    def update_staff(self, staff_id: int, *, full_name: str | None = None,
                     role: str | None = None, active: bool | None = None,
                     extra_permissions: list[str] | None = None,
                     removed_permissions: list[str] | None = None) -> dict:
        body = {k: v for k, v in {"full_name": full_name, "role": role, "active": active}.items()
                if v is not None}
        if extra_permissions is not None:
            body["extra_permissions"] = sorted(extra_permissions)
        if removed_permissions is not None:
            body["removed_permissions"] = sorted(removed_permissions)
        return self._request("PATCH", f"/admin/staff/{int(staff_id)}", json_body=body)

    def reset_staff_password(self, staff_id: int, password: str,
                             *, must_change_password: bool = True) -> dict:
        return self._request("POST", f"/admin/staff/{int(staff_id)}/password", json_body={
            "password": password, "must_change_password": must_change_password})

    def unlock_staff(self, staff_id: int) -> dict:
        return self._request("POST", f"/admin/staff/{int(staff_id)}/unlock")

    def delete_staff(self, staff_id: int) -> None:
        self._request("DELETE", f"/admin/staff/{int(staff_id)}")

    def audit_log(self, limit: int = 200) -> list[dict]:
        return list(self._request("GET", "/admin/audit", params={"limit": limit}) or [])

    # ---- server control (super admin) ---------------------------------------
    def server_status(self) -> dict:
        return self._request("GET", "/admin/server/status") or {}

    def server_settings(self) -> dict:
        return (self._request("GET", "/admin/server/settings") or {}).get("settings", {})

    def update_server_settings(self, values: dict[str, str]) -> dict:
        return self._request("PUT", "/admin/server/settings", json_body={"values": values}) or {}

    def server_logs(self, lines: int = 200) -> list[str]:
        payload = self._request("GET", "/admin/server/logs", params={"lines": lines}) or {}
        return list(payload.get("lines") or [])

    def restart_server(self) -> None:
        self._request("POST", "/admin/server/restart")

    # ---- notifications -----------------------------------------------------
    def events(self, after: int | None = None, limit: int = 100) -> dict:
        """``GET /admin/events``; ``after=None`` returns only the current position."""
        payload = self._request("GET", "/admin/events", params={"after": after, "limit": limit})
        if not isinstance(payload, dict):
            raise ApiError(MSG_BAD_RESPONSE, kind="decode")
        return payload
