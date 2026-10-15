"""HTTP client for the shopapi REST API.

Customer calls use BOT_API_KEY, admin calls use ADMIN_API_KEY. Every failure is
turned into a Persian message; the raw shopapi `detail` is kept on the exception
for admins but never logged.
"""
from __future__ import annotations

from typing import Any

import httpx

from . import texts
from .config import Settings


class ShopApiError(Exception):
    def __init__(self, message_fa: str, status: int | None = None, detail: str | None = None):
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.status = status
        self.detail = detail


class ShopApiUnavailable(ShopApiError):
    """shopapi is down, timed out or answered with something unparsable."""


class ShopApiRejected(ShopApiError):
    """shopapi answered with an error status."""


_STATUS_MESSAGES = {
    401: "کلید دسترسی ربات نامعتبر است.",
    403: "دسترسی برای این عملیات مجاز نیست.",
    404: "موردی با این مشخصات پیدا نشد.",
    409: "امکان انجام این عملیات در وضعیت فعلی وجود ندارد.",
    422: "اطلاعات ارسالی نامعتبر است.",
}


def format_admin_error(exc: ShopApiError) -> str:
    """Plain-Persian explanation of a shopapi failure for an admin."""
    if isinstance(exc, ShopApiUnavailable):
        return texts.SERVICE_UNAVAILABLE
    detail = (exc.detail or "").lower()
    if "stock" in detail:
        return texts.ADMIN_INSUFFICIENT_STOCK
    if "person_code" in detail and "not found" in detail:
        return texts.ADMIN_PERSON_CODE_NOT_FOUND
    if "already linked" in detail:
        return texts.ADMIN_PERSON_CODE_IN_USE
    if "not approved yet" in detail:
        return texts.ADMIN_CUSTOMER_NOT_APPROVED
    if "status code is not configured" in detail:
        return texts.ADMIN_STATUS_NOT_CONFIGURED
    if "duplicate accounting order number" in detail:
        return texts.ADMIN_DUPLICATE_ORDER_NO
    return texts.ADMIN_ACTION_FAILED.format(reason=exc.detail or exc.message_fa)


class ShopApiClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._client = client
        self._base = settings.shopapi_base_url.rstrip("/")

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            verify: object = True
            if self._settings.shopapi_ca_file:
                import ssl

                # Trust exactly the server's own self-signed certificate.
                verify = ssl.create_default_context(cafile=self._settings.shopapi_ca_file)
            # trust_env=False: shopapi is local - never route it through a proxy
            # (HTTP(S)_PROXY variables of the Windows account are ignored).
            self._client = httpx.AsyncClient(
                timeout=self._settings.http_timeout, verify=verify, trust_env=False
            )
        return self._client

    @staticmethod
    def _detail_of(response: httpx.Response) -> str | None:
        try:
            body = response.json()
        except ValueError:
            return None
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            return body["detail"]
        return None

    def _message_for(self, status: int, detail: str | None) -> str:
        if status == 409 and detail and "stock" in detail.lower():
            return texts.ADMIN_INSUFFICIENT_STOCK
        if status == 422 and detail and "awaiting approval" in detail.lower():
            return texts.PENDING_LIMIT
        if status == 409 and detail and "sales are closed" in detail.lower():
            return texts.SALES_CLOSED
        if status == 409 and detail and "deadline" in detail.lower():
            return texts.RECEIPT_TOO_LATE
        if status == 503:
            return texts.SERVICE_UNAVAILABLE
        return _STATUS_MESSAGES.get(status, "خطای نامشخص از سامانهٔ فروش.")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        key: str,
        params: dict | None = None,
        json_body: Any = None,
        allow_404: bool = True,
        extra_headers: dict | None = None,
    ):
        client = await self._http()
        headers = {"X-API-Key": key} if key else {}
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = await client.request(
                method, f"{self._base}{path}", params=params, json=json_body, headers=headers
            )
        except httpx.HTTPError:
            raise ShopApiUnavailable(texts.SERVICE_UNAVAILABLE) from None
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code >= 400:
            detail = self._detail_of(response)
            raise ShopApiRejected(
                self._message_for(response.status_code, detail),
                status=response.status_code,
                detail=detail,
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise ShopApiUnavailable(texts.SERVICE_UNAVAILABLE) from None

    # ---- customer side (BOT_API_KEY) -------------------------------------
    async def health(self) -> dict | None:
        return await self._request(
            "GET", "/health", key="", allow_404=False
        )

    async def get_groups(self) -> list[dict]:
        return await self._request("GET", "/groups", key=self._settings.bot_api_key) or []

    async def get_products(
        self,
        *,
        q: str | None = None,
        group: int | None = None,
        in_stock: bool = True,
        page: int = 1,
        page_size: int = 5,
    ) -> dict:
        params: dict[str, Any] = {
            "in_stock": in_stock,
            "page": int(page),
            "page_size": int(page_size),
        }
        if q:
            params["q"] = q
        if group is not None:
            params["group"] = int(group)
        result = await self._request(
            "GET", "/products", key=self._settings.bot_api_key, params=params
        )
        if not isinstance(result, dict):
            return {"total": 0, "page": page, "page_size": page_size, "items": []}
        result.setdefault("items", [])
        return result

    async def get_product(self, code: int) -> dict | None:
        return await self._request("GET", f"/products/{int(code)}", key=self._settings.bot_api_key)

    async def resolve_model(self, text: str) -> dict | None:
        """A site model reference -> found / ambiguous / unavailable / unknown (§9a)."""
        return await self._request(
            "GET", "/catalog/resolve", key=self._settings.bot_api_key,
            params={"text": str(text)[:400]},
        )

    async def shop_state(self) -> dict:
        result = await self._request("GET", "/shop/state", key=self._settings.bot_api_key)
        return result if isinstance(result, dict) else {"closed": False}

    async def get_statement(
        self, platform: str, chat_id: str | int, page: int = 1, page_size: int = 10
    ) -> dict | None:
        return await self._request(
            "GET",
            f"/users/{platform}/{chat_id}/statement",
            key=self._settings.bot_api_key,
            params={"page": int(page), "page_size": int(page_size)},
        )

    async def get_user(self, platform: str, chat_id: str | int) -> dict | None:
        return await self._request(
            "GET", f"/users/{platform}/{chat_id}", key=self._settings.bot_api_key
        )

    async def register_user(
        self, platform: str, chat_id: str | int, name: str, phone: str
    ) -> dict | None:
        return await self._request(
            "POST",
            "/users/register",
            key=self._settings.bot_api_key,
            json_body={
                "platform": platform,
                "chat_id": str(chat_id),
                "name": name,
                "phone": phone,
            },
        )

    async def create_order(
        self, platform: str, chat_id: str | int, items: list[dict],
        idempotency_key: str | None = None,
    ) -> dict | None:
        return await self._request(
            "POST",
            "/orders",
            key=self._settings.bot_api_key,
            json_body={"platform": platform, "chat_id": str(chat_id), "items": items},
            extra_headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
        )

    async def upload_receipt(
        self, order_id: int, receipt_ref: str, platform: str, chat_id: str | int,
        data_b64: str | None = None,
    ) -> dict | None:
        body: dict[str, Any] = {"receipt_ref": receipt_ref}
        if data_b64:
            body["data_b64"] = data_b64
        return await self._request(
            "POST",
            f"/orders/{int(order_id)}/receipt",
            key=self._settings.bot_api_key,
            params={"platform": platform, "chat_id": str(chat_id)},
            json_body=body,
        )

    async def get_order(
        self, order_id: int, platform: str | None = None, chat_id: str | int | None = None
    ) -> dict | None:
        params: dict[str, Any] = {}
        if platform:
            params["platform"] = platform
        if chat_id is not None:
            params["chat_id"] = str(chat_id)
        return await self._request(
            "GET",
            f"/orders/{int(order_id)}",
            key=self._settings.bot_api_key,
            params=params or None,
        )

    async def list_user_orders(self, platform: str, chat_id: str | int) -> list[dict]:
        return (
            await self._request(
                "GET",
                f"/users/{platform}/{chat_id}/orders",
                key=self._settings.bot_api_key,
            )
            or []
        )

    # ---- admin side (ADMIN_API_KEY) --------------------------------------
    async def admin_list_users(self, status_filter: str = "pending") -> list[dict]:
        return (
            await self._request(
                "GET",
                "/admin/users",
                key=self._settings.admin_api_key,
                params={"status": status_filter},
            )
            or []
        )

    async def admin_get_user(self, user_id: int) -> dict | None:
        return await self._request(
            "GET", f"/admin/users/{int(user_id)}", key=self._settings.admin_api_key
        )

    async def create_inquiry(
        self, platform: str, chat_id: str | int, kala_code: int, variant_id: int | None
    ) -> dict | None:
        """Inquiry for a phone color without a price (REQUIREMENTS §4)."""
        body: dict[str, Any] = {
            "platform": platform, "chat_id": str(chat_id), "kala_code": int(kala_code),
        }
        if variant_id:
            body["variant_id"] = int(variant_id)
        return await self._request(
            "POST", "/inquiries", key=self._settings.bot_api_key, json_body=body
        )

    async def report_security(self, kind: str, platform: str, chat_id: str | int) -> bool:
        """Tell shopapi about a suspicious act (REQUIREMENTS §10). Best effort:
        a failure is swallowed, the customer's flow never depends on it."""
        body = {"kind": kind, "platform": platform, "chat_id": str(chat_id)}
        try:
            await self._request(
                "POST", "/security/report", key=self._settings.bot_api_key, json_body=body
            )
        except ShopApiError:
            return False
        return True

    async def get_statement_full(self, platform: str, chat_id: str | int) -> dict | None:
        """The whole statement for the PDF (v2.6.0)."""
        return await self._request(
            "GET", f"/users/{platform}/{chat_id}/statement/full", key=self._settings.bot_api_key,
        )

    async def item_request_search(self, q: str) -> list[dict]:
        """Names of products matching ``q`` («درخواست کالای ناموجود», v2.6.0)."""
        result = await self._request(
            "GET", "/item-requests/search", key=self._settings.bot_api_key,
            params={"q": str(q)[:100]},
        )
        return [r for r in (result or []) if isinstance(r, dict)]

    async def create_item_request(
        self, platform: str, chat_id: str | int, *, kala_code: int | None = None, text: str = "",
        kind: str = "unavailable",
    ) -> dict | None:
        """``kind="inquiry"``: «استعلام قیمت» of a price-on-inquiry product (v2.6.1)."""
        body: dict[str, Any] = {"platform": platform, "chat_id": str(chat_id),
                                "text": str(text or "")[:300], "kind": kind}
        if kala_code:
            body["kala_code"] = int(kala_code)
        return await self._request(
            "POST", "/item-requests", key=self._settings.bot_api_key, json_body=body
        )

    async def admin_get_item_request(self, request_id: int) -> dict | None:
        return await self._request(
            "GET", f"/admin/item-requests/{int(request_id)}", key=self._settings.admin_api_key
        )

    async def admin_get_item_request_message(self, message_id: int) -> dict | None:
        """A staff reply to an item request and where to deliver it (v2.6.1)."""
        return await self._request(
            "GET", f"/admin/item-request-messages/{int(message_id)}",
            key=self._settings.admin_api_key,
        )

    async def admin_item_request_message_result(
        self, message_id: int, ok: bool, error: str = ""
    ) -> dict | None:
        return await self._request(
            "POST", f"/admin/item-request-messages/{int(message_id)}/result",
            key=self._settings.admin_api_key,
            json_body={"ok": bool(ok), "error": str(error or "")[:300]},
        )

    async def admin_get_inquiry(self, inquiry_id: int) -> dict | None:
        return await self._request(
            "GET", f"/admin/inquiries/{int(inquiry_id)}", key=self._settings.admin_api_key
        )

    async def admin_get_order(self, order_id: int) -> dict | None:
        return await self._request(
            "GET", f"/orders/{int(order_id)}", key=self._settings.admin_api_key
        )

    async def admin_approve_user(self, user_id: int, person_code: int) -> dict | None:
        return await self._request(
            "POST",
            f"/admin/users/{int(user_id)}/approve",
            key=self._settings.admin_api_key,
            json_body={"person_code": int(person_code)},
        )

    async def admin_reject_user(self, user_id: int, reason: str | None = None) -> dict | None:
        body = {"reason": reason} if reason else None
        return await self._request(
            "POST",
            f"/admin/users/{int(user_id)}/reject",
            key=self._settings.admin_api_key,
            json_body=body,
        )

    async def admin_list_orders(self, status_filter: str = "receipt_uploaded") -> list[dict]:
        return (
            await self._request(
                "GET",
                "/admin/orders",
                key=self._settings.admin_api_key,
                params={"status": status_filter},
            )
            or []
        )

    async def admin_approve_payment(self, order_id: int) -> dict | None:
        return await self._request(
            "POST",
            f"/admin/orders/{int(order_id)}/approve-payment",
            key=self._settings.admin_api_key,
        )

    async def admin_reject_payment(self, order_id: int, reason: str | None = None) -> dict | None:
        body = {"reason": reason} if reason else None
        return await self._request(
            "POST",
            f"/admin/orders/{int(order_id)}/reject-payment",
            key=self._settings.admin_api_key,
            json_body=body,
        )

    async def admin_events(self, after: int | None = None, limit: int = 200) -> dict:
        """Staff notification feed: {"last_id": int, "items": [{kind, ref_id}, ...]}."""
        params: dict[str, Any] = {"limit": int(limit)}
        if after is not None:
            params["after"] = int(after)
        result = await self._request(
            "GET", "/admin/events", key=self._settings.admin_api_key, params=params
        )
        return result if isinstance(result, dict) else {"last_id": after or 0, "items": []}

    async def admin_match_person(self, mobile: str) -> dict | None:
        return await self._request(
            "GET",
            "/admin/persons/match",
            key=self._settings.admin_api_key,
            params={"mobile": mobile},
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
