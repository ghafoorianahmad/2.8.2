"""Shared conversation engine: routing, customer flow, admin flow.

The engine is platform agnostic — it only talks to a PlatformAdapter and to the
shop core (`app/core`: catalog, cart, orders, customers), which talks to shopapi.
The engine owns states, texts and keyboards; the core owns the shop rules.
Prices always come from shopapi; a user can never supply one.

Privacy: this module never logs names, phones or message text. Log lines are
produced only by `utils.log_event` (platform, update id, event type).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import asyncio

from . import texts
from .config import Settings
from .core import (
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_REJECTED,
    CartService,
    CatalogService,
    ContactProblem,
    CustomerService,
    OrderService,
    ReceiptOutcome,
    looks_like_model_ref,
    parse_product_ref,
)
from .core.cart import clamp_qty
from .platforms import (
    BotApiError,
    PlatformAdapter,
    contact_keyboard,
    inline_keyboard,
    remove_keyboard,
    reply_keyboard,
)
from .ratelimit import RateLimiter
from .shopapi import (
    ShopApiClient,
    ShopApiError,
    ShopApiRejected,
    ShopApiUnavailable,
    format_admin_error,
)
from .store import Store
from .utils import (
    fmt_num,
    log_event,
    mask_phone,
    normalize_digits,
    parse_int,
    shorten,
)

# --- conversation states ----------------------------------------------------
STATE_NONE = ""
STATE_AWAIT_CONTACT = "await_contact"
#: States of the old name -> typed-phone registration; a conversation left in
#: one of them continues as contact-only registration.
LEGACY_REGISTRATION_STATES = frozenset({"await_name", "await_phone"})
STATE_AWAIT_SEARCH = "await_search"
STATE_AWAIT_RECEIPT = "await_receipt"
STATE_ADMIN_PERSON_CODE = "admin_person_code"

# --- callback payloads ------------------------------------------------------
# "action" or "action:int[:int]"; every action has a fixed argument count.
CALLBACK_ARG_COUNTS: dict[str, int] = {
    "menu": 0,
    "groups": 0,
    "cart": 0,
    "orders": 0,
    "contact": 0,
    "support": 0,
    "info": 0,
    "search": 0,
    "cclear": 0,
    "checkout": 0,
    "grp": 1,
    "prod": 1,
    "cinc": 1,
    "cdec": 1,
    "cdel": 1,
    "addu": 1,
    "adru": 1,
    "adap": 1,
    "adrp": 1,
    "adst": 1,
    "rcpt": 1,
    "stmt": 1,
    "pg": 2,
    "qty": 2,
    "add": 2,
    "adsug": 2,
    # phone colors (REQUIREMENTS §4): product, color [, qty]
    "col": 2,
    "vqty": 3,
    "vadd": 3,
    "vinc": 2,
    "vdec": 2,
    "vdel": 2,
    "inq": 2,
    # site models (REQUIREMENTS §9a): a product of the model / one of the options
    "kp": 1,
    "mdl": 1,
}
ADMIN_ACTIONS = frozenset({"addu", "adru", "adap", "adrp", "adsug", "adst"})
#: Screens anyone may open, even before registration is approved.
PUBLIC_ACTIONS = frozenset({"support", "info", "contact"})
#: shopapi event kinds that mean "tell the customer" (decisions made in ShopAdmin too).
CUSTOMER_EVENT_KINDS = frozenset(
    {
        "customer_approved", "customer_rejected", "payment_approved", "payment_rejected",
        "order_partially_invoiced", "order_invoiced", "order_shipped",
        "order_auto_cancelled",
    }
)
INVOICE_EVENT_KINDS = frozenset({"order_partially_invoiced", "order_invoiced"})
#: order event kind -> customer message (tracking: invoiced / shipped)
ORDER_EVENT_TEXTS = {
    "payment_approved": "PAYMENT_APPROVED",
    "payment_rejected": "PAYMENT_REJECTED",
    "order_partially_invoiced": "ORDER_PARTIALLY_INVOICED",
    "order_invoiced": "ORDER_INVOICED",
    "order_shipped": "ORDER_SHIPPED",
    # v2.5.0: no receipt within the deadline -> cancelled locally by shopapi
    "order_auto_cancelled": "ORDER_AUTO_CANCELLED",
}
#: shopapi event kinds that mean "tell the owner" (admin chats) -> text key.
OWNER_EVENT_TEXTS = {
    "pricelist_held": "PRICELIST_HELD_NOTICE",
    "pricelist_failed": "PRICELIST_FAILED_NOTICE",
    "proxies_all_dead": "PROXIES_DEAD_NOTICE",
    "telegram_login_required": "TG_LOGIN_NOTICE",
    "telegram_unreachable": "TG_UNREACHABLE_NOTICE",
    "price_inquiry": "INQUIRY_NOTICE",
    # v2.5.0: never deleted in the accounting DB; the owner decides there
    "accounting_duplicate_order": "DUPLICATE_ORDER_NOTICE",
    "order_timeout_written": "TIMEOUT_WRITTEN_NOTICE",
}
SHOP_STATE_TTL = 30.0
#: Receipt deadline when shopapi does not say (minutes).
DEFAULT_RECEIPT_MINUTES = 30
EVENT_CURSOR_KEY = "shopapi_event_cursor"
MAX_CALLBACK_LEN = 64
MAX_CALLBACK_ARG = 1_000_000_000


def parse_callback(data: Any) -> tuple[str, list[int]] | None:
    """Validate a callback payload; return (action, [int args]) or None."""
    if not isinstance(data, str) or not data or len(data) > MAX_CALLBACK_LEN:
        return None
    parts = data.split(":")
    action = parts[0]
    expected = CALLBACK_ARG_COUNTS.get(action)
    if expected is None:
        return None
    raw_args = parts[1:]
    if len(raw_args) != expected:
        return None
    args: list[int] = []
    for raw in raw_args:
        if not raw.isdigit():
            return None
        value = int(raw)
        if value < 0 or value > MAX_CALLBACK_ARG:
            return None
        args.append(value)
    return action, args


def _stock_label(in_stock: bool) -> str:
    return texts.IN_STOCK if in_stock else texts.OUT_OF_STOCK_LABEL


def _safe_error(exc: BaseException) -> str:
    """A log-safe error description (never a URL, which would embed a token)."""
    if isinstance(exc, (BotApiError, ShopApiError)):
        return f"{type(exc).__name__}:{exc}"
    return type(exc).__name__


class BotEngine:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        api: ShopApiClient,
        adapters: dict[str, PlatformAdapter],
        *,
        rate_limiter: RateLimiter | None = None,
        logger: logging.Logger | None = None,
    ):
        self.settings = settings
        self.store = store
        self.api = api
        self.adapters = adapters
        self.rate_limiter = rate_limiter or RateLimiter(
            settings.rate_limit_messages, settings.rate_limit_window
        )
        self.logger = logger or logging.getLogger("shopbots.engine")
        # channel-independent shop logic (app/core)
        self.catalog = CatalogService(
            api, page_size=settings.product_page_size,
            show_out_of_stock=settings.show_out_of_stock,
        )
        self.cart = CartService(store)
        self.orders = OrderService(
            api, store, self.cart, receipt_max_bytes=settings.receipt_max_bytes
        )
        self.customers = CustomerService(api, max_name_len=settings.max_name_len)
        #: receipts are downloaded and stored: a stricter per-customer limit
        self.receipt_limiter = RateLimiter(
            settings.receipt_rate_count, settings.receipt_rate_window
        )
        self._shop_state: tuple[float, dict] | None = None
        #: (kind, platform, chat) -> monotonic time of the last security report
        self._security_reported: dict[tuple[str, str, str], float] = {}

    # ================= update entry point =================================
    async def handle_update(self, platform: str, update: dict) -> bool:
        """Process one update at most once. Returns True when it was handled."""
        adapter = self.adapters.get(platform)
        if adapter is None or not isinstance(update, dict):
            return False
        update_id = parse_int(str(update.get("update_id", "")), minimum=0)
        if update_id is None:
            return False
        if not self.store.is_new_update(platform, update_id):
            return False

        event = self._parse_update(update)
        if event is None:
            log_event(self.logger, platform, update_id, "ignored")
            self.store.set_last_update_id(platform, update_id)
            return False

        log_event(self.logger, platform, update_id, event["type"])
        try:
            if event.get("chat_type") not in (None, "private"):
                log_event(self.logger, platform, update_id, "non_private_ignored")
                return False
            chat_id = str(event["chat_id"])
            if not self.rate_limiter.allow(platform, chat_id):
                await self._report_security("rate_limited", platform, chat_id)
                await self._send_text(adapter, chat_id, texts.RATE_LIMITED)
                return False
            if event["type"] == "message":
                await self._handle_message(adapter, platform, chat_id, event)
            else:
                await self._handle_callback(adapter, platform, chat_id, event)
            return True
        except ShopApiUnavailable:
            await self._send_text(adapter, str(event["chat_id"]), texts.SERVICE_UNAVAILABLE)
            return True
        except ShopApiError as exc:
            await self._send_text(adapter, str(event["chat_id"]), exc.message_fa)
            return True
        except Exception as exc:  # one bad update must not stop the poller
            self.logger.warning(
                "platform=%s update_id=%s error=%s", platform, update_id, _safe_error(exc)
            )
            return False
        finally:
            self.store.set_last_update_id(platform, update_id)

    @staticmethod
    def _parse_update(update: dict) -> dict | None:
        if isinstance(update.get("message"), dict):
            message = update["message"]
            chat = message.get("chat") or {}
            if chat.get("id") is None:
                return None
            sender = message.get("from") if isinstance(message.get("from"), dict) else {}
            return {
                "type": "message",
                "chat_id": chat.get("id"),
                "chat_type": chat.get("type"),
                "message_id": message.get("message_id"),
                "from_id": sender.get("id"),
                "sender": sender,
                "text": message.get("text") or message.get("caption"),
                "contact": message.get("contact"),
                "photo": message.get("photo"),
                "document": message.get("document"),
            }
        if isinstance(update.get("callback_query"), dict):
            callback = update["callback_query"]
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            if chat.get("id") is None:
                return None
            return {
                "type": "callback",
                "chat_id": chat.get("id"),
                "chat_type": chat.get("type"),
                "message_id": message.get("message_id"),
                "callback_id": callback.get("id"),
                "data": callback.get("data"),
            }
        return None

    # ================= messaging helpers ==================================
    def _markup(self, adapter: PlatformAdapter, rows) -> dict | None:
        if not rows:
            return None
        if adapter.supports_inline_keyboard:
            return inline_keyboard(rows)
        if adapter.supports_reply_keyboard:
            return reply_keyboard(rows)
        return None

    @staticmethod
    def _with_labels(data: dict, rows) -> dict:
        labels = dict(data.get("labels") or {})
        for row in rows or []:
            for label, callback_data in row:
                labels[label] = callback_data
        merged = dict(data)
        merged["labels"] = labels
        return merged

    def _flatten(self, text: str, markup: dict | None, rows) -> str:
        if markup is not None or not rows:
            return text
        flat = [label for row in rows for label, _ in row]
        return text + "\n\n" + "\n".join(f"• {label}" for label in flat)

    async def _send_text(
        self, adapter: PlatformAdapter, chat_id, text: str, reply_markup: dict | None = None
    ):
        try:
            return await adapter.send_text(chat_id, text, reply_markup)
        except BotApiError as exc:
            self.logger.warning("platform=%s send_failed=%s", adapter.platform, exc.method)
            return None

    async def _send_card(self, adapter: PlatformAdapter, chat_id, render, caption: str) -> bool:
        """Send a branded image card as a photo (BOT_IMAGE_CARDS). False = nothing was
        sent (setting off, rendering or upload failed) so the caller sends the text."""
        if not self.settings.bot_image_cards:
            return False
        try:
            png = await asyncio.to_thread(render)
            if not png:
                return False
            await adapter.send_photo_bytes(chat_id, png, caption)
            return True
        except BotApiError as exc:
            self.logger.warning("platform=%s card_send_failed=%s", adapter.platform, exc.method)
        except Exception as exc:  # noqa: BLE001 - a card must never break the chat flow
            self.logger.warning("platform=%s card_failed=%s", adapter.platform, type(exc).__name__)
        return False

    async def _edit_text(
        self,
        adapter: PlatformAdapter,
        chat_id,
        message_id,
        text: str,
        reply_markup: dict | None = None,
    ):
        if message_id is None:
            return await self._send_text(adapter, chat_id, text, reply_markup)
        try:
            return await adapter.edit_text(chat_id, message_id, text, reply_markup)
        except BotApiError as exc:
            self.logger.warning("platform=%s edit_failed=%s", adapter.platform, exc.method)
            return await self._send_text(adapter, chat_id, text, reply_markup)

    async def _answer_callback(
        self, adapter: PlatformAdapter, callback_id, text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        if not callback_id:
            return
        try:
            await adapter.answer_callback(callback_id, text, show_alert)
        except BotApiError as exc:
            self.logger.warning("platform=%s answer_failed=%s", adapter.platform, exc.method)

    async def _send_options(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id,
        text: str,
        rows,
        *,
        state: str | None = None,
        data: dict | None = None,
        edit_message_id=None,
    ):
        current_state, current_data = self.store.get_conversation(platform, chat_id)
        merged = self._with_labels(data if data is not None else current_data, rows)
        self.store.set_conversation(
            platform, chat_id, state if state is not None else current_state, merged
        )
        markup = self._markup(adapter, rows)
        body = self._flatten(text, markup, rows)
        if edit_message_id is not None:
            return await self._edit_text(adapter, chat_id, edit_message_id, body, markup)
        return await self._send_text(adapter, chat_id, body, markup)

    # ================= message routing ====================================
    async def _handle_message(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, event: dict
    ) -> None:
        raw_text = event.get("text") or ""
        if len(raw_text) > self.settings.max_input_len:
            await self._send_text(adapter, chat_id, texts.TEXT_TOO_LONG)
            return
        text = shorten(normalize_digits(raw_text), self.settings.max_input_len)
        photo = event.get("photo")
        document = event.get("document")
        state, data = self.store.get_conversation(platform, chat_id)

        is_admin = self.settings.is_admin_chat(platform, chat_id)
        command = text.split()[0].lower().split("@", 1)[0] if text.startswith("/") else ""

        # commands that work for everyone, in any state
        if command == "/myid":
            await self._send_text(adapter, chat_id, texts.MY_ID.format(chat_id=chat_id))
            return
        if command == "/help":
            await self._send_text(adapter, chat_id, texts.HELP)
            return

        # admin commands and the admin person-code prompt come first
        if command and is_admin:
            if await self._maybe_admin_command(adapter, platform, chat_id, text):
                return
        if state == STATE_ADMIN_PERSON_CODE and is_admin:
            await self._admin_person_code(adapter, platform, chat_id, text, data)
            return

        # /start always restarts, even in the middle of registration.
        # "/start kala_289" is the site's deep link to a product (Bale did not pass
        # the parameter in the 2026-10-11 live test; typing the code is the fallback).
        if command in ("/start", "/menu"):
            self.store.clear_conversation(platform, chat_id)
            args = text.split()[1:]
            model_ref = args[0] if args and looks_like_model_ref(args[0]) else None
            product_code = (
                parse_product_ref(args[0], allow_bare_code=True) if args and not model_ref else None
            )
            await self._customer_entry(
                adapter, platform, chat_id, welcome=command == "/start",
                product_code=product_code, model_ref=model_ref,
            )
            return

        # registration (the user may not exist in shopapi yet): contact only
        if state == STATE_AWAIT_CONTACT or state in LEGACY_REGISTRATION_STATES:
            if not event.get("contact") and looks_like_model_ref(text):
                # a site model code, typed before registering: keep it
                self.store.set_conversation(
                    platform, chat_id, STATE_AWAIT_CONTACT, {**(data or {}), "model": text}
                )
                await self._send_text(
                    adapter, chat_id, texts.MODEL_AFTER_CONTACT,
                    contact_keyboard(texts.BTN_SHARE_CONTACT),
                )
                return
            product_code = None if event.get("contact") else parse_product_ref(text, allow_bare_code=True)
            if product_code is not None:
                # a product code from the site, typed before registering: keep it
                self.store.set_conversation(
                    platform, chat_id, STATE_AWAIT_CONTACT, {**(data or {}), "product": product_code}
                )
                await self._send_text(
                    adapter, chat_id, texts.PRODUCT_AFTER_CONTACT,
                    contact_keyboard(texts.BTN_SHARE_CONTACT),
                )
                return
            await self._registration_contact(adapter, platform, chat_id, event, data)
            return

        # text-only platforms: a typed button label acts as a callback
        label_cb = (data.get("labels") or {}).get(text) if isinstance(data.get("labels"), dict) else None
        if label_cb:
            await self._dispatch_callback(adapter, platform, chat_id, None, None, label_cb)
            return

        user = await self.api.get_user(platform, chat_id)
        status = self.customers.status_of(user)
        if status == STATUS_NEW:
            model_ref = text if looks_like_model_ref(text) else None
            product_code = None if model_ref else parse_product_ref(text, allow_bare_code=True)
            await self._begin_registration(
                adapter, platform, chat_id, product_code=product_code, model_ref=model_ref
            )
            return
        if status == STATUS_REJECTED:
            await self._show_not_approved(adapter, platform, chat_id, status)
            return

        if state == STATE_AWAIT_SEARCH and text:
            self.store.clear_conversation(platform, chat_id)
            await self._show_products(adapter, platform, chat_id, q=text, group=None, page=1)
            return
        if state == STATE_AWAIT_RECEIPT:
            if photo or document:
                await self._save_receipt(adapter, platform, chat_id, photo, document, data)
            else:
                await self._send_text(adapter, chat_id, texts.RECEIPT_EXPECTED_PHOTO)
            return
        if photo or document:
            # a receipt outside the receipt step: let the customer pick the order
            await self._show_orders(adapter, platform, chat_id)
            return

        # "kala_289" or a bare product code (fallback when a deep link lost its parameter)
        product_code = parse_product_ref(text, allow_bare_code=True)
        if product_code is not None:
            await self._show_product_by_code(adapter, platform, chat_id, product_code)
            return

        # a site model (m_<slug>, the copied «name + کد مدل», a slug or a model name)
        if text and await self._show_model(adapter, platform, chat_id, text):
            return

        # any other text: back to the main menu
        await self._show_main_menu(adapter, platform, chat_id, status=status)

    async def _customer_entry(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, *, welcome: bool = True,
        product_code: int | None = None, model_ref: str | None = None,
    ) -> None:
        intro = texts.WELCOME if welcome else None
        status = await self.customers.status(platform, chat_id)
        if status == STATUS_NEW:
            await self._begin_registration(
                adapter, platform, chat_id, intro=intro, product_code=product_code,
                model_ref=model_ref,
            )
            return
        if status == STATUS_REJECTED:
            await self._show_not_approved(adapter, platform, chat_id, status, intro=intro)
            return
        if product_code is not None:
            await self._show_product_by_code(adapter, platform, chat_id, product_code)
            return
        if model_ref and await self._show_model(adapter, platform, chat_id, model_ref):
            return
        await self._show_main_menu(adapter, platform, chat_id, intro=intro, status=status)

    async def _show_not_approved(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, status: str,
        *, intro: str | None = None,
    ) -> None:
        body = texts.REJECTED_USER if status == STATUS_REJECTED else texts.STILL_PENDING
        if intro:
            body = f"{intro}\n\n{body}"
        rows = [[(texts.BTN_SUPPORT, "support"), (texts.BTN_INFO, "info")]]
        await self._send_options(adapter, platform, chat_id, body, rows, state=STATE_NONE, data={})

    # ================= registration (REQUIREMENTS §3) =====================
    #: One report per chat and kind per this many seconds (a flood is one report).
    SECURITY_REPORT_EVERY = 60.0

    async def _report_security(self, kind: str, platform: str, chat_id: str) -> None:
        now = time.monotonic()
        key = (kind, platform, str(chat_id))
        last = self._security_reported.get(key)
        if last is not None and now - last < self.SECURITY_REPORT_EVERY:
            return
        self._security_reported[key] = now
        if len(self._security_reported) > 5000:
            cutoff = now - self.SECURITY_REPORT_EVERY
            self._security_reported = {k: v for k, v in self._security_reported.items() if v > cutoff}
        try:
            await self.api.report_security(kind, platform, chat_id)
        except Exception as exc:  # noqa: BLE001 - reporting must never break the chat
            self.logger.warning("security report failed (%s)", type(exc).__name__)

    async def _begin_registration(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, *,
        intro: str | None = None, product_code: int | None = None,
        model_ref: str | None = None,
    ) -> None:
        """Ask for the contact - only the share-contact button is accepted.
        A deep-linked product or site model is remembered and shown after registration."""
        data = {"product": int(product_code)} if product_code else {}
        if model_ref:
            data = {"model": str(model_ref)}
        self.store.set_conversation(platform, chat_id, STATE_AWAIT_CONTACT, data)
        body = f"{intro}\n\n{texts.ASK_CONTACT}" if intro else texts.ASK_CONTACT
        await self._send_text(adapter, chat_id, body, contact_keyboard(texts.BTN_SHARE_CONTACT))

    async def _registration_contact(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, event: dict, data: dict
    ) -> None:
        verified = self.customers.verify_contact(
            event.get("contact"), event.get("from_id"), event.get("sender")
        )
        if verified.problem is not ContactProblem.NONE:
            if verified.problem is ContactProblem.NOT_OWN:
                await self._report_security("contact_not_own", platform, chat_id)
            message = {
                ContactProblem.NOT_OWN: texts.CONTACT_NOT_OWN,
                ContactProblem.NOT_MOBILE: texts.CONTACT_NOT_MOBILE,
            }.get(verified.problem, texts.CONTACT_BUTTON_ONLY)
            # keep the state (and a deep-linked product) and offer the button again
            self.store.set_conversation(platform, chat_id, STATE_AWAIT_CONTACT, data or {})
            await self._send_text(
                adapter, chat_id, message, contact_keyboard(texts.BTN_SHARE_CONTACT)
            )
            return
        user = await self.customers.register(platform, chat_id, verified)
        status = self.customers.status_of(user if isinstance(user, dict) else None)
        self.store.clear_conversation(platform, chat_id)
        if status == STATUS_REJECTED:
            await self._send_text(adapter, chat_id, texts.REJECTED_USER, remove_keyboard())
            return
        done = texts.REGISTERED_APPROVED if status == STATUS_APPROVED else texts.REGISTERED_PENDING
        await self._send_text(adapter, chat_id, done, remove_keyboard())
        product_code = (data or {}).get("product")
        if isinstance(product_code, int) and product_code > 0:
            await self._show_product_by_code(adapter, platform, chat_id, product_code)
            return
        model_ref = (data or {}).get("model")
        if isinstance(model_ref, str) and model_ref:
            if await self._show_model(adapter, platform, chat_id, model_ref):
                return
        await self._show_main_menu(adapter, platform, chat_id, status=status)

    # ================= customer screens ===================================
    def _main_menu_rows(self, approved: bool = True):
        rows = [
            [(texts.BTN_GROUPS, "groups"), (texts.BTN_SEARCH, "search")],
            [(texts.BTN_CART, "cart"), (texts.BTN_ORDERS, "orders")],
        ]
        if approved:
            # the statement belongs to a verified, linked customer only
            rows.append([(texts.BTN_STATEMENT, "stmt:1")])
        rows.append([(texts.BTN_SUPPORT, "support"), (texts.BTN_INFO, "info")])
        return rows

    async def _show_main_menu(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, *,
        intro: str | None = None, status: str | None = None,
    ) -> None:
        if status is None:
            status = await self.customers.status(platform, chat_id)
        parts = [intro] if intro else []
        if status != STATUS_APPROVED:
            parts.append(texts.STILL_PENDING)
        parts.append(texts.MAIN_MENU)
        await self._send_options(
            adapter, platform, chat_id, "\n\n".join(parts),
            self._main_menu_rows(status == STATUS_APPROVED), state=STATE_NONE, data={},
        )

    async def _sales_state(self) -> dict:
        """Phone sales state from shopapi (price list, Friday, ShopAdmin buttons),
        cached briefly; unknown = open (shopapi still refuses phone orders when
        closed). Accessories and other items are never affected."""
        now = time.monotonic()
        if self._shop_state is not None and now - self._shop_state[0] < SHOP_STATE_TTL:
            return self._shop_state[1]
        try:
            state = await self.api.shop_state()
            state = state if isinstance(state, dict) else {}
        except ShopApiError:
            state = {}
        self._shop_state = (now, state)
        return state

    async def _shop_closed(self) -> bool:
        return bool((await self._sales_state()).get("closed"))

    @staticmethod
    def _has_phones(items) -> bool:
        """Cart lines with a color are phones (priced from the price list)."""
        return any(int(it.get("variant_id") or 0) for it in items or [])

    @staticmethod
    def _sales_closed_text(state: dict) -> str:
        reason = str((state or {}).get("reason") or "")
        if reason == "holiday":
            return texts.SALES_CLOSED_HOLIDAY
        if reason == "weekday_closed":
            return texts.SALES_CLOSED_FRIDAY
        return texts.SALES_CLOSED

    async def _show_static(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str
    ) -> None:
        await self._send_options(
            adapter, platform, chat_id, text, [[(texts.BTN_MENU, "menu")]],
        )

    async def _show_groups(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        groups = await self.catalog.groups()
        if not groups:
            await self._send_options(
                adapter, platform, chat_id, texts.NO_GROUPS, [[(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={},
            )
            return
        rows = [[(str(g.get("name") or ""), f"grp:{g.get('code')}")] for g in groups]
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, texts.GROUPS_TITLE, rows, state=STATE_NONE, data={}
        )

    async def _show_products(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id: str,
        *,
        q: str | None = None,
        group: int | None = None,
        page: int = 1,
        edit_message_id=None,
    ) -> None:
        result = await self.catalog.products(q=q, group=group, page=page)
        page, pages = result.page, result.pages
        # Sales windows close ONLY phones (priced from the Telegram list).
        closed = any(p.has_colors for p in result.items) and await self._shop_closed()

        cache: dict[str, dict] = {}
        rows: list = []
        if not result.items:
            body = texts.NO_PRODUCTS
        else:
            lines = [texts.PRODUCTS_TITLE.format(page=page, pages=pages)]
            for product in result.items:
                code = product.code
                cache[str(code)] = product.as_cache()
                if product.has_colors:
                    lines.append(
                        texts.PRODUCT_LINE_COLORS.format(
                            name=product.name, colors=fmt_num(len(product.colors)),
                            stock=_stock_label(product.in_stock),
                        )
                    )
                else:
                    lines.append(
                        texts.PRODUCT_LINE.format(
                            name=product.name, price=fmt_num(product.price),
                            stock=_stock_label(product.in_stock),
                        )
                    )
                label = shorten(product.name, 40) or str(code)
                rows.append([(label if product.in_stock else f"❌ {label}", f"prod:{code}")])
            nav = []
            group_arg = int(group) if group is not None else 0
            if page > 1:
                nav.append((texts.BTN_PREV, f"pg:{group_arg}:{page - 1}"))
            if page < pages:
                nav.append((texts.BTN_NEXT, f"pg:{group_arg}:{page + 1}"))
            if nav:
                rows.append(nav)
            body = "\n".join(lines)
        if closed:
            # Last prices stay visible; orders are refused until sales reopen.
            body = f"{texts.SHOP_CLOSED_NOTICE}\n\n{body}"
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data={"pcache": cache}, edit_message_id=edit_message_id,
        )

    async def _show_product(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id: str,
        code: int,
        qty: int,
        edit_message_id=None,
    ) -> None:
        _state, data = self.store.get_conversation(platform, chat_id)
        product = (data.get("pcache") or {}).get(str(code))
        if not product:
            await self._send_text(adapter, chat_id, texts.NO_PRODUCTS)
            return
        if product.get("colors") is not None:
            await self._show_colors(adapter, platform, chat_id, code, product, data,
                                    edit_message_id=edit_message_id)
            return
        qty = clamp_qty(qty)
        in_stock = float(product.get("qty") or 0) > 0
        body = texts.PRODUCT_DETAIL.format(
            name=product["name"], price=fmt_num(product["price"]),
            stock=_stock_label(in_stock), qty=fmt_num(qty),
        )
        if not in_stock:
            await self._send_options(
                adapter, platform, chat_id, f"{body}\n{texts.OUT_OF_STOCK}",
                [[(texts.BTN_MENU, "menu")]], state=STATE_NONE, data=data,
                edit_message_id=edit_message_id,
            )
            return
        rows = [
            [
                (texts.BTN_MINUS, f"qty:{code}:{max(1, qty - 1)}"),
                (texts.BTN_PLUS, f"qty:{code}:{qty + 1}"),
            ],
            [(f"{texts.BTN_ADD} ({fmt_num(qty)})", f"add:{code}:{qty}")],
            [(texts.BTN_MENU, "menu")],
        ]
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data=data, edit_message_id=edit_message_id,
        )

    async def _show_product_by_code(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int
    ) -> None:
        """A product opened from a deep link or a typed code (not from a list)."""
        product = await self.catalog.product(code)
        if product is None:
            await self._send_options(
                adapter, platform, chat_id, texts.PRODUCT_NOT_FOUND,
                [[(texts.BTN_SEARCH, "search"), (texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={},
            )
            return
        self.store.set_conversation(
            platform, chat_id, STATE_NONE, {"pcache": {str(product.code): product.as_cache()}}
        )
        await self._show_product(adapter, platform, chat_id, product.code, 1)

    # ---- site models (REQUIREMENTS §9a) -----------------------------------------
    async def _show_model(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str,
    ) -> bool:
        """Resolve a site model reference and show it. Returns False when the
        text is not a model at all (the caller shows the main menu). Never
        guesses: a hidden, unmapped or unknown model -> a polite message + phone."""
        explicit = looks_like_model_ref(text)
        try:
            result = await self.api.resolve_model(text)
        except ShopApiError:
            if not explicit:
                return False
            raise  # the generic "service unavailable" answer
        if not isinstance(result, dict):
            result = {"status": "unknown", "explicit": explicit}
        status = result.get("status")
        model = result.get("model") if isinstance(result.get("model"), dict) else {}
        name = str(model.get("name") or "")
        if status == "found":
            items = [i for i in (result.get("items") or [])
                     if isinstance(i, dict) and str(i.get("kala_code", "")).isdigit()]
            if len(items) == 1:
                await self._show_product_by_code(adapter, platform, chat_id, int(items[0]["kala_code"]))
                return True
            if items:
                rows = [[(shorten(str(i.get("label") or name), 30), f"kp:{int(i['kala_code'])}")]
                        for i in items[:12]]
                rows.append([(texts.BTN_MENU, "menu")])
                await self._send_options(
                    adapter, platform, chat_id, texts.MODEL_PICK_VARIANT.format(name=name),
                    rows, state=STATE_NONE, data={},
                )
                return True
            status = "unavailable"
        if status == "ambiguous":
            options = [o for o in (result.get("options") or [])
                       if isinstance(o, dict) and o.get("slug")][:3]
            if options:
                rows = [[(shorten(str(o.get("name") or o["slug"]), 30), f"mdl:{n}")]
                        for n, o in enumerate(options)]
                rows.append([(texts.BTN_SEARCH, "search"), (texts.BTN_MENU, "menu")])
                await self._send_options(
                    adapter, platform, chat_id, texts.MODEL_AMBIGUOUS, rows,
                    state=STATE_NONE, data={"model_opts": [str(o["slug"]) for o in options]},
                )
                return True
            status = "unknown"
        if status == "unavailable":
            body = texts.MODEL_UNAVAILABLE.format(name=name or "این مدل")
        elif explicit or result.get("explicit"):
            body = texts.MODEL_UNKNOWN
        else:
            return False
        await self._send_options(
            adapter, platform, chat_id, body,
            [[(texts.BTN_SEARCH, "search"), (texts.BTN_SUPPORT, "support")],
             [(texts.BTN_MENU, "menu")]],
            state=STATE_NONE, data={},
        )
        return True

    async def _pick_model_option(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, index: int,
    ) -> None:
        _state, data = self.store.get_conversation(platform, chat_id)
        options = data.get("model_opts") if isinstance(data, dict) else None
        if not isinstance(options, list) or not 0 <= index < len(options):
            await self._show_main_menu(adapter, platform, chat_id)
            return
        await self._show_model(adapter, platform, chat_id, f"m_{options[index]}")

    async def _add_to_cart(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int, qty: int,
        callback_id=None,
    ) -> None:
        _state, data = self.store.get_conversation(platform, chat_id)
        product = (data.get("pcache") or {}).get(str(code))
        if not product or product.get("colors") is not None:
            # a phone is added only with a color (vadd)
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
            return
        if product["qty"] <= 0:
            await self._answer_callback(adapter, callback_id, texts.OUT_OF_STOCK)
            return
        self.cart.add(platform, chat_id, code, product["name"], qty, product["price"])
        await self._answer_callback(adapter, callback_id, texts.QTY_ADDED)
        await self._show_cart(adapter, platform, chat_id)

    # ---- phones: color first, then the price (REQUIREMENTS §4) ----------------
    @staticmethod
    def _color_rows(code: int, colors: list[dict], current: int = 0) -> list:
        rows, row = [], []
        for c in colors:
            if int(c["id"]) == int(current):
                continue
            mark = "🎨" if c.get("available") else "❌"
            row.append((f"{mark} {shorten(str(c.get('name') or ''), 20)}", f"col:{code}:{c['id']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return rows

    async def _show_colors(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int,
        product: dict, data: dict, edit_message_id=None,
    ) -> None:
        """A phone: the colors as buttons; no price until one is picked."""
        data = {k: v for k, v in (data or {}).items() if k != "card_code"}  # new product view
        colors = product.get("colors") or []
        if not colors:
            await self._send_options(
                adapter, platform, chat_id,
                f"«{product['name']}»\n{texts.COLOR_NO_COLORS}",
                [[(texts.BTN_INQUIRY, f"inq:{code}:0")], [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            )
            return
        rows = self._color_rows(code, colors)
        rows.append([(texts.BTN_MENU, "menu")])
        body = texts.CHOOSE_COLOR.format(name=product["name"])
        if await self._shop_closed():
            body = f"{texts.SHOP_CLOSED_NOTICE}\n\n{body}"
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data=data, edit_message_id=edit_message_id,
        )

    async def _show_color(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int,
        color_id: int, qty: int, *, callback_id=None, edit_message_id=None,
        refresh: bool = True,
    ) -> None:
        """The price of one color. Picking another color announces its price."""
        _state, data = self.store.get_conversation(platform, chat_id)
        cache = dict(data.get("pcache") or {})
        product = cache.get(str(code))
        if refresh or not product:
            # Prices are read when the color is picked, never from an old screen.
            fresh = await self.catalog.product(code)
            if fresh is None:
                await self._answer_callback(adapter, callback_id, texts.PRODUCT_NOT_FOUND)
                return
            product = fresh.as_cache()
            cache[str(code)] = product
        colors = product.get("colors") or []
        color = next((c for c in colors if int(c["id"]) == int(color_id)), None)
        if color is None:
            await self._answer_callback(adapter, callback_id, texts.COLOR_GONE)
            data["pcache"] = cache
            await self._show_colors(adapter, platform, chat_id, code, product, data,
                                    edit_message_id=edit_message_id)
            return

        selected = dict(data.get("color_sel") or {})
        previous = int(selected.get(str(code)) or 0)
        selected[str(code)] = int(color_id)
        data = {**data, "pcache": cache, "color_sel": selected}
        name = product["name"]
        others = self._color_rows(code, colors, current=color_id)

        if not color.get("available") or not color.get("price"):
            await self._answer_callback(adapter, callback_id)
            rows = [[(texts.BTN_INQUIRY, f"inq:{code}:{color_id}")], *others,
                    [(texts.BTN_MENU, "menu")]]
            await self._send_options(
                adapter, platform, chat_id,
                texts.COLOR_UNAVAILABLE.format(name=name, color=color["name"]), rows,
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            )
            return

        qty = clamp_qty(qty)
        price = fmt_num(color["price"])
        body = texts.PRODUCT_COLOR_DETAIL.format(
            name=name, color=color["name"], price=price, qty=fmt_num(qty),
        )
        changed = bool(previous) and previous != int(color_id)
        # The image card goes out on the first color pick of a product view only;
        # later switches keep the short "new price" text (no new image).
        if self.settings.bot_image_cards and data.get("card_code") != int(code):
            from .cards import price_card

            sent_card = await self._send_card(
                adapter, chat_id,
                lambda: price_card(
                    shop=texts.SHOP.get("shop_name", ""), name=name, color=color["name"],
                    price=color["price"], in_stock=True,
                    contact={**self._card_contact(), "thanks": ""},
                    currency=texts.SHOP.get("currency", "ریال"),
                ),
                texts.CARD_CAPTION_PRICE.format(name=name, color=color["name"], price=price),
            )
            if sent_card:
                data = {**data, "card_code": int(code)}
        if changed:
            notice = texts.COLOR_CHANGED.format(color=color["name"], price=price)
            body = f"{notice}\n\n{body}"
            await self._answer_callback(adapter, callback_id, notice)
        else:
            await self._answer_callback(adapter, callback_id)
        rows = [
            [
                (texts.BTN_MINUS, f"vqty:{code}:{color_id}:{max(1, qty - 1)}"),
                (texts.BTN_PLUS, f"vqty:{code}:{color_id}:{qty + 1}"),
            ],
            [(f"{texts.BTN_ADD} ({fmt_num(qty)})", f"vadd:{code}:{color_id}:{qty}")],
            *others,
            [(texts.BTN_MENU, "menu")],
        ]
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data=data, edit_message_id=edit_message_id,
        )

    async def _add_color_to_cart(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int,
        color_id: int, qty: int, callback_id=None,
    ) -> None:
        _state, data = self.store.get_conversation(platform, chat_id)
        product = (data.get("pcache") or {}).get(str(code)) or {}
        color = next((c for c in product.get("colors") or []
                      if int(c["id"]) == int(color_id)), None)
        if color is None:
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
            return
        if not color.get("available") or not color.get("price"):
            await self._answer_callback(adapter, callback_id, texts.OUT_OF_STOCK)
            return
        # shopapi prices the order again at checkout (the list may change).
        self.cart.add(platform, chat_id, code, f"{product['name']} — {color['name']}", qty,
                      color["price"], int(color_id))
        await self._answer_callback(adapter, callback_id, texts.QTY_ADDED)
        await self._show_cart(adapter, platform, chat_id)

    async def _send_inquiry(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int,
        color_id: int, callback_id=None,
    ) -> None:
        marker = f"inq:{code}:{color_id}"
        _state, data = self.store.get_conversation(platform, chat_id)
        if marker in (data.get("inquired") or []):
            await self._answer_callback(adapter, callback_id, texts.INQUIRY_SENT)
            return
        try:
            await self.api.create_inquiry(platform, chat_id, code, color_id or None)
        except ShopApiError:
            await self._answer_callback(adapter, callback_id, texts.SERVICE_UNAVAILABLE, True)
            return
        data = {**data, "inquired": [*(data.get("inquired") or [])[-19:], marker]}
        self.store.set_conversation(platform, chat_id, _state, data)
        await self._answer_callback(adapter, callback_id, texts.INQUIRY_SENT)
        await self._send_text(adapter, chat_id, texts.INQUIRY_SENT)

    async def _show_cart(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        items = self.cart.items(platform, chat_id)
        if not items:
            await self._send_options(
                adapter, platform, chat_id, texts.CART_EMPTY, [[(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={},
            )
            return
        lines = [texts.CART_TITLE]
        rows = []
        for item in items:
            code = item["kala_code"]
            color_id = int(item.get("variant_id") or 0)
            lines.append(
                texts.CART_LINE.format(
                    name=item["name"], qty=fmt_num(item["qty"]), price=fmt_num(item["unit_price"])
                )
            )
            if color_id:
                rows.append(
                    [
                        (texts.BTN_MINUS, f"vdec:{code}:{color_id}"),
                        (texts.BTN_PLUS, f"vinc:{code}:{color_id}"),
                        (texts.BTN_REMOVE, f"vdel:{code}:{color_id}"),
                    ]
                )
                continue
            rows.append(
                [
                    (texts.BTN_MINUS, f"cdec:{code}"),
                    (texts.BTN_PLUS, f"cinc:{code}"),
                    (texts.BTN_REMOVE, f"cdel:{code}"),
                ]
            )
        lines.append(texts.CART_TOTAL.format(total=fmt_num(self.cart.total(items))))
        state = await self._sales_state()
        if state.get("closed") and self._has_phones(items):
            # Only phones are closed: the customer may remove them and order the rest.
            lines.append("")
            lines.append(self._sales_closed_text(state))
        else:
            rows.append([(texts.BTN_CHECKOUT, "checkout")])
        rows.append([(texts.BTN_CLEAR_CART, "cclear"), (texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, "\n".join(lines), rows, state=STATE_NONE, data={}
        )

    async def _cart_change(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int, delta: float,
        callback_id=None, color_id: int = 0,
    ) -> None:
        if not self.cart.change(platform, chat_id, code, delta, color_id):
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
            return
        await self._answer_callback(adapter, callback_id)
        await self._show_cart(adapter, platform, chat_id)

    async def _cart_remove(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int, callback_id=None,
        color_id: int = 0,
    ) -> None:
        self.cart.remove(platform, chat_id, code, color_id)
        await self._answer_callback(adapter, callback_id, texts.CART_REMOVED)
        await self._show_cart(adapter, platform, chat_id)

    async def _checkout(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        state = await self._sales_state()
        if state.get("closed") and self._has_phones(self.cart.items(platform, chat_id)):
            await self._send_options(
                adapter, platform, chat_id, self._sales_closed_text(state),
                [[(texts.BTN_MENU, "menu")]],
            )
            return
        try:
            result = await self.orders.checkout(platform, chat_id)
        except ShopApiRejected as exc:
            if exc.status == 409 and "sales are closed" in (exc.detail or "").lower():
                self._shop_state = None          # closed meanwhile: refresh next time
                await self._send_options(
                    adapter, platform, chat_id,
                    self._sales_closed_text(await self._sales_state()),
                    [[(texts.BTN_MENU, "menu")]],
                )
                return
            raise
        if result.empty_cart:
            await self._send_text(adapter, chat_id, texts.CART_EMPTY)
            return
        order = result.order
        if not order:
            await self._send_text(adapter, chat_id, texts.SERVICE_UNAVAILABLE)
            return
        order_id = order.get("id")
        total = fmt_num(order.get("total"))
        parts = [texts.CHECKOUT_OK.format(order_id=order_id, total=total)]
        if order.get("customer_pending"):
            parts.append(texts.PENDING_ORDER_NOTE)
        minutes = state.get("receipt_deadline_minutes") or DEFAULT_RECEIPT_MINUTES
        parts.append(texts.RECEIPT_DEADLINE_NOTE.format(minutes=fmt_num(minutes)))
        parts.append(
            self._payment_text(order_id, total, order.get("payment_instructions"))
        )
        self.store.set_conversation(
            platform, chat_id, STATE_AWAIT_RECEIPT, {"order_id": order_id}
        )
        if self.settings.bot_image_cards and order.get("items"):
            from .cards import pre_invoice_card

            await self._send_card(
                adapter, chat_id,
                lambda: pre_invoice_card(
                    shop=texts.SHOP.get("shop_name", ""), order_id=order_id,
                    items=order.get("items"), total=order.get("total"),
                    payment={"card_number": order.get("payment_card_number"),
                             "sheba": order.get("payment_sheba"),
                             "owner": order.get("payment_owner")},
                    contact=self._card_contact(),
                    currency=texts.SHOP.get("currency", "ریال"),
                    date=order.get("created_at"),
                ),
                texts.CARD_CAPTION_PRE_INVOICE.format(
                    order_id=order_id, total=total, currency=texts.SHOP.get("currency", "ریال")),
            )
        await self._send_options(
            adapter, platform, chat_id, "\n\n".join(parts), [[(texts.BTN_MENU, "menu")]],
        )
        if order_id is not None and not self.store.is_announced("neworder", int(order_id)):
            self.store.mark_announced("neworder", int(order_id), platform, chat_id)
            await self._announce_new_order(order)

    @staticmethod
    def _card_contact() -> dict:
        """Footer of the invoice cards, from the shop texts (messages.fa.json)."""
        return {"address": texts.SHOP.get("shop_address", ""), "phone": texts.SHOP.get("shop_phone", ""),
                "bot_id": texts.SHOP.get("bot_id", ""), "thanks": texts.SHOP.get("invoice_thanks", "")}

    @staticmethod
    def _payment_text(order_id, total: str, api_instructions) -> str:
        """Card details from messages.fa.json; shopapi's BANK_ACCOUNT_TEXT is the
        fallback while the card number there is still a placeholder."""
        card = str(texts.SHOP.get("card_number") or "")
        fallback = str(api_instructions or "").strip()
        if fallback and not any(ch.isdigit() for ch in card):
            return f"{fallback}\n\n" + texts.ASK_RECEIPT.format(order_id=order_id)
        return texts.PAYMENT_INSTRUCTIONS.format(order_id=order_id, total=total)

    async def _save_receipt(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, photo, document,
        data: dict,
    ) -> None:
        order_id = (data or {}).get("order_id")
        if not self.receipt_limiter.allow(platform, chat_id):
            await self._report_security("receipt_flood", platform, chat_id)
            await self._send_text(adapter, chat_id, texts.RECEIPT_RATE_LIMITED)
            return
        result = await self.orders.attach_receipt(
            platform, chat_id, order_id, photo, document, download=adapter.download_file_ref
        )
        if result.outcome is ReceiptOutcome.NO_ORDER:
            await self._send_text(adapter, chat_id, texts.NO_ORDER_FOR_RECEIPT)
            return
        retry = {
            ReceiptOutcome.NOT_A_PHOTO: texts.RECEIPT_EXPECTED_PHOTO,
            ReceiptOutcome.TOO_LARGE: texts.RECEIPT_TOO_LARGE,
            ReceiptOutcome.DOWNLOAD_FAILED: texts.RECEIPT_DOWNLOAD_FAILED,
        }.get(result.outcome)
        if retry:
            await self._send_text(adapter, chat_id, retry)
            return
        if result.outcome in (ReceiptOutcome.NOT_AWAITING, ReceiptOutcome.REJECTED,
                              ReceiptOutcome.TOO_LATE):
            self.store.clear_conversation(platform, chat_id)
            message = {ReceiptOutcome.NOT_AWAITING: texts.ORDER_NOT_AWAITING,
                       ReceiptOutcome.TOO_LATE: texts.RECEIPT_TOO_LATE}.get(
                           result.outcome, result.message_fa)
            await self._send_text(adapter, chat_id, message)
            return
        order = result.order
        self.store.clear_conversation(platform, chat_id)
        await self._send_options(
            adapter, platform, chat_id, texts.RECEIPT_RECEIVED, [[(texts.BTN_MENU, "menu")]],
        )
        # tell the admins right away instead of waiting for the next sweep
        if order is not None and not self.store.is_announced("order", int(order_id)):
            await self._announce_order(order)
            self.store.mark_announced("order", int(order_id), platform, chat_id)

    async def _show_orders(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        orders = await self.orders.list_for(platform, chat_id)
        if not orders:
            await self._send_options(
                adapter, platform, chat_id, texts.ORDERS_EMPTY, [[(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={},
            )
            return
        lines = [texts.ORDERS_TITLE]
        rows = []
        for order in orders:
            lines.append(
                texts.ORDER_LINE.format(
                    order_id=order.get("id"), status=texts.status_fa(self._tracking_status(order)),
                    total=fmt_num(order.get("total")),
                )
            )
            if self.orders.awaits_payment(order):
                rows.append(
                    [(f"{texts.BTN_SEND_RECEIPT} ({order.get('id')})", f"rcpt:{order.get('id')}")]
                )
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, "\n".join(lines), rows, state=STATE_NONE, data={},
        )

    @staticmethod
    def _tracking_status(order: dict) -> str:
        """The furthest step of an order: shipped > invoiced > its status."""
        if order.get("shipped_at"):
            return "shipped"
        if order.get("invoice_state") == "full":
            return "invoiced"
        if order.get("invoice_state") == "partial":
            return "partially_invoiced"
        return str(order.get("status") or "")

    async def _show_statement(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, page: int,
        edit_message_id=None,
    ) -> None:
        """Account statement from the accounting ledger (approved customers only)."""
        page = max(1, int(page))
        size = max(1, int(self.settings.statement_page_size))
        result = await self.api.get_statement(platform, chat_id, page=page, page_size=size)
        menu = [[(texts.BTN_MENU, "menu")]]
        if not isinstance(result, dict):
            await self._send_options(
                adapter, platform, chat_id, texts.STATEMENT_EMPTY, menu, state=STATE_NONE, data={}
            )
            return
        sides = {"debtor": texts.SIDE_DEBTOR, "creditor": texts.SIDE_CREDITOR,
                 "zero": texts.SIDE_ZERO}
        total = int(result.get("total") or 0)
        pages = max(1, (total + size - 1) // size)
        lines = [texts.STATEMENT_TITLE.format(
            page=page, pages=pages, balance=fmt_num(result.get("balance")),
            side=sides.get(str(result.get("side")), ""),
        )]
        items = [it for it in (result.get("items") or []) if isinstance(it, dict)]
        if not items:
            lines.append(texts.STATEMENT_EMPTY)
        for it in items:
            lines.append(texts.STATEMENT_LINE.format(
                date=it.get("date") or "", kind=it.get("kind") or "",
                doc_no=it.get("doc_no") or "", debit=fmt_num(it.get("debit")),
                credit=fmt_num(it.get("credit")), balance=fmt_num(it.get("balance")),
                side=sides.get(str(it.get("side")), ""),
            ))
        rows = []
        nav = []
        if page > 1:
            nav.append((texts.BTN_PREV, f"stmt:{page - 1}"))
        if page < pages:
            nav.append((texts.BTN_NEXT, f"stmt:{page + 1}"))
        if nav:
            rows.append(nav)
        rows += menu
        await self._send_options(
            adapter, platform, chat_id, "\n".join(lines), rows, state=STATE_NONE, data={},
            edit_message_id=edit_message_id,
        )

    async def _ask_receipt(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int
    ) -> None:
        self.store.set_conversation(
            platform, chat_id, STATE_AWAIT_RECEIPT, {"order_id": int(order_id)}
        )
        await self._send_options(
            adapter, platform, chat_id, texts.ASK_RECEIPT.format(order_id=order_id),
            [[(texts.BTN_MENU, "menu")]],
        )

    async def _ask_search(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        self.store.set_conversation(platform, chat_id, STATE_AWAIT_SEARCH, {})
        await self._send_text(
            adapter, chat_id, texts.ASK_SEARCH, reply_markup=self._markup(
                adapter, [[(texts.BTN_MENU, "menu")]]
            )
        )

    # ================= callback routing ===================================
    async def _handle_callback(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, event: dict
    ) -> None:
        await self._dispatch_callback(
            adapter, platform, chat_id,
            event.get("message_id"), event.get("callback_id"), event.get("data"),
        )

    async def _dispatch_callback(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id: str,
        message_id,
        callback_id,
        raw_data,
    ) -> None:
        parsed = parse_callback(raw_data)
        if parsed is None:
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK, True)
            return
        action, args = parsed

        if action in ADMIN_ACTIONS:
            if not self.settings.is_admin_chat(platform, chat_id):
                await self._answer_callback(adapter, callback_id, texts.ADMIN_ONLY, True)
                return
            await self._handle_admin_callback(
                adapter, platform, chat_id, message_id, callback_id, action, args
            )
            return

        if action in PUBLIC_ACTIONS:
            await self._answer_callback(adapter, callback_id)
            text = texts.SHOP_INFO if action == "info" else texts.SUPPORT
            await self._show_static(adapter, platform, chat_id, text)
            return

        user = await self.api.get_user(platform, chat_id)
        status = self.customers.status_of(user)
        if status == STATUS_NEW:
            await self._answer_callback(adapter, callback_id)
            await self._begin_registration(adapter, platform, chat_id)
            return
        if status == STATUS_REJECTED:
            await self._answer_callback(adapter, callback_id, texts.REJECTED_USER)
            return
        # customers awaiting approval may browse and order (within shopapi's
        # limits); only the statement needs an approved, linked account
        if action == "stmt" and status != STATUS_APPROVED:
            await self._answer_callback(adapter, callback_id, texts.STATEMENT_ONLY_APPROVED, True)
            return

        if action == "menu":
            await self._answer_callback(adapter, callback_id)
            await self._show_main_menu(adapter, platform, chat_id, status=status)
        elif action == "groups":
            await self._answer_callback(adapter, callback_id)
            await self._show_groups(adapter, platform, chat_id)
        elif action == "grp":
            await self._answer_callback(adapter, callback_id)
            await self._show_products(
                adapter, platform, chat_id, group=args[0], page=1,
                edit_message_id=message_id,
            )
        elif action == "pg":
            await self._answer_callback(adapter, callback_id)
            await self._show_products(
                adapter, platform, chat_id, group=args[0] or None, page=args[1],
                edit_message_id=message_id,
            )
        elif action == "prod":
            await self._answer_callback(adapter, callback_id)
            await self._show_product(
                adapter, platform, chat_id, args[0], 1, edit_message_id=message_id
            )
        elif action == "qty":
            await self._answer_callback(adapter, callback_id)
            await self._show_product(
                adapter, platform, chat_id, args[0], args[1], edit_message_id=message_id
            )
        elif action == "add":
            await self._add_to_cart(
                adapter, platform, chat_id, args[0], args[1], callback_id
            )
        elif action == "col":
            await self._show_color(
                adapter, platform, chat_id, args[0], args[1], 1,
                callback_id=callback_id, edit_message_id=message_id,
            )
        elif action == "vqty":
            await self._show_color(
                adapter, platform, chat_id, args[0], args[1], args[2],
                callback_id=callback_id, edit_message_id=message_id, refresh=False,
            )
        elif action == "vadd":
            await self._add_color_to_cart(
                adapter, platform, chat_id, args[0], args[1], args[2], callback_id
            )
        elif action == "vinc":
            await self._cart_change(adapter, platform, chat_id, args[0], 1, callback_id, args[1])
        elif action == "vdec":
            await self._cart_change(adapter, platform, chat_id, args[0], -1, callback_id, args[1])
        elif action == "vdel":
            await self._cart_remove(adapter, platform, chat_id, args[0], callback_id, args[1])
        elif action == "inq":
            await self._send_inquiry(adapter, platform, chat_id, args[0], args[1], callback_id)
        elif action == "kp":
            await self._answer_callback(adapter, callback_id)
            await self._show_product_by_code(adapter, platform, chat_id, args[0])
        elif action == "mdl":
            await self._answer_callback(adapter, callback_id)
            await self._pick_model_option(adapter, platform, chat_id, args[0])
        elif action == "cart":
            await self._answer_callback(adapter, callback_id)
            await self._show_cart(adapter, platform, chat_id)
        elif action == "cinc":
            await self._cart_change(adapter, platform, chat_id, args[0], 1, callback_id)
        elif action == "cdec":
            await self._cart_change(adapter, platform, chat_id, args[0], -1, callback_id)
        elif action == "cdel":
            await self._cart_remove(adapter, platform, chat_id, args[0], callback_id)
        elif action == "cclear":
            self.store.cart_clear(platform, chat_id)
            await self._answer_callback(adapter, callback_id)
            await self._show_cart(adapter, platform, chat_id)
        elif action == "checkout":
            await self._answer_callback(adapter, callback_id)
            await self._checkout(adapter, platform, chat_id)
        elif action == "orders":
            await self._answer_callback(adapter, callback_id)
            await self._show_orders(adapter, platform, chat_id)
        elif action == "rcpt":
            await self._answer_callback(adapter, callback_id)
            await self._ask_receipt(adapter, platform, chat_id, args[0])
        elif action == "search":
            await self._answer_callback(adapter, callback_id)
            await self._ask_search(adapter, platform, chat_id)
        elif action == "stmt":
            await self._answer_callback(adapter, callback_id)
            await self._show_statement(
                adapter, platform, chat_id, args[0], edit_message_id=message_id
            )
        else:  # pragma: no cover - parse_callback already restricts actions
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)

    # ================= admin flow =========================================
    async def admin_sweep(self) -> dict:
        """Announce new pending users and new receipts to the admin chats, and
        tell customers about decisions (made here or in ShopAdmin)."""
        announced = {"users": 0, "orders": 0, "notified": 0}
        try:
            announced["notified"] = await self.notify_customers_from_events()
        except ShopApiError:
            pass
        platforms = tuple(self.adapters.keys())
        if not self.settings.admin_targets(platforms):
            return announced

        try:
            users = await self.api.admin_list_users("pending")
        except ShopApiError:
            users = []
        for user in users:
            user_id = user.get("id") if isinstance(user, dict) else None
            if user_id is None or self.store.is_announced("user", int(user_id)):
                continue
            await self._announce_user(user)
            self.store.mark_announced(
                "user", int(user_id), str(user.get("platform") or ""), user.get("chat_id") or ""
            )
            announced["users"] += 1

        try:
            orders = await self.api.admin_list_orders("receipt_uploaded")
        except ShopApiError:
            orders = []
        for order in orders:
            order_id = order.get("id") if isinstance(order, dict) else None
            if order_id is None or self.store.is_announced("order", int(order_id)):
                continue
            await self._announce_order(order)
            receipt = self.store.get_receipt(int(order_id)) or {}
            self.store.mark_announced(
                "order", int(order_id), str(receipt.get("platform") or ""),
                receipt.get("chat_id") or "",
            )
            announced["orders"] += 1

        return announced

    async def _broadcast_admin(
        self, text: str, rows, photo_ref: str | None = None, photo_platform: str | None = None
    ) -> None:
        platforms = tuple(self.adapters.keys())
        for platform, chat_id in self.settings.admin_targets(platforms):
            adapter = self.adapters.get(platform)
            if adapter is None:
                continue
            markup = self._markup(adapter, rows)
            if rows:
                current_state, current_data = self.store.get_conversation(platform, chat_id)
                self.store.set_conversation(
                    platform, chat_id, current_state, self._with_labels(current_data, rows)
                )
            body = self._flatten(text, markup, rows)
            sent = None
            if photo_ref and (photo_platform is None or photo_platform == platform):
                try:
                    sent = await adapter.send_photo(
                        chat_id, photo_ref, caption=body, reply_markup=markup
                    )
                except BotApiError:
                    sent = None
            if sent is None:
                await self._send_text(adapter, chat_id, body, markup)

    async def _announce_user(self, user: dict) -> None:
        user_id = user.get("id")
        phone = str(user.get("phone") or "")
        body = texts.NEW_USER_NOTICE.format(
            platform=user.get("platform") or "",
            name=user.get("name") or "",
            phone=mask_phone(phone),
        )
        rows = []
        match = None
        if phone:
            try:
                match = await self.api.admin_match_person(phone)
            except ShopApiError:
                match = None
        if isinstance(match, dict) and match.get("code") is not None:
            body += "\n" + texts.NEW_USER_SUGGESTION.format(person_code=match["code"])
            rows.append(
                [
                    (
                        f"{texts.BTN_USE_SUGGESTED} ({match['code']})",
                        f"adsug:{user_id}:{match['code']}",
                    )
                ]
            )
        rows.append(
            [(texts.BTN_APPROVE, f"addu:{user_id}"), (texts.BTN_REJECT, f"adru:{user_id}")]
        )
        await self._broadcast_admin(body, rows)

    async def notify_customers_from_events(self) -> int:
        """Follow shopapi's /admin/events feed and message the customer once per
        decision. The first run only records the current position (no replay)."""
        raw = self.store.get_value(EVENT_CURSOR_KEY)
        if raw is None:
            feed = await self.api.admin_events(None)
            self.store.set_value(EVENT_CURSOR_KEY, str(int(feed.get("last_id") or 0)))
            return 0
        feed = await self.api.admin_events(int(raw))
        sent = 0
        for event in feed.get("items") or []:
            if not isinstance(event, dict):
                continue
            kind = str(event.get("kind") or "")
            ref_id = event.get("ref_id")
            if kind in CUSTOMER_EVENT_KINDS and ref_id is not None:
                if await self._notify_decision(kind, int(ref_id)):
                    sent += 1
            elif kind in OWNER_EVENT_TEXTS:
                if await self._notify_owner(kind, ref_id, int(event.get("id") or 0)):
                    sent += 1
        self.store.set_value(EVENT_CURSOR_KEY, str(int(feed.get("last_id") or raw)))
        return sent

    async def _notify_owner(self, kind: str, ref_id, event_id: int) -> bool:
        """Price-list / proxy / inquiry alerts to the admin chats, once each."""
        marker = f"owner:{kind}"
        key = int(ref_id) if ref_id is not None else event_id
        if self.store.is_announced(marker, key):
            return False
        self.store.mark_announced(marker, key, "", "")
        if not self.settings.admin_targets(tuple(self.adapters.keys())):
            return False
        template = getattr(texts, OWNER_EVENT_TEXTS[kind])
        if kind == "price_inquiry":
            try:
                inquiry = await self.api.admin_get_inquiry(int(ref_id))
            except ShopApiError:
                inquiry = None
            inquiry = inquiry if isinstance(inquiry, dict) else {}
            text = template.format(
                product=inquiry.get("product_name") or "-",
                color=inquiry.get("color") or "-",
                name=inquiry.get("customer_name") or "-",
            )
        else:
            text = template.format(list_id=ref_id if ref_id is not None else "-")
        await self._broadcast_admin(text, [])
        return True

    async def _notify_decision(self, kind: str, ref_id: int) -> bool:
        """Message the customer about one decision, at most once."""
        marker = f"notified:{kind}"
        if self.store.is_announced(marker, ref_id):
            return False
        if kind.startswith("customer_"):
            target = self.store.get_notice("user", ref_id) or await self._find_user_chat(ref_id)
            text = texts.APPROVED_BY_ADMIN if kind == "customer_approved" else texts.REJECTED_BY_ADMIN
        else:
            target = (
                self.store.get_receipt(ref_id)
                or self.store.get_notice("order", ref_id)
                or self.store.get_notice("neworder", ref_id)
                or await self._find_order_chat(ref_id)
            )
            text = getattr(texts, ORDER_EVENT_TEXTS[kind]).format(order_id=ref_id)
        self.store.mark_announced(
            marker, ref_id, str((target or {}).get("platform") or ""),
            (target or {}).get("chat_id") or "",
        )
        if not target:
            return False
        if kind in INVOICE_EVENT_KINDS and await self._send_invoice_card(kind, ref_id, target, text):
            return True
        await self._notify_customer(target, text)
        return True

    async def _send_invoice_card(self, kind: str, order_id: int, target: dict, caption: str) -> bool:
        """The invoice image (caption = the usual invoiced message). The lines and
        prices are the order's own: see PROGRESS.md for the grants a true invoice needs."""
        if not self.settings.bot_image_cards:
            return False
        adapter = self.adapters.get(str(target.get("platform") or ""))
        chat_id = target.get("chat_id")
        if adapter is None or not chat_id:
            return False
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            return False
        if not isinstance(order, dict) or not order.get("items"):
            return False
        from .cards import final_invoice_card

        return await self._send_card(
            adapter, chat_id,
            lambda: final_invoice_card(
                shop=texts.SHOP.get("shop_name", ""), order_id=order_id, items=order.get("items"),
                total=order.get("total"), partial=kind == "order_partially_invoiced",
                invoice_numbers=order.get("invoice_numbers"), contact=self._card_contact(),
                currency=texts.SHOP.get("currency", "ریال"),
                date=order.get("invoiced_at"),
            ),
            caption,
        )

    async def _find_user_chat(self, user_id: int) -> dict | None:
        try:
            user = await self.api.admin_get_user(int(user_id))
        except ShopApiError:
            return None
        if isinstance(user, dict) and user.get("chat_id"):
            return {"platform": user.get("platform"), "chat_id": user.get("chat_id")}
        return None

    async def _find_order_chat(self, order_id: int) -> dict | None:
        """The customer's chat for an order the bot has no notice of (e.g. an
        order invoiced long after the bot's own records)."""
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            return None
        user_id = order.get("user_id") if isinstance(order, dict) else None
        return await self._find_user_chat(int(user_id)) if user_id else None

    def _items_text(self, order: dict) -> str:
        items = [it for it in (order.get("items") or []) if isinstance(it, dict)]
        return "\n".join(f"• {it.get('name')} × {fmt_num(it.get('qty'))}" for it in items) or "—"

    async def _announce_new_order(self, order: dict) -> None:
        order_id = order.get("id")
        body = texts.NEW_ORDER_NOTICE.format(
            order_id=order_id, total=fmt_num(order.get("total")), items=self._items_text(order)
        )
        await self._broadcast_admin(body, [[(texts.BTN_ORDER_STATUS, f"adst:{order_id}")]])

    async def _announce_order(self, order: dict) -> None:
        order_id = order.get("id")
        body = texts.NEW_RECEIPT_NOTICE.format(
            order_id=order_id, total=fmt_num(order.get("total")), items=self._items_text(order)
        )
        rows = [
            [
                (texts.BTN_PAY_APPROVE, f"adap:{order_id}"),
                (texts.BTN_PAY_REJECT, f"adrp:{order_id}"),
            ]
        ]
        receipt = self.store.get_receipt(int(order_id)) if order_id is not None else None
        photo_ref = (receipt or {}).get("file_ref")
        photo_platform = (receipt or {}).get("platform")
        await self._broadcast_admin(body, rows, photo_ref=photo_ref, photo_platform=photo_platform)

    async def _maybe_admin_command(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str
    ) -> bool:
        parts = text.split()
        if not parts:
            return False
        command = parts[0].lower().lstrip("/")
        if command == "pending":
            await self._admin_pending(adapter, platform, chat_id)
            return True
        if command == "order" and len(parts) >= 2:
            order_id = parse_int(parts[1], minimum=1)
            if order_id is None:
                await self._send_text(adapter, chat_id, texts.BAD_INPUT)
                return True
            await self._admin_order_status(adapter, platform, chat_id, order_id)
            return True
        return False

    async def _admin_pending(
        self, adapter: PlatformAdapter, platform: str, chat_id: str
    ) -> None:
        try:
            users = await self.api.admin_list_users("pending")
            orders = await self.api.admin_list_orders("receipt_uploaded")
        except ShopApiError as exc:
            await self._send_text(adapter, chat_id, format_admin_error(exc))
            return
        lines = [texts.ADMIN_PENDING_SUMMARY.format(users=len(users), orders=len(orders))]
        if not users and not orders:
            lines.append(texts.NOTHING_PENDING)
        for user in users:
            lines.append(f"• کاربر {user.get('id')} — {user.get('platform')}")
        for order in orders:
            lines.append(f"• سفارش {order.get('id')}")
        await self._send_text(adapter, chat_id, "\n".join(lines))

    async def _admin_order_status(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int
    ) -> None:
        order = await self.api.admin_get_order(order_id)
        if not order:
            await self._send_text(adapter, chat_id, texts.ADMIN_UNKNOWN_ORDER.format(order_id=order_id))
            return
        await self._send_text(
            adapter,
            chat_id,
            texts.ADMIN_ORDER_STATUS.format(
                order_id=order.get("id"), status=texts.status_fa(order.get("status")),
                total=fmt_num(order.get("total")),
            ),
        )

    async def _admin_person_code(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str, data: dict
    ) -> None:
        user_id = (data or {}).get("user_id")
        code = parse_int(text, minimum=1, maximum=MAX_CALLBACK_ARG)
        if user_id is None or code is None:
            await self._send_text(adapter, chat_id, texts.ADMIN_ASK_PERSON_CODE)
            return
        await self._approve_user(adapter, platform, chat_id, int(user_id), code, None)

    async def _handle_admin_callback(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id: str,
        message_id,
        callback_id,
        action: str,
        args: list[int],
    ) -> None:
        if action == "addu":
            self.store.set_conversation(
                platform, chat_id, STATE_ADMIN_PERSON_CODE, {"user_id": args[0]}
            )
            await self._answer_callback(adapter, callback_id)
            await self._send_text(adapter, chat_id, texts.ADMIN_ASK_PERSON_CODE)
            return
        if action == "adsug":
            await self._approve_user(adapter, platform, chat_id, args[0], args[1], callback_id)
            return
        if action == "adru":
            await self._reject_user(adapter, platform, chat_id, args[0], callback_id)
            return
        if action == "adap":
            await self._approve_payment(adapter, platform, chat_id, args[0], callback_id)
            return
        if action == "adrp":
            await self._reject_payment(adapter, platform, chat_id, args[0], callback_id)
            return
        if action == "adst":
            await self._answer_callback(adapter, callback_id)
            await self._admin_order_status(adapter, platform, chat_id, args[0])
            return

    async def _notify_customer(self, notice: dict | None, text: str) -> None:
        if not notice:
            return
        adapter = self.adapters.get(str(notice.get("platform") or ""))
        chat_id = notice.get("chat_id")
        if adapter is None or not chat_id:
            return
        await self._send_text(adapter, chat_id, text)

    async def _notify_once(self, kind: str, ref_id: int, notice: dict | None, text: str) -> None:
        marker = f"notified:{kind}"
        if self.store.is_announced(marker, int(ref_id)):
            return
        self.store.mark_announced(
            marker, int(ref_id), str((notice or {}).get("platform") or ""),
            (notice or {}).get("chat_id") or "",
        )
        await self._notify_customer(notice, text)

    async def _approve_user(
        self,
        adapter: PlatformAdapter,
        platform: str,
        chat_id: str,
        user_id: int,
        person_code: int,
        callback_id,
    ) -> None:
        notice = self.store.get_notice("user", int(user_id))
        try:
            await self.api.admin_approve_user(int(user_id), int(person_code))
        except ShopApiError as exc:
            message = format_admin_error(exc)
            await self._answer_callback(adapter, callback_id, message, True)
            if not callback_id:
                await self._send_text(adapter, chat_id, message)
            return
        self.store.clear_conversation(platform, chat_id)
        await self._answer_callback(adapter, callback_id, texts.ADMIN_USER_APPROVED)
        await self._send_text(adapter, chat_id, texts.ADMIN_USER_APPROVED)
        await self._notify_once("customer_approved", user_id, notice, texts.APPROVED_BY_ADMIN)

    async def _reject_user(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, user_id: int, callback_id
    ) -> None:
        notice = self.store.get_notice("user", int(user_id))
        try:
            await self.api.admin_reject_user(int(user_id))
        except ShopApiError as exc:
            message = format_admin_error(exc)
            await self._answer_callback(adapter, callback_id, message, True)
            return
        await self._answer_callback(adapter, callback_id, texts.ADMIN_USER_REJECTED)
        await self._send_text(adapter, chat_id, texts.ADMIN_USER_REJECTED)
        await self._notify_once("customer_rejected", user_id, notice, texts.REJECTED_BY_ADMIN)

    async def _approve_payment(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int, callback_id
    ) -> None:
        notice = self.store.get_receipt(int(order_id)) or self.store.get_notice("order", int(order_id))
        try:
            order = await self.api.admin_approve_payment(int(order_id))
        except ShopApiError as exc:
            message = format_admin_error(exc)
            await self._answer_callback(adapter, callback_id, message, True)
            await self._send_text(adapter, chat_id, message)
            return
        # With ACCOUNTING_WRITE_ENABLED=false shopapi only rehearses the write
        # (dry-run + ROLLBACK): the order is not "written" and the admin is told so.
        written = isinstance(order, dict) and order.get("status") == "written"
        message = texts.ADMIN_PAYMENT_APPROVED if written else texts.ADMIN_PAYMENT_APPROVED_DRY_RUN
        await self._answer_callback(adapter, callback_id, message)
        await self._send_text(adapter, chat_id, message)
        await self._notify_once(
            "payment_approved", order_id, notice, texts.PAYMENT_APPROVED.format(order_id=order_id)
        )

    async def _reject_payment(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int, callback_id
    ) -> None:
        notice = self.store.get_receipt(int(order_id)) or self.store.get_notice("order", int(order_id))
        try:
            await self.api.admin_reject_payment(int(order_id))
        except ShopApiError as exc:
            message = format_admin_error(exc)
            await self._answer_callback(adapter, callback_id, message, True)
            await self._send_text(adapter, chat_id, message)
            return
        await self._answer_callback(adapter, callback_id, texts.ADMIN_PAYMENT_REJECTED)
        await self._send_text(adapter, chat_id, texts.ADMIN_PAYMENT_REJECTED)
        await self._notify_once(
            "payment_rejected", order_id, notice, texts.PAYMENT_REJECTED.format(order_id=order_id)
        )
