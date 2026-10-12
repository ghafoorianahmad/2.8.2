"""Shared core (app/core): channel-independent shop logic, tested without any Bot API."""
from __future__ import annotations

import asyncio
import base64

from app.core import (
    MAX_QTY,
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_PENDING,
    STATUS_REJECTED,
    CartService,
    CatalogService,
    ContactProblem,
    CustomerService,
    OrderService,
    ReceiptOutcome,
    normalize_search,
    parse_product_ref,
    receipt_file,
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

    async def upload_receipt(self, order_id, file_ref, platform, chat_id, data_b64=None):
        self.calls.append(("upload_receipt", order_id, file_ref, data_b64))
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


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


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


def test_receipt_photo_or_image_document():
    limit = 1000
    assert receipt_file([{"file_id": "p", "file_size": 10}], None, limit).file_ref == "p"
    doc = {"file_id": "d", "mime_type": "image/png", "file_size": 10}
    assert receipt_file(None, doc, limit).file_ref == "d"
    named = {"file_id": "n", "file_name": "receipt.JPG"}
    assert receipt_file(None, named, limit).file_ref == "n"
    pdf = {"file_id": "x", "mime_type": "application/pdf"}
    assert receipt_file(None, pdf, limit).outcome is ReceiptOutcome.NOT_A_PHOTO
    big = {"file_id": "b", "mime_type": "image/jpeg", "file_size": limit + 1}
    assert receipt_file(None, big, limit).outcome is ReceiptOutcome.TOO_LARGE
    assert receipt_file([{"file_id": "p", "file_size": limit + 1}], None, limit).outcome \
        is ReceiptOutcome.TOO_LARGE


def test_receipt_is_downloaded_checked_and_sent():
    api, store, orders = _orders()
    orders.receipt_max_bytes = 100
    doc = {"file_id": "d", "mime_type": "image/jpeg"}

    async def ok(ref, limit):
        assert ref == "d" and limit == 100
        return JPEG

    saved = run(orders.attach_receipt("bale", "1", 7, None, doc, download=ok))
    assert saved.outcome is ReceiptOutcome.SAVED
    assert base64.b64decode(api.calls[-1][3]) == JPEG

    async def html(ref, limit):
        return b"<html>not an image</html>"

    assert run(orders.attach_receipt("bale", "1", 7, None, doc, download=html)).outcome \
        is ReceiptOutcome.NOT_A_PHOTO

    async def huge(ref, limit):
        return JPEG + b"0" * 200

    assert run(orders.attach_receipt("bale", "1", 7, None, doc, download=huge)).outcome \
        is ReceiptOutcome.TOO_LARGE

    async def broken(ref, limit):
        raise RuntimeError("network")

    assert run(orders.attach_receipt("bale", "1", 7, None, doc, download=broken)).outcome \
        is ReceiptOutcome.DOWNLOAD_FAILED


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


def test_contact_verification():
    api = StubApi()
    customers = CustomerService(api, max_name_len=10)
    own = {"phone_number": "+989121234567", "user_id": 5, "first_name": "علی"}
    verified = customers.verify_contact(own, 5)
    assert verified.problem is ContactProblem.NONE
    assert verified.phone == "09121234567" and verified.name == "علی"
    assert customers.verify_contact(own, "5").problem is ContactProblem.NONE
    # never a typed number, never somebody else's contact
    assert customers.verify_contact(None, 5).problem is ContactProblem.NO_CONTACT
    assert customers.verify_contact(own, 6).problem is ContactProblem.NOT_OWN
    assert customers.verify_contact(own, None).problem is ContactProblem.NOT_OWN
    no_owner = {"phone_number": "09121234567"}
    assert customers.verify_contact(no_owner, 5).problem is ContactProblem.NOT_OWN
    foreign = {"phone_number": "+14155550100", "user_id": 5}
    assert customers.verify_contact(foreign, 5).problem is ContactProblem.NOT_MOBILE
    # name: contact -> sender profile -> default; trimmed to max_name_len
    nameless = {"phone_number": "09121234567", "user_id": 5}
    assert customers.verify_contact(nameless, 5, {"first_name": "Sara"}).name == "Sara"
    assert customers.verify_contact(nameless, 5).name == "مشتری"
    long_name = {**nameless, "first_name": "x" * 30}
    assert customers.verify_contact(long_name, 5).name == "x" * 10
    run(customers.register("bale", "1", verified))
    assert api.calls[-1] == ("register_user", "bale", "1", "علی", "09121234567")


def test_product_ref_parsing():
    assert parse_product_ref("kala_289") == 289
    assert parse_product_ref("KALA_۲۸۹") == 289
    assert parse_product_ref("289") is None
    assert parse_product_ref("289", allow_bare_code=True) == 289
    for typed in ("kala289", "KALA289", "kala-289", "kala 289", "کد 289", "کد کالا: ۲۸۹", "#289"):
        assert parse_product_ref(typed) == 289, typed
    assert parse_product_ref("09121234567", allow_bare_code=True) is None  # a phone, not a code
    for bad in ("kala_", "kala_x", "kala_0", "kala_123456789", "hello", "", None):
        assert parse_product_ref(bad, allow_bare_code=True) is None


def test_site_model_slugs_are_never_read_as_product_codes():
    # Phase 6 site: deep link m_<slug> and the copied "name + کد مدل: slug" text
    # (REQUIREMENTS §9) go to shopapi's model resolver (§9a, test_phase6b),
    # never resolve to a numeric Kala code.
    for slug in ("iphone-17-pro", "galaxy-s25-ultra", "redmi-note-14-pro-5g", "poco-x7", "iphone-16e"):
        for sent in (slug, "m_" + slug, "iPhone 17 Pro\nکد مدل: " + slug, "کد مدل: " + slug):
            assert parse_product_ref(sent, allow_bare_code=True) is None, sent
