"""Test fixtures: fake Bot API and fake shopapi served through httpx.MockTransport.

No real network access, no real tokens (the strings below are clearly fake and
only exist so the tests can assert they never leak into logs).
"""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import os

import pytest

from app.config import Settings
from app.engine import BotEngine
from app.platforms import BaleAdapter
from app.shopapi import ShopApiClient
from app.store import Store

BALE_TOKEN = "TESTTOKEN-BALE-000"
BOT_KEY = "test-bot-key"
ADMIN_KEY = "test-admin-key"
ADMIN_CHAT = "9001"
CUSTOMER_CHAT = "5005"
OTHER_CHAT = "5006"


# ============================ fake Bot API ==================================
class FakeBotApi:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.photos: list[dict] = []
        #: v2.6.0: raw multipart bodies of sendDocument (the statement PDF)
        self.documents: list[bytes] = []
        self.edited: list[dict] = []
        self.answered: list[dict] = []
        self.fail_methods: set[str] = set()
        self.raise_on: set[str] = set()
        #: what a file download returns (a JPEG by default)
        self.file_bytes: bytes = b"\xff\xd8\xff\xe0" + b"0" * 64
        self.file_size: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "/file/bot" in request.url.path:
            self.calls.append(("download", {}))
            return httpx.Response(200, content=self.file_bytes)
        method = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        payload = {}
        if request.content:
            try:
                payload = json.loads(request.content.decode())
            except ValueError:
                payload = {}
        self.calls.append((method, payload))
        if method in self.raise_on:
            raise httpx.ConnectError("bot api unreachable")
        if method in self.fail_methods:
            return httpx.Response(200, json={"ok": False, "description": "forced failure"})
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return httpx.Response(200, json={"ok": True, "result": updates})
        if method == "sendMessage":
            self.sent.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 100 + len(self.sent)}})
        if method == "sendDocument":
            self.documents.append(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 300 + len(self.documents)}})
        if method == "sendPhoto":
            self.photos.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 200 + len(self.photos)}})
        if method == "editMessageText":
            self.edited.append(payload)
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "answerCallbackQuery":
            self.answered.append(payload)
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "getFile":
            result = {"file_path": "photos/p.jpg"}
            if self.file_size is not None:
                result["file_size"] = self.file_size
            return httpx.Response(200, json={"ok": True, "result": result})
        return httpx.Response(200, json={"ok": True, "result": True})

    # --- assertions helpers ---
    def texts(self, chat_id=None) -> list[str]:
        return [
            str(p.get("text", ""))
            for p in self.sent
            if chat_id is None or str(p.get("chat_id")) == str(chat_id)
        ]

    def last_text(self, chat_id=None) -> str:
        found = self.texts(chat_id)
        return found[-1] if found else ""

    def edited_texts(self, chat_id=None) -> list[str]:
        return [
            str(p.get("text", ""))
            for p in self.edited
            if chat_id is None or str(p.get("chat_id")) == str(chat_id)
        ]

    def last_text_any(self, chat_id=None) -> str:
        """Last message body for a chat, whether it was sent, edited or a photo caption."""
        latest = ""
        for method, payload in self.calls:
            if method not in ("sendMessage", "editMessageText", "sendPhoto"):
                continue
            if chat_id is not None and str(payload.get("chat_id")) != str(chat_id):
                continue
            latest = str(payload.get("text") or payload.get("caption") or "")
        return latest

    def buttons_for(self, chat_id) -> list[list[tuple[str, str]]]:
        """Inline keyboard of the last message for a chat (sent *or* edited)."""
        result: list[list[tuple[str, str]]] = []
        for method, payload in self.calls:
            if method not in ("sendMessage", "editMessageText", "sendPhoto"):
                continue
            if str(payload.get("chat_id")) != str(chat_id):
                continue
            rows = (payload.get("reply_markup") or {}).get("inline_keyboard")
            if rows:
                result = [
                    [(b.get("text", ""), b.get("callback_data", "")) for b in row] for row in rows
                ]
        return result

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def raw(self) -> str:
        return json.dumps(
            {"calls": self.calls, "photos": self.photos, "edited": self.edited, "answered": self.answered},
            ensure_ascii=False,
            default=str,
        )


# ============================ fake shopapi ==================================
class FakeShopApi:
    def __init__(self):
        self.users: dict[tuple[str, str], dict] = {}
        self.orders: dict[int, dict] = {}
        self.groups = [{"code": 1, "name": "گروه یک"}, {"code": 2, "name": "گروه دو"}]
        self.products = [
            {"code": 101, "name": "کالای الف", "group": 1, "unit_price": 1000.0,
             "available_qty": 10.0, "image": None},
            {"code": 102, "name": "کالای ب", "group": 1, "unit_price": 2000.0,
             "available_qty": 5.0, "image": None},
            {"code": 103, "name": "کالای ج", "group": 2, "unit_price": 3000.0,
             "available_qty": 0.0, "image": None},
            {"code": 104, "name": "کالای د", "group": 2, "unit_price": 4000.0,
             "available_qty": 7.0, "image": None},
        ]
        self.requests: list[tuple[str, str, str]] = []
        self.down = False
        self.person_match: dict | None = None
        self.approve_payment_fails = False
        #: ACCOUNTING_WRITE_ENABLED=false: approve-payment rehearses and keeps the status
        self.dry_run_writes = False
        self.events: list[dict] = []
        #: phone -> accounting person code: registration approves at once (R4)
        self.known_phones: dict[str, int] = {}
        #: PENDING_MAX_ORDER_ITEMS > 0: customers awaiting approval may order
        self.pending_can_order = True
        self.closed = False
        #: v2.5.0 sales state reason while closed (list_not_updated / holiday / weekday_closed)
        self.closed_reason = "list_not_updated"
        #: receipts are refused: the 30-minute deadline has passed
        self.receipt_too_late = False
        self.statement: dict | None = None
        #: v2.6.0: GET .../statement/full (None = 404, an older shopapi -> text statement)
        self.statement_full: dict | None = None
        #: v2.6.0: PAYMENT_CARD_NUMBER of shopapi ("" = not configured -> no checkout)
        self.payment_card = "6037-0000-1111-2222"
        #: the card was removed between the state check and the order
        self.card_removed_meanwhile = False
        #: v2.8.2: payment details staff typed for the order. Set = they come with the
        #: order at once (the old flow most tests use); None = sent later by staff
        #: (``send_payment_info`` + the ``order_payment_info`` event).
        self.auto_payment_info: dict | None = {"card_number": "6037-0000-1111-2222",
                                               "holder": "فروشگاه نمونه"}
        #: v2.8.2: POST /orders?check=true bodies, and products without stock in Sazeh
        self.check_bodies: list[dict] = []
        self.no_stock: set[int] = set()
        #: v2.6.0: «درخواست کالای ناموجود»
        self.item_requests: list[dict] = []
        self.item_request_limit = 10
        #: v2.6.1: staff replies {id: row}, delivery reports, and order refusals
        #: {kala_code: reason} ("is price on inquiry", ...)
        self.item_request_messages: dict[int, dict] = {}
        self.message_results: list[dict] = []
        self.refuse_items: dict[int, str] = {}
        self.statement_requests: list[dict] = []
        self.order_bodies: list[dict] = []
        self.inquiries: list[dict] = []
        self.security_reports: list[dict] = []
        #: site models (REQUIREMENTS §9a): slug -> {name, status, items}
        self.models: dict[str, dict] = {}
        self.resolve_texts: list[str] = []
        #: v2.8.0: rows /phones/search returns (when ``q`` is in the model) and
        #: the «درخواست خرید» bodies received
        self.phone_rows: list[dict] = []
        self.phone_sales_open = True
        self.purchase_requests: list[dict] = []
        #: v2.11.0: the site's cart codes received and what shopapi answers
        self.cart_codes: list[str] = []
        self.cart_answer: dict = {"created": [
            {"id": 1, "name": "Galaxy S26 Ultra", "color": "مشکی", "qty": 2},
            {"id": 2, "name": "پاوربانک Anker 737", "color": "", "qty": 1}],
            "unknown": 1, "repeated": False}
        self.cart_status: int | None = None
        #: v2.9.2: answers to offered prices, the order an accept returns, an error
        self.offer_answers: list[dict] = []
        self.offer_order_id: int | None = None
        self.offer_answer_error: tuple[int, str] | None = None
        self._next_user = 1
        self._next_order = 1

    # --- helpers ---
    @staticmethod
    def _ok(data) -> httpx.Response:
        return httpx.Response(200, json=data)

    @staticmethod
    def _err(status: int, detail: str) -> httpx.Response:
        return httpx.Response(status, json={"detail": detail})

    def add_user(self, platform: str, chat_id, *, name="علی", phone="09121234567",
                 status="pending", person_code=None) -> dict:
        user = {
            "id": self._next_user, "platform": platform, "chat_id": str(chat_id),
            "name": name, "phone": phone, "status": status,
            "person_code": person_code, "created_at": "t",
        }
        self._next_user += 1
        self.users[(platform, str(chat_id))] = user
        return user

    def add_event(self, kind: str, ref_id: int) -> None:
        self.events.append({"id": len(self.events) + 1, "ts": "t", "kind": kind,
                            "ref_id": ref_id, "actor": "staff:admin"})

    def _order_public(self, order: dict) -> dict:
        return {k: v for k, v in order.items() if not k.startswith("_")}

    def _resolve(self, text: str) -> dict:
        """A small stand-in for shopapi's resolver: slug forms + exact names."""
        self.resolve_texts.append(text)
        value = text.strip()
        explicit = False
        slug = None
        if value.startswith("m_"):
            slug, explicit = value[2:].lower(), True
        elif "کد مدل:" in value:
            slug, explicit = value.split("کد مدل:", 1)[1].strip().lower(), True
        elif "-" in value and " " not in value:
            slug, explicit = value.lower(), True
        model = self.models.get(slug) if slug else None
        if model is None:
            first = (value.splitlines() or [""])[0].strip().lower()
            hits = [s for s, m in self.models.items() if first and first in m["name"].lower()]
            if len(hits) > 1:
                return {"status": "ambiguous", "explicit": explicit,
                        "options": [{"slug": s, "name": self.models[s]["name"]} for s in hits]}
            if len(hits) == 1:
                slug, model, explicit = hits[0], self.models[hits[0]], True
        if model is None:
            return {"status": "unknown", "explicit": explicit}
        out = {"status": model.get("status", "found"), "explicit": True,
               "model": {"slug": slug, "name": model["name"]}}
        if out["status"] == "found":
            out["items"] = model["items"]
        return out

    # --- request handler ---
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("shopapi unreachable")
        path = request.url.path
        method = request.method.upper()
        key = request.headers.get("X-API-Key", "")
        self.requests.append((method, path, key))
        body = {}
        if request.content:
            try:
                body = json.loads(request.content.decode())
            except ValueError:
                body = {}
        params = dict(request.url.params)

        # API key separation: admin routes need the admin key; the service
        # (admin) key may also read customer routes, as in shopapi
        if path.startswith("/admin/"):
            if key != ADMIN_KEY:
                return self._err(401, "Invalid API key")
        elif path != "/health" and key not in (BOT_KEY, ADMIN_KEY):
            return self._err(401, "Invalid API key")

        if method == "GET" and path == "/health":
            return self._ok({"status": "ok"})

        if method == "GET" and path == "/groups":
            return self._ok(self.groups)

        if method == "GET" and path == "/shop/state":
            return self._ok({"closed": self.closed, "sales_open": not self.closed,
                             "reason": self.closed_reason if self.closed else "list",
                             "receipt_deadline_minutes": 30,
                             "payment_ready": bool(self.payment_card), "catalog_ready": True})

        if method == "GET" and path.startswith("/products/"):
            code = int(path.split("/")[2])
            product = next((p for p in self.products if p["code"] == code), None)
            if product is None or (product["unit_price"] <= 0 and product.get("variants") is None):
                return self._err(404, "Product not found")
            return self._ok(product)

        if method == "POST" and path == "/inquiries":
            inquiry = {"id": len(self.inquiries) + 1, **body}
            self.inquiries.append(inquiry)
            return httpx.Response(201, json=inquiry)

        if method == "GET" and path.startswith("/admin/inquiries/"):
            inquiry_id = int(path.split("/")[3])
            if inquiry_id > len(self.inquiries):
                return self._err(404, "Inquiry not found")
            return self._ok({"id": inquiry_id, "product_name": "گوشی آزمایشی",
                             "color": "آبی", "customer_name": "علی"})

        if method == "GET" and path.startswith("/users/") and path.endswith("/statement/full"):
            parts = path.split("/")
            user = self.users.get((parts[2], parts[3]))
            if user is None or self.statement_full is None:
                return self._err(404, "Not found")
            if user["status"] != "approved":
                return self._err(403, "User is not approved")
            return self._ok(self.statement_full)

        if method == "GET" and path == "/phones/search":
            q = str(params.get("q") or "").lower()
            items = [r for r in self.phone_rows if q and q in r["model"].lower()]
            return self._ok({"list_ready": True, "sales_open": self.phone_sales_open,
                             "items": items})

        if method == "POST" and path == "/purchase-requests":
            user = self.users.get((str(body.get("platform")), str(body.get("chat_id"))))
            if user is None:
                return self._err(404, "User not found")
            self.purchase_requests.append(body)
            return httpx.Response(201, json={"id": len(self.purchase_requests), "kind": "purchase",
                                             "user_id": user["id"], "status": "new",
                                             "created_at": "t"})

        if method == "POST" and path == "/cart-requests":
            # v2.11.0: the site's cart -> purchase requests (decoded by shopapi)
            user = self.users.get((str(body.get("platform")), str(body.get("chat_id"))))
            if user is None:
                return self._err(404, "User not found")
            if self.cart_status is not None:
                return self._err(self.cart_status, "refused")
            self.cart_codes.append(body.get("code"))
            return httpx.Response(201, json=self.cart_answer)

        if method == "GET" and path == "/item-requests/search":
            q = str(params.get("q") or "")
            return self._ok([{"code": p["code"], "name": p["name"]}
                             for p in self.products if q and q in p["name"]][:8])

        if method == "POST" and path == "/item-requests":
            user = self.users.get((str(body.get("platform")), str(body.get("chat_id"))))
            if user is None:
                return self._err(404, "User not found")
            if len(self.item_requests) >= self.item_request_limit:
                return self._err(429, "Too many requests today")
            name = ""
            if body.get("kala_code"):
                product = next((p for p in self.products if p["code"] == body["kala_code"]), None)
                if product is None:
                    return self._err(404, "Product not found")
                name = product["name"]
            if not name and len(str(body.get("text") or "")) < 2:
                return self._err(422, "Describe the item")
            row = {"id": len(self.item_requests) + 1, "user_id": user["id"], "status": "new",
                   "kala_code": body.get("kala_code"), "product_name": name,
                   "text": body.get("text") or "", "created_at": "t",
                   "kind": body.get("kind") or "unavailable"}
            self.item_requests.append(row)
            return httpx.Response(201, json=row)

        if method == "GET" and path.startswith("/admin/item-request-messages/"):
            row = self.item_request_messages.get(int(path.split("/")[3]))
            return self._ok(row) if row else self._err(404, "Message not found")

        if method == "POST" and path.startswith("/admin/item-request-messages/"):
            message_id = int(path.split("/")[3])
            self.message_results.append({"id": message_id, **body})
            row = self.item_request_messages.get(message_id)
            if row and row["status"] == "pending":
                row["status"] = "sent" if body.get("ok") else "failed"
                row["error"] = body.get("error") or ""
            return self._ok(row)

        if method == "POST" and path.startswith("/admin/item-requests/")                 and path.endswith("/customer-answer"):
            # v2.9.2: the customer's answer to an offered price
            request_id = int(path.split("/")[3])
            self.offer_answers.append({"id": request_id, **body})
            if self.offer_answer_error:
                return self._err(*self.offer_answer_error)
            order = self.orders.get(self.offer_order_id) if body.get("accept") else None
            return self._ok({"request": {"id": request_id},
                             "order": self._order_public(order) if order else None})

        if method == "GET" and path.startswith("/admin/item-requests/"):
            request_id = int(path.split("/")[3])
            if request_id > len(self.item_requests):
                return self._err(404, "Request not found")
            return self._ok({**self.item_requests[request_id - 1], "customer_name": "علی"})

        if method == "GET" and path.startswith("/users/") and path.endswith("/statement"):
            parts = path.split("/")
            user = self.users.get((parts[2], parts[3]))
            if user is None:
                return self._err(404, "User not found")
            if user["status"] != "approved":
                return self._err(403, "User is not approved")
            self.statement_requests.append(params)
            return self._ok(self.statement or {"balance": 0, "side": "zero", "total": 0,
                                               "page": 1, "page_size": 8, "items": []})

        if method == "GET" and path.startswith("/admin/users/"):
            user_id = int(path.split("/")[3])
            user = next((u for u in self.users.values() if u["id"] == user_id), None)
            return self._ok(user) if user else self._err(404, "User not found")

        if method == "GET" and path == "/products":
            items = self.products
            group = params.get("group")
            if group is not None:
                items = [p for p in items if str(p["group"]) == str(group)]
            q = params.get("q")
            if q:
                items = [p for p in items if q in p["name"]]
            if str(params.get("in_stock", "true")).lower() != "false":
                items = [p for p in items if p["available_qty"] > 0 or p.get("price_on_inquiry")]
            page = int(params.get("page", 1))
            page_size = int(params.get("page_size", 5))
            start = (page - 1) * page_size
            return self._ok({
                "total": len(items), "page": page, "page_size": page_size,
                "items": items[start:start + page_size],
            })

        if method == "POST" and path == "/users/register":
            platform = str(body.get("platform"))
            chat_id = str(body.get("chat_id"))
            existing = self.users.get((platform, chat_id))
            if existing and existing["status"] != "pending":
                return self._ok(existing)
            user = existing or self.add_user(platform, chat_id, name=body.get("name", ""),
                                             phone=body.get("phone", ""))
            code = self.known_phones.get(body.get("phone", ""))
            if code is not None:
                user["status"] = "approved"
                user["person_code"] = code
            return self._ok(user)

        if method == "GET" and path.startswith("/admin/users"):
            status_filter = params.get("status")
            users = [u for u in self.users.values() if not status_filter or u["status"] == status_filter]
            return self._ok(users)

        if method == "POST" and path.startswith("/admin/users/") and path.endswith("/approve"):
            user_id = int(path.split("/")[3])
            user = next((u for u in self.users.values() if u["id"] == user_id), None)
            if user is None:
                return self._err(404, "User not found")
            user["status"] = "approved"
            user["person_code"] = body.get("person_code")
            return self._ok(user)

        if method == "POST" and path.startswith("/admin/users/") and path.endswith("/reject"):
            user_id = int(path.split("/")[3])
            user = next((u for u in self.users.values() if u["id"] == user_id), None)
            if user is None:
                return self._err(404, "User not found")
            user["status"] = "rejected"
            return self._ok(user)

        if method == "GET" and path == "/admin/persons/match":
            if self.person_match is None:
                return self._err(404, "No matching person")
            return self._ok(self.person_match)

        if method == "GET" and path == "/admin/events":
            last = self.events[-1]["id"] if self.events else 0
            if "after" not in params:
                return self._ok({"last_id": last, "items": []})
            after = int(params["after"])
            items = [e for e in self.events if e["id"] > after]
            return self._ok({"last_id": items[-1]["id"] if items else min(after, last),
                             "items": items})

        if method == "GET" and path == "/admin/orders":
            status_filter = params.get("status")
            orders = [o for o in self.orders.values() if not status_filter or o["status"] == status_filter]
            return self._ok([self._order_public(o) for o in orders])

        if method == "POST" and path.startswith("/admin/orders/") and path.endswith("/approve-payment"):
            order_id = int(path.split("/")[3])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            if self.approve_payment_fails:
                return self._err(409, "Insufficient stock for product 101")
            if self.dry_run_writes:
                return self._ok(self._order_public(order))
            order["status"] = "written"
            order["accounting_order_no"] = 777
            return self._ok(self._order_public(order))

        if method == "POST" and path.startswith("/admin/orders/") and path.endswith("/reject-payment"):
            order_id = int(path.split("/")[3])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            order["status"] = "rejected"
            return self._ok(self._order_public(order))

        if method == "GET" and path.startswith("/users/") and path.endswith("/orders"):
            parts = path.split("/")
            platform, chat_id = parts[2], parts[3]
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            mine = [o for o in self.orders.values()
                    if o["_platform"] == platform and o["_chat_id"] == chat_id]
            return self._ok([self._order_public(o) for o in mine])

        if method == "GET" and path.startswith("/users/"):
            parts = path.split("/")
            platform, chat_id = parts[2], parts[3]
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            return self._ok(user)

        if method == "POST" and path == "/orders":
            platform = str(body.get("platform"))
            chat_id = str(body.get("chat_id"))
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            if user["status"] == "rejected" or (
                    user["status"] != "approved" and not self.pending_can_order):
                return self._err(403, "User is not approved")
            if not self.payment_card or self.card_removed_meanwhile:
                return self._err(409, "Payment details are not configured")
            if self.closed and any(line.get("variant_id") for line in body.get("items", [])):
                # v2.5.0: closed sales block only phones (price-list items)
                return self._err(409, f"Sales are closed: {self.closed_reason}")
            items = []
            total = 0.0
            checking = str(params.get("check", "")).lower() == "true"
            (self.check_bodies if checking else self.order_bodies).append(body)
            for line in body.get("items", []):
                if line["kala_code"] in self.no_stock:
                    return self._err(422, f"Product {line['kala_code']} has no stock; "
                                          f"purchase request")
                if line["kala_code"] in self.refuse_items:
                    return self._err(422, f"Product {line['kala_code']} "
                                          f"{self.refuse_items[line['kala_code']]}")
                product = next((p for p in self.products if p["code"] == line["kala_code"]), None)
                if product is not None and product.get("variants") is not None:
                    color = next((v for v in product["variants"]
                                  if v["id"] == line.get("variant_id")), None)
                    if color is None:
                        return self._err(422, "Choose a color")
                    if not color["available"]:
                        return self._err(409, "Color not available")
                    items.append({
                        "kala_code": line["kala_code"],
                        "name": f"{product['name']} — {color['color']}", "qty": line["qty"],
                        "unit_price": color["unit_price"], "variant_id": color["id"],
                        "variant": color["color"], "part": color.get("part"),
                    })
                    total += float(line["qty"]) * float(color["unit_price"])
                    continue
                if product is None or product["unit_price"] <= 0:
                    return self._err(422, f"Product {line['kala_code']} is not available for sale")
                if product["available_qty"] < line["qty"]:
                    return self._err(409, f"Insufficient stock for product {line['kala_code']}")
                items.append({
                    "kala_code": line["kala_code"], "name": product["name"],
                    "qty": line["qty"], "unit_price": product["unit_price"],
                })
                total += float(line["qty"]) * float(product["unit_price"])
            if checking:
                return self._ok({"id": 0, "status": "check", "price_level": 3, "total": total,
                                 "created_at": "t", "items": items})
            order_id = self._next_order
            self._next_order += 1
            order = {
                "id": order_id, "status": "awaiting_payment", "price_level": 3, "total": total,
                "reserve_until": "t+30m", "accounting_order_no": None, "created_at": "t",
                "items": items, "payment_instructions": "واریز به کارت 1234",
                "payment_card_number": self.payment_card or None, "payment_sheba": None,
                "payment_owner": "فروشگاه نمونه",
                "payment_info": dict(self.auto_payment_info) if self.auto_payment_info else None,
                "user_id": user["id"], "customer_pending": user["status"] != "approved",
                "_platform": platform, "_chat_id": chat_id,
            }
            self.orders[order_id] = order
            return self._ok(self._order_public(order))

        if method == "POST" and path.startswith("/orders/") and path.endswith("/cancel"):
            order = self.orders.get(int(path.split("/")[2]))
            if order is None or order["_platform"] != params.get("platform")                     or order["_chat_id"] != str(params.get("chat_id")):
                return self._err(404, "Order not found")
            if order["status"] == "receipt_uploaded":
                return self._err(409, "Receipt already sent; the order cannot be cancelled")
            if order["status"] != "awaiting_payment":
                return self._err(409, f"Order in status {order['status']}; cannot be cancelled")
            order["status"] = "cancelled"
            return self._ok(self._order_public(order))

        if method == "POST" and path.startswith("/orders/") and path.endswith("/receipt"):
            order_id = int(path.split("/")[2])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            platform = params.get("platform")
            chat_id = params.get("chat_id")
            if (not platform or not chat_id or order["_platform"] != platform
                    or order["_chat_id"] != str(chat_id)):
                return self._err(404, "Order not found")
            if self.receipt_too_late and order["status"] == "awaiting_payment":
                order["status"] = "cancelled"
            if order["status"] == "cancelled" and self.receipt_too_late:
                return self._err(409, "Receipt deadline passed; order cancelled")
            if order["status"] != "awaiting_payment":
                return self._err(409, f"Order in status {order['status']}")
            order["status"] = "receipt_uploaded"
            order["receipt_ref"] = body.get("receipt_ref")
            order["_receipt_b64"] = body.get("data_b64")
            return self._ok(self._order_public(order))

        if method == "GET" and path.startswith("/orders/"):
            order_id = int(path.split("/")[2])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            platform = params.get("platform")
            chat_id = params.get("chat_id")
            if platform and chat_id:
                if order["_platform"] != platform or order["_chat_id"] != str(chat_id):
                    return self._err(404, "Order not found")
            return self._ok(self._order_public(order))

        if method == "GET" and path == "/catalog/resolve":
            return self._ok(self._resolve(params.get("text", "")))

        if method == "POST" and path == "/security/report":
            self.security_reports.append(json.loads(request.content or b"{}"))
            return httpx.Response(204)

        return self._err(404, f"no route for {method} {path}")


# ============================ update builders ===============================
def message_update(update_id: int, chat_id, *, text=None, contact=None, photo=None,
                   document=None, chat_type="private", from_id="same") -> dict:
    message = {"message_id": update_id, "chat": {"id": chat_id, "type": chat_type}}
    if from_id is not None:
        message["from"] = {"id": chat_id if from_id == "same" else from_id,
                           "first_name": "Bale", "last_name": "User"}
    if text is not None:
        message["text"] = text
    if contact is not None:
        message["contact"] = contact
    if photo is not None:
        message["photo"] = photo
    if document is not None:
        message["document"] = document
    return {"update_id": update_id, "message": message}


def own_contact(chat_id, phone="09121234567", **extra) -> dict:
    """What Bale's share-contact button sends for the user's own number."""
    return {"phone_number": phone, "user_id": int(chat_id), "first_name": "Ali",
            "last_name": "Rezaei", **extra}


def callback_update(update_id: int, chat_id, data, *, chat_type="private") -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb-{update_id}",
            "data": data,
            "message": {"message_id": update_id, "chat": {"id": chat_id, "type": chat_type}},
        },
    }


async def push_message(engine, platform, update_id, chat_id, **kwargs) -> bool:
    return await engine.handle_update(platform, message_update(update_id, chat_id, **kwargs))


async def push_callback(engine, platform, update_id, chat_id, data, **kwargs) -> bool:
    return await engine.handle_update(platform, callback_update(update_id, chat_id, data, **kwargs))


# ============================ fixtures ======================================
@pytest.fixture
def settings():
    return Settings(
        shopapi_base_url="http://shopapi.test",
        bot_api_key=BOT_KEY,
        admin_api_key=ADMIN_KEY,
        bale_token=BALE_TOKEN,
        bale_api_base="https://bale.test",
        admin_chat_ids=(f"bale:{ADMIN_CHAT}",),
        sqlite_path=":memory:",
        poll_timeout=1,
        admin_sweep_seconds=30,
        rate_limit_messages=20,
        rate_limit_window=60.0,
        product_page_size=2,
    )


@pytest.fixture
def bot_apis():
    return {"bale": FakeBotApi()}


@pytest.fixture
def shopapi():
    return FakeShopApi()


@pytest.fixture
def store():
    return Store(":memory:")


@contextlib.asynccontextmanager
async def bot_env(settings, store, shopapi, bot_apis, rate_limiter=None):
    clients: list[httpx.AsyncClient] = []
    adapters = {}
    for platform, adapter_cls, base, token in (
        ("bale", BaleAdapter, settings.bale_api_base, settings.bale_token),
    ):
        client = httpx.AsyncClient(transport=httpx.MockTransport(bot_apis[platform].handler))
        clients.append(client)
        adapters[platform] = adapter_cls(token=token, api_base=base, client=client)
    api_client = httpx.AsyncClient(transport=httpx.MockTransport(shopapi.handler))
    clients.append(api_client)
    api = ShopApiClient(settings, client=api_client)
    engine = BotEngine(settings, store, api, adapters, rate_limiter=rate_limiter)
    try:
        yield engine, adapters, api
    finally:
        for client in clients:
            await client.aclose()


@pytest.fixture
def env(settings, store, shopapi, bot_apis):
    """Run one async scenario with a fully wired engine inside a single event loop."""

    def _run(scenario, rate_limiter=None):
        async def wrapper():
            async with bot_env(settings, store, shopapi, bot_apis, rate_limiter) as ctx:
                return await scenario(*ctx)

        return asyncio.run(wrapper())

    return _run


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Tests never read a real .env (a developer's ACCOUNTING_STATUS_CODE=0 or
    tokens would change results). Opt out only for live runs:
    SHOP_TESTS_USE_DOTENV=1."""
    if os.environ.get("SHOP_TESTS_USE_DOTENV") == "1":
        return
    from app import config

    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
