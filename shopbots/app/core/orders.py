"""Orders: checkout from the cart, payment receipts, a customer's order list."""
from __future__ import annotations

import base64
import enum
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..shopapi import ShopApiClient, ShopApiRejected
from ..store import Store
from .cart import CartService

#: Receipt images accepted from a photo or an image document (REQUIREMENTS §7).
RECEIPT_MIME_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})
_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


class ReceiptOutcome(enum.Enum):
    SAVED = "saved"
    NO_ORDER = "no_order"            # no order is waiting for a receipt
    NOT_A_PHOTO = "not_a_photo"      # not a photo / JPEG or PNG document
    TOO_LARGE = "too_large"
    DOWNLOAD_FAILED = "download_failed"
    NOT_AWAITING = "not_awaiting"    # shopapi: the order no longer waits for payment
    TOO_LATE = "too_late"            # shopapi: receipt deadline passed, order cancelled
    REJECTED = "rejected"            # shopapi refused for another reason (message_fa)


@dataclass
class CheckoutResult:
    order: dict | None = None
    empty_cart: bool = False
    #: v2.9.1: (name, old price, new price) of cart lines whose price changed since
    #: they were added; the cart now holds the new prices and NO order was placed
    price_changes: list | None = None


@dataclass
class ReceiptResult:
    outcome: ReceiptOutcome
    order: dict | None = None
    message_fa: str = ""


@dataclass
class ReceiptFile:
    file_ref: str = ""
    size: int | None = None
    outcome: ReceiptOutcome | None = None   # set when the attachment is refused


def receipt_file_ref(photo) -> str | None:
    """The largest size of a Bot-API photo (the last entry), or None."""
    if isinstance(photo, list) and photo:
        last = photo[-1]
        if isinstance(last, dict) and last.get("file_id"):
            return str(last["file_id"])
    return None


def receipt_file(photo, document, max_bytes: int) -> ReceiptFile:
    """Pick the receipt attachment: a photo, or a JPEG/PNG sent as a file."""
    size = None
    ref = receipt_file_ref(photo)
    if ref:
        size = photo[-1].get("file_size")
    elif isinstance(document, dict) and document.get("file_id"):
        mime = str(document.get("mime_type") or "").lower()
        name = str(document.get("file_name") or "").lower()
        if mime not in RECEIPT_MIME_TYPES and not name.endswith((".jpg", ".jpeg", ".png")):
            return ReceiptFile(outcome=ReceiptOutcome.NOT_A_PHOTO)
        ref = str(document["file_id"])
        size = document.get("file_size")
    else:
        return ReceiptFile(outcome=ReceiptOutcome.NOT_A_PHOTO)
    if isinstance(size, int) and size > max_bytes:
        return ReceiptFile(outcome=ReceiptOutcome.TOO_LARGE)
    return ReceiptFile(file_ref=ref, size=size if isinstance(size, int) else None)


def is_image(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _SIGNATURES)


Downloader = Callable[[str, int], Awaitable["bytes | None"]]


class OrderService:
    def __init__(self, api: ShopApiClient, store: Store, cart: CartService,
                 *, receipt_max_bytes: int = 5 * 1024 * 1024):
        self.api = api
        self.store = store
        self.cart = cart
        self.receipt_max_bytes = int(receipt_max_bytes)

    async def checkout(self, platform: str, chat_id: str,
                       ship_address: str | None = None) -> CheckoutResult:
        items = self.cart.items(platform, chat_id)
        if not items:
            return CheckoutResult(empty_cart=True)
        payload = self.cart.order_payload(items)
        changes = await self._price_changes(platform, chat_id, items, payload)
        if changes:
            return CheckoutResult(price_changes=changes)
        key = self._checkout_key(platform, chat_id, payload)
        extra = {"ship_address": ship_address} if ship_address else {}
        order = await self.api.create_order(platform, chat_id, payload, idempotency_key=key,
                                            **extra)
        if order:
            self.cart.clear(platform, chat_id)
            self.store.set_value(f"checkout_key:{platform}:{chat_id}", "")
        return CheckoutResult(order=order or None)

    async def _price_changes(self, platform: str, chat_id: str, items: list[dict],
                             payload: list[dict]) -> list[tuple[str, float, float]]:
        """v2.9.1: open carts are re-checked with today's prices before the order is
        placed (placed orders keep theirs). shopapi prices the order (``?check``);
        any line that changed is updated in the cart and the customer confirms again."""
        try:
            checked = await self.api.check_order(platform, chat_id, payload)
        except ShopApiRejected:
            raise
        except Exception:  # noqa: BLE001 - shopapi down: the real submit reports it
            return []
        lines = (checked or {}).get("items") if isinstance(checked, dict) else None
        if not lines:
            return []
        now = {(int(it.get("kala_code") or 0), int(it.get("variant_id") or 0)):
               float(it.get("unit_price") or 0) for it in lines if isinstance(it, dict)}
        changes = []
        for item in items:
            key = (int(item["kala_code"]), int(item.get("variant_id") or 0))
            new = now.get(key)
            old = float(item.get("unit_price") or 0)
            if new is None or new <= 0 or abs(new - old) < 0.5:
                continue
            self.store.cart_set_price(platform, chat_id, key[0], new, key[1])
            changes.append((str(item.get("name") or key[0]), old, new))
        return changes

    def _checkout_key(self, platform: str, chat_id: str, payload: list[dict]) -> str:
        """One key per checkout attempt: a retry of the same cart (timeout, double tap)
        reuses it so shopapi returns the first order; a changed cart gets a new key."""
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]
        slot = f"checkout_key:{platform}:{chat_id}"
        saved = self.store.get_value(slot) or ""
        if saved.startswith(digest + ":"):
            return saved.split(":", 1)[1]
        key = uuid.uuid4().hex
        self.store.set_value(slot, f"{digest}:{key}")
        return key

    async def attach_receipt(
        self, platform: str, chat_id: str, order_id, photo, document=None,
        download: Downloader | None = None,
    ) -> ReceiptResult:
        """Download the image (size-capped), check it is JPEG/PNG and hand it
        to shopapi, which stores it for review in ShopAdmin."""
        if not order_id:
            return ReceiptResult(ReceiptOutcome.NO_ORDER)
        picked = receipt_file(photo, document, self.receipt_max_bytes)
        if picked.outcome is not None:
            return ReceiptResult(picked.outcome)
        data_b64 = None
        if download is not None:
            try:
                data = await download(picked.file_ref, self.receipt_max_bytes)
            except Exception as exc:
                # the adapter refuses an oversized file before/while downloading it
                if getattr(exc, "description", "") == "too large":
                    return ReceiptResult(ReceiptOutcome.TOO_LARGE)
                data = None
            if data is None:
                return ReceiptResult(ReceiptOutcome.DOWNLOAD_FAILED)
            if len(data) > self.receipt_max_bytes:
                return ReceiptResult(ReceiptOutcome.TOO_LARGE)
            if not is_image(data):
                return ReceiptResult(ReceiptOutcome.NOT_A_PHOTO)
            data_b64 = base64.b64encode(data).decode("ascii")
        try:
            order = await self.api.upload_receipt(
                int(order_id), picked.file_ref, platform, chat_id, data_b64=data_b64
            )
        except ShopApiRejected as exc:
            if exc.status == 409 and "deadline" in (exc.detail or "").lower():
                return ReceiptResult(ReceiptOutcome.TOO_LATE)
            if exc.status == 409:
                return ReceiptResult(ReceiptOutcome.NOT_AWAITING)
            return ReceiptResult(ReceiptOutcome.REJECTED, message_fa=exc.message_fa)
        self.store.save_receipt(int(order_id), platform, chat_id, picked.file_ref)
        return ReceiptResult(ReceiptOutcome.SAVED, order=order if isinstance(order, dict) else None)

    async def list_for(self, platform: str, chat_id: str, limit: int = 10) -> list[dict]:
        return list(await self.api.list_user_orders(platform, chat_id) or [])[:limit]

    @staticmethod
    def awaits_payment(order: dict) -> bool:
        return order.get("status") == "awaiting_payment" and order.get("id") is not None
