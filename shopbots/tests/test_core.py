"""Shared core (app/core): channel-independent shop logic, tested without any Bot API."""
from __future__ import annotations

import asyncio

from app.core import (
    MAX_QTY,
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_PENDING,
    STATUS_REJECTED,
    CartService,
    CatalogService,
    CustomerService,
    OrderService,
    ReceiptOutcome,
    normalize_search,
    receipt_file_ref,
)
from app.shopapi import ShopApiRejected
from app.store import Store


class StubApi:
    """Duck-typed stand-in for ShopApiClient; records what the core sends."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.user = None
        self.order = {"id": 7, "total": 300, "status": "awaiting_payment"}
        self.receipt_error: Exception | None = None

    async def get_groups(self):
        return [{"code": 1, "name": "قاب"}, "junk"]

    async def get_products(self, **kwargs):
        self.calls.append(("get_products", kwargs))
        return {"total": 5, "items": [
            {"code": 101, "name": "کابل", "unit_price": 100, "available_qty": 3},
            {"code": 102, "name": "شارژر", "unit_price": 250, "available_qty": 0},
        ]}

    async def get_user(self, platform, chat_id):
        return self.user

    async def register_user(self, platform, chat_id, name, phone):
        self.calls.append(("register_user", platform, chat_id, name, phone))

    async def create_order(self, platform, chat_id, items):
        self.calls.append(("create_order", items))
        return self.order

    async def upload_receipt(self, order_id, file_ref, platform, chat_id):
        self.calls.append(("upload_receipt", order_id, file_ref))
        if self.receipt_error:
            raise self.receipt_error
        return {"id": order_id, "status": "receipt_uploaded"}

    async def list_user_orders(self, platform, chat_id):
        return [{"id": i, "status": "awaiting_payment"} for i in range(15)]


def run(coro):
    return asyncio.run(coro)


# ---- catalog ---------------------------------------------------------------
def test_search_text_is_normalized_for_arabic_letters_and_digits():
    assert normalize_search("  كابل  آيفون ۱۲ ") == "کابل آیفون 12"
    assert normalize_search(None) == ""


def test_catalog_pages_and_normalized_query():
    api = StubApi()
    catalog = CatalogService(api, page_size=2, show_out_of_stock=True)
    page = run(catalog.products(q="كابل", page=0))
    assert page.page == 1 and page.pages == 3 and page.total == 5
    assert [p.code for p in page.items] == [101, 102]
    assert page.items[0].in_stock and not page.items[1].in_stock
    assert page.items[0].as_cache() == {"name": "کابل", "price": 100.0, "qty": 3.0}
    sent = api.calls[-1][1]
    assert sent["q"] == "کابل" and sent["in_stock"] is False and sent["page_size"] == 2
    assert run(catalog.groups()) == [{"code": 1, "name": "قاب"}]


def test_catalog_blank_query_means_no_filter():
    api = StubApi()
    run(CatalogService(api, page_size=5, show_out_of_stock=False).products(q="   "))
    assert api.calls[-1][1]["q"] is None and api.calls[-1][1]["in_stock"] is True


# ---- cart ------------------------------------------------------------------
def test_cart_limits_changes_and_payload():
    cart = CartService(Store(":memory:"))
    assert cart.add("bale", "1", 101, "کابل", 5000, 100.0) == MAX_QTY
    cart.add("bale", "1", 102, "شارژر", 0, 250.0)          # 0 -> at least 1
    assert cart.change("bale", "1", 102, +2) is True
    assert cart.change("bale", "1", 999, +1) is False      # not in the cart
    items = cart.items("bale", "1")
    assert cart.total(items) == MAX_QTY * 100.0 + 3 * 250.0
    assert cart.order_payload(items) == [
        {"kala_code": 101, "qty": float(MAX_QTY)}, {"kala_code": 102, "qty": 3.0},
    ]
    assert cart.change("bale", "1", 102, -3) is True       # down to 0 removes it
    assert [it["kala_code"] for it in cart.items("bale", "1")] == [101]
    assert cart.items("bale", "2") == []                   # carts are per chat


# ---- orders ----------------------------------------------------------------
def _orders():
    api, store = StubApi(), Store(":memory:")
    return api, store, OrderService(api, store, CartService(store))


def test_checkout_sends_codes_and_quantities_only_and_clears_the_cart():
    api, store, orders = _orders()
    assert run(orders.checkout("bale", "1")).empty_cart is True
    orders.cart.add("bale", "1", 101, "کابل", 2, 1.0)    # a client price is never sent
    result = run(orders.checkout("bale", "1"))
    assert result.order["id"] == 7
    assert api.calls[-1] == ("create_order", [{"kala_code": 101, "qty": 2.0}])
    assert orders.cart.items("bale", "1") == []


def test_failed_checkout_keeps_the_cart():
    api, store, orders = _orders()
    api.order = None
    orders.cart.add("bale", "1", 101, "کابل", 1, 1.0)
    assert run(orders.checkout("bale", "1")).order is None
    assert len(orders.cart.items("bale", "1")) == 1


def test_receipt_outcomes():
    photo = [{"file_id": "small"}, {"file_id": "big"}]
    assert receipt_file_ref(photo) == "big"
    assert receipt_file_ref("text") is None

    api, store, orders = _orders()
    assert run(orders.attach_receipt("bale", "1", None, photo)).outcome is ReceiptOutcome.NO_ORDER
    assert run(orders.attach_receipt("bale", "1", 7, None)).outcome is ReceiptOutcome.NOT_A_PHOTO
    saved = run(orders.attach_receipt("bale", "1", 7, photo))
    assert saved.outcome is ReceiptOutcome.SAVED and saved.order["id"] == 7
    assert store.get_receipt(7)["file_ref"] == "big"

    api.receipt_error = ShopApiRejected("دیگر منتظر پرداخت نیست", status=409)
    assert run(orders.attach_receipt("bale", "1", 7, photo)).outcome is ReceiptOutcome.NOT_AWAITING
    api.receipt_error = ShopApiRejected("سفارش پیدا نشد", status=404)
    rejected = run(orders.attach_receipt("bale", "1", 7, photo))
    assert rejected.outcome is ReceiptOutcome.REJECTED and rejected.message_fa == "سفارش پیدا نشد"


def test_order_list_is_capped():
    _api, _store, orders = _orders()
    listed = run(orders.list_for("bale", "1"))
    assert len(listed) == 10 and orders.awaits_payment(listed[0])


# ---- customers -------------------------------------------------------------
def test_customer_status_mapping():
    api = StubApi()
    customers = CustomerService(api, max_name_len=80)
    assert run(customers.status("bale", "1")) == STATUS_NEW
    for raw, expected in (("approved", STATUS_APPROVED), ("rejected", STATUS_REJECTED),
                          ("pending", STATUS_PENDING), (None, STATUS_PENDING)):
        api.user = {"status": raw}
        assert run(customers.status("bale", "1")) == expected


def test_customer_name_phone_and_registration():
    api = StubApi()
    customers = CustomerService(api, max_name_len=10)
    assert customers.valid_name("  علی ") == "علی"
    for bad in ("", "ع", "/start", "x" * 11):
        assert customers.valid_name(bad) is None
    assert customers.phone_from("", {"phone_number": "+989121234567"}) == "09121234567"
    assert customers.phone_from("۰۹۱۲۱۲۳۴۵۶۷", None) == "09121234567"
    assert customers.phone_from("123", None) == ""
    run(customers.register("bale", "1", "  ", "09121234567"))
    assert api.calls[-1] == ("register_user", "bale", "1", "مشتری", "09121234567")
