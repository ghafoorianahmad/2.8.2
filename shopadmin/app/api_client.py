"""HTTP client for shopapi.

This is the ONLY way this desktop app talks to the shop's data. It never opens a
SQL Server connection and never touches shopapi's SQLite file.

Every failure is turned into an :class:`ApiError` carrying a Persian message so
the UI can show it verbatim, with no English text and no stack traces.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .logging_setup import get_logger
from .persian import to_persian_digits

log = get_logger("api")

DEFAULT_TIMEOUT = 15.0
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

MSG_CONNECTION_FAILED = "ارتباط با سرور فروشگاه برقرار نشد. آدرس سرور و اجرای سرویس را بررسی کنید."
MSG_TIMEOUT = "پاسخی از سرور فروشگاه دریافت نشد (زمان انتظار به پایان رسید)."
MSG_INVALID_KEY = "کلید API نامعتبر است. مقدار ADMIN_API_KEY را در تنظیمات بررسی کنید."
MSG_FORBIDDEN = "کلید API فعلی دسترسی مدیریتی ندارد. کلید مدیر (ADMIN_API_KEY) لازم است."
MSG_NOT_FOUND = "موردی با این شناسه در سرور فروشگاه یافت نشد."
MSG_SERVER_ERROR = "خطای داخلی سرور فروشگاه رخ داد. لطفاً بعداً تلاش کنید."
MSG_UNAVAILABLE = "سرور فروشگاه در دسترس نیست یا سرویس حسابداری پاسخ نمی‌دهد."
MSG_BAD_RESPONSE = "پاسخ سرور فروشگاه قابل خواندن نبود."
MSG_UNEXPECTED = "خطای پیش‌بینی‌نشده در ارتباط با سرور فروشگاه رخ داد."

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
    (re.compile(r"missing x-api-key header", re.I), MSG_INVALID_KEY),
    (re.compile(r"invalid api key", re.I), MSG_INVALID_KEY),
    (re.compile(r"admin key required", re.I), MSG_FORBIDDEN),
)

_STATUS_FA = {
    "awaiting_payment": "در انتظار پرداخت",
    "receipt_uploaded": "فیش ارسال‌شده",
    "approved": "تأییدشده",
    "rejected": "ردشده",
    "written": "نوشته‌شده در حسابداری",
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
    def __init__(self, message: str = MSG_INVALID_KEY, *, status_code: int = 401, raw: str = "") -> None:
        super().__init__(message, status_code=status_code, kind="auth", raw=raw)


def translate_detail(detail: Any, status_code: int | None = None) -> str:
    """Turn shopapi's ``{"detail": ...}`` into a Persian sentence.

    ``detail`` may be a string (HTTPException) or a list of pydantic validation
    errors (422). Unknown English text is never shown to the user as-is.
    """
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
    if re.search(r"[\u0600-\u06FF]", text):
        return to_persian_digits(text)

    if status_code == 404:
        return MSG_NOT_FOUND
    return "خطای سرور فروشگاه: " + to_persian_digits(text)


@dataclass
class SystemInfo:
    """Operational flags reported by ``GET /admin/system-info``."""

    accounting_write_enabled: bool = False
    write_allowed_on_host: bool = False
    price_level_bot: int = 3
    price_level_site: int = 3
    reserve_hours: int = 12
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
    """Thin, typed wrapper over the shopapi admin REST surface."""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.Client | None = None

    # ---- lifecycle -------------------------------------------------------
    def configure(self, base_url: str, api_key: str) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.close()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

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
            self._client = httpx.Client(**kwargs)
        return self._client

    # ---- request core ----------------------------------------------------
    def _headers(self, with_key: bool = True) -> dict[str, str]:
        return {API_KEY_HEADER: self.api_key} if with_key and self.api_key else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        with_key: bool = True,
    ) -> Any:
        if not self.base_url:
            raise ApiConnectionError("آدرس سرور فروشگاه تنظیم نشده است. به صفحهٔ تنظیمات بروید.")
        # Drop empty params so shopapi applies its own defaults.
        clean_params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:
            response = self._http().request(
                method,
                path,
                params=clean_params or None,
                json=json_body,
                headers=self._headers(with_key),
            )
        except httpx.TimeoutException as exc:
            log.warning("shopapi timeout: %s %s", method, path)
            raise ApiError(MSG_TIMEOUT, kind="timeout", raw=str(exc)) from exc
        except httpx.HTTPError as exc:
            log.warning("shopapi connection error: %s %s (%s)", method, path, type(exc).__name__)
            raise ApiConnectionError(raw=str(exc)) from exc

        return self._handle(response, method, path)

    def _handle(self, response: httpx.Response, method: str, path: str) -> Any:
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
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail", payload)
        except ValueError:
            detail = response.text[:300]

        message = translate_detail(detail, status_code)
        if status_code in (401,):
            raise ApiAuthError(message, status_code=status_code, raw=str(detail)[:200])
        if status_code == 403:
            raise ApiAuthError(message or MSG_FORBIDDEN, status_code=status_code, raw=str(detail)[:200])
        if status_code == 422:
            log.info("shopapi validation error on %s %s", method, path)
        elif status_code == 503:
            message = message or MSG_UNAVAILABLE
        log.warning("shopapi error %s on %s %s", status_code, method, path)
        raise ApiError(message, status_code=status_code, kind="http", raw=str(detail)[:300])

    # ---- endpoints -------------------------------------------------------
    def health(self) -> dict:
        """``GET /health`` — needs no API key."""
        return self._request("GET", "/health", with_key=False) or {}

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
        """``GET /admin/users`` — CUSTOMERS, not internal admin users."""
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

    def approve_customer(self, user_id: int, person_code: int) -> dict:
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/approve", json_body={"person_code": int(person_code)}
        )

    def reject_customer(self, user_id: int, reason: str = "") -> dict:
        return self._request(
            "POST", f"/admin/users/{int(user_id)}/reject", json_body={"reason": reason or None}
        )

    def list_orders(self, status: str | None = None) -> list[dict]:
        """``GET /admin/orders``.

        shopapi defaults ``status`` to ``receipt_uploaded``, so an explicit
        value is always sent when the caller asks for one.
        """
        payload = self._request("GET", "/admin/orders", params={"status": status})
        return list(payload or [])

    def approve_payment(self, order_id: int) -> dict:
        return self._request("POST", f"/admin/orders/{int(order_id)}/approve-payment")

    def reject_payment(self, order_id: int, reason: str = "") -> dict:
        return self._request(
            "POST", f"/admin/orders/{int(order_id)}/reject-payment", json_body={"reason": reason or None}
        )

    def expire_orders(self) -> dict:
        return self._request("POST", "/admin/orders/expire") or {}

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

    def test_connection(self) -> SystemInfo:
        """Health check + system info; raises :class:`ApiError` on failure."""
        self.health()
        return self.system_info()
