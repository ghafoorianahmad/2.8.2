"""Orders: checkout from the cart, payment receipts, a customer's order list."""
from __future__ import annotations

import enum
from dataclasses import dataclass

from ..shopapi import ShopApiClient, ShopApiRejected
from ..store import Store
from .cart import CartService


class ReceiptOutcome(enum.Enum):
    SAVED = "saved"
    NO_ORDER = "no_order"            # no order is waiting for a receipt
    NOT_A_PHOTO = "not_a_photo"
    NOT_AWAITING = "not_awaiting"    # shopapi: the order no longer waits for payment
    REJECTED = "rejected"            # shopapi refused for another reason (message_fa)


@dataclass
class CheckoutResult:
    order: dict | None = None
    empty_cart: bool = False


@dataclass
class ReceiptResult:
    outcome: ReceiptOutcome
    order: dict | None = None
    message_fa: str = ""


def receipt_file_ref(photo) -> str | None:
    """The largest size of a Bot-API photo (the last entry), or None."""
    if isinstance(photo, list) and photo:
        last = photo[-1]
        if isinstance(last, dict) and last.get("file_id"):
            return str(last["file_id"])
    return None


class OrderService:
    def __init__(self, api: ShopApiClient, store: Store, cart: CartService):
        self.api = api
        self.store = store
        self.cart = cart

    async def checkout(self, platform: str, chat_id: str) -> CheckoutResult:
        items = self.cart.items(platform, chat_id)
        if not items:
            return CheckoutResult(empty_cart=True)
        order = await self.api.create_order(platform, chat_id, self.cart.order_payload(items))
        if order:
            self.cart.clear(platform, chat_id)
        return CheckoutResult(order=order or None)

    async def attach_receipt(
        self, platform: str, chat_id: str, order_id, photo
    ) -> ReceiptResult:
        file_ref = receipt_file_ref(photo)
        if not order_id:
            return ReceiptResult(ReceiptOutcome.NO_ORDER)
        if not file_ref:
            return ReceiptResult(ReceiptOutcome.NOT_A_PHOTO)
        try:
            order = await self.api.upload_receipt(int(order_id), file_ref, platform, chat_id)
        except ShopApiRejected as exc:
            if exc.status == 409:
                return ReceiptResult(ReceiptOutcome.NOT_AWAITING)
            return ReceiptResult(ReceiptOutcome.REJECTED, message_fa=exc.message_fa)
        self.store.save_receipt(int(order_id), platform, chat_id, file_ref)
        return ReceiptResult(ReceiptOutcome.SAVED, order=order if isinstance(order, dict) else None)

    async def list_for(self, platform: str, chat_id: str, limit: int = 10) -> list[dict]:
        return list(await self.api.list_user_orders(platform, chat_id) or [])[:limit]

    @staticmethod
    def awaits_payment(order: dict) -> bool:
        return order.get("status") == "awaiting_payment" and order.get("id") is not None
