"""Per-chat cart kept in the bot's own SQLite state."""
from __future__ import annotations

from ..store import Store

MAX_QTY = 1000


def clamp_qty(qty) -> int:
    return max(1, min(int(qty or 1), MAX_QTY))


class CartService:
    def __init__(self, store: Store):
        self.store = store

    def items(self, platform: str, chat_id: str) -> list[dict]:
        return self.store.cart_list(platform, chat_id)

    @staticmethod
    def total(items: list[dict]) -> float:
        return sum(float(it["qty"]) * float(it["unit_price"]) for it in items)

    def add(self, platform: str, chat_id: str, code: int, name: str, qty, price: float) -> int:
        qty = clamp_qty(qty)
        self.store.cart_add(platform, chat_id, code, name, qty, price)
        return qty

    def change(self, platform: str, chat_id: str, code: int, delta: float) -> bool:
        """Add `delta` to an item's quantity; 0 or less removes it. False = not in cart."""
        items = {int(it["kala_code"]): it for it in self.items(platform, chat_id)}
        item = items.get(int(code))
        if item is None:
            return False
        new_qty = float(item["qty"]) + float(delta)
        if new_qty <= 0:
            self.store.cart_remove(platform, chat_id, int(code))
        else:
            self.store.cart_set_qty(platform, chat_id, int(code), min(new_qty, MAX_QTY))
        return True

    def remove(self, platform: str, chat_id: str, code: int) -> None:
        self.store.cart_remove(platform, chat_id, int(code))

    def clear(self, platform: str, chat_id: str) -> None:
        self.store.cart_clear(platform, chat_id)

    @staticmethod
    def order_payload(items: list[dict]) -> list[dict]:
        """Only codes and quantities: shopapi prices the order itself."""
        return [{"kala_code": int(it["kala_code"]), "qty": float(it["qty"])} for it in items]
