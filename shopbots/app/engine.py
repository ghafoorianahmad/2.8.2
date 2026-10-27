"""Shared conversation engine: routing, customer flow, admin flow.

The engine is platform agnostic — it only talks to a PlatformAdapter and to the
shop core (`app/core`: catalog, cart, orders, customers), which talks to shopapi.
The engine owns states, texts and keyboards; the core owns the shop rules.
Prices always come from shopapi; a user can never supply one.

Privacy: this module never logs names, phones or message text. Log lines are
produced only by `utils.log_event` (platform, update id, event type).
"""
from __future__ import annotations

import json
import logging
import re
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
    looks_like_cart_ref,
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
from .ratelimit import RateLimiter, WarnOnce
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
#: v2.6.0: «درخواست کالای ناموجود» - waiting for the item's name
STATE_AWAIT_ITEM_REQUEST = "await_item_request"
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
    # v2.6.2: the part / region of the picked color (product, variant)
    "prt": 2,
    # v2.6.2: the customer's own order cancel: ask / confirm
    "ocx": 1,
    "ocy": 1,
    # site models (REQUIREMENTS §9a): a product of the model / one of the options
    "kp": 1,
    "mdl": 1,
    # v2.6.0: unavailable item request: start / submit the typed text / a product
    "ireq": 0,
    "ireqt": 0,
    "ireqk": 1,
    # v2.6.1: «استعلام قیمت» of a price-on-inquiry product
    "pinq": 1,
    # v2.8.0: smart phone search: model / model+color / one row; «درخواست خرید» of a
    # search row or of a product color; «وقتی فروش باز شد خبرم کن»
    "psm": 1,
    "psc": 2,
    "psr": 1,
    "pbr": 1,
    "pbv": 2,
    # v2.9.2: the customer's answer to a price offered by staff (staff message id)
    "pok": 1,
    "pno": 1,
    "snot": 0,
    "psl": 0,
    # v2.8.3: «مرحلهٔ قبل» (one screen back, the earlier choices kept)
    "back": 0,
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
        # v2.9.3: cancelled in ShopAdmin: the customer stopped waiting for nothing
        "order_cancelled_by_staff",
    }
)
#: v2.9.3: an order that ended this way: its old buttons in the chat stop working
ORDER_ENDED_KINDS = frozenset({"order_auto_cancelled", "order_cancelled_by_staff"})
#: v2.9.3: orders that can no longer be paid or cancelled
CLOSED_ORDER_STATUSES = frozenset({"cancelled", "expired", "rejected"})
#: v2.9.3: how many messages with buttons are remembered per order
ORDER_MESSAGES_KEEP = 6
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
    # v2.9.3: cancelled by staff in ShopAdmin (with the short reason, when given)
    "order_cancelled_by_staff": "ORDER_CANCELLED_BY_STAFF",
}
#: shopapi event kinds that mean "tell the owner" (admin chats) -> text key.
OWNER_EVENT_TEXTS = {
    "pricelist_held": "PRICELIST_HELD_NOTICE",
    "pricelist_failed": "PRICELIST_FAILED_NOTICE",
    "proxies_all_dead": "PROXIES_DEAD_NOTICE",
    "telegram_login_required": "TG_LOGIN_NOTICE",
    "telegram_unreachable": "TG_UNREACHABLE_NOTICE",
    # v2.9.0: a price-list PDF of the channel could not be downloaded
    "telegram_pricelist_error": "TG_PRICELIST_ERROR_NOTICE",
    # v2.9.1: a suspicious price (more than 10 %) waits for a manager; correction
    # lines that match no model; the distributor closed sales in the channel
    "price_held": "PRICE_HELD_NOTICE",
    "price_correction_unmatched": "PRICE_CORRECTION_UNMATCHED_NOTICE",
    "sales_closed_channel": "SALES_CLOSED_CHANNEL_NOTICE",
    "price_inquiry": "INQUIRY_NOTICE",
    # v2.5.0: never deleted in the accounting DB; the owner decides there
    "accounting_duplicate_order": "DUPLICATE_ORDER_NOTICE",
    "order_timeout_written": "TIMEOUT_WRITTEN_NOTICE",
    # v2.6.1: item requests are announced ONLY inside ShopAdmin (no admin chat).
}
#: v2.9.1: owner notices that are not problems (only with ADMIN_CHAT_ORDER_NOTICES)
OWNER_INFO_KINDS = frozenset({"price_inquiry"})
#: v2.6.1: a staff reply to an item request, delivered here to the customer.
ITEM_REQUEST_MESSAGE_EVENT = "item_request_message"
#: v2.8.0: staff confirmed the stock of a «درخواست خرید»: the customer pays now.
PURCHASE_ORDER_EVENT = "purchase_order_created"
#: v2.8.2: staff sent the payment details of an order («ارسال اطلاعات پرداخت»).
PAYMENT_INFO_EVENT = "order_payment_info"
#: v2.8.2: the payment details lines, in this order (empty ones are left out).
PAYMENT_INFO_LINES = (("card_number", "PAYMENT_INFO_CARD"),
                      ("account_number", "PAYMENT_INFO_ACCOUNT"),
                      ("sheba", "PAYMENT_INFO_SHEBA"), ("holder", "PAYMENT_INFO_HOLDER"),
                      ("bank", "PAYMENT_INFO_BANK"), ("note", "PAYMENT_INFO_NOTE"))
#: v2.8.3: numbers that must read left to right in the customer's message.
LTR_PAYMENT_FIELDS = frozenset({"card_number", "account_number", "sheba"})
#: v2.8.0: sales state the sweep saw last ("1" open / "0" closed) for the watchers.
SALES_SEEN_KEY = "sales_last_open"
def _lowest(prices) -> float:
    """The lowest real price (0 when every one waits for a manager)."""
    values = [p for p in prices if p]
    return min(values) if values else 0.0


def _price_or_ask(price) -> str:
    return fmt_num(price) if price else texts.PRICE_ON_REQUEST


#: shopapi detail of a refused cart item: "Product <code> <reason>".
_REFUSED_ITEM = re.compile(r"^Product (\d+) (.+)$")
REFUSED_ITEM_TEXTS = {
    "is not available for sale": "CART_ITEM_NOT_FOR_SALE",
    "is price on inquiry": "CART_ITEM_ON_INQUIRY",
    "is not in the current price list": "CART_ITEM_NOT_IN_LIST",
    # v2.8.0: a phone without stock in «سازه حساب»
    "has no stock; purchase request": "CART_ITEM_NO_STOCK",
    # v2.9.2: the list price waits for a manager (price guard)
    "price waits for approval; purchase request": "CART_ITEM_PRICE_HELD",
}
SHOP_STATE_TTL = 30.0
#: Receipt deadline when shopapi does not say (minutes).
DEFAULT_RECEIPT_MINUTES = 30
EVENT_CURSOR_KEY = "shopapi_event_cursor"
MAX_CALLBACK_LEN = 64
MAX_CALLBACK_ARG = 1_000_000_000
#: v2.8.3: «مرحلهٔ قبل». Every customer screen says which screen it is (``id``) and
#: how to draw it again (``cb``: a callback, or an internal ``@…`` step); the
#: chat's screens are kept (with the conversation data of each) in the bot's kv
#: store, so going back restores the earlier choices exactly.
NAV_ROOT = "__root__"
NAV_MAX = 15
#: Unicode LEFT-TO-RIGHT MARK: card / account / Sheba numbers keep their order
#: inside a right-to-left message (v2.8.3: they arrived reversed).
LRM = "\u200e"


def ltr(value: str) -> str:
    """A number like 6037-1234-5678-1234 shown left to right in any client: an
    LRM around it and around every separator (each separator is then between
    two left-to-right marks and cannot flip the groups)."""
    out = []
    for ch in str(value):
        out.append(f"{LRM}{ch}{LRM}" if not ch.isalnum() else ch)
    return f"{LRM}{''.join(out)}{LRM}"


def variant_label(color: dict) -> str:
    """«Silver — CHA»: the color, then the part / region when there is one."""
    return " — ".join(p for p in (str(color.get("name") or "").strip(),
                                  str(color.get("part") or "").strip()) if p)


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
        #: v2.6.0: button taps have their own, much higher limit (quick +/− taps are
        #: normal use); the warning goes out once per window; /start is never limited.
        self.callback_limiter = RateLimiter(
            settings.rate_limit_callbacks, settings.rate_limit_window
        )
        self.rate_warner = WarnOnce(settings.rate_limit_window)
        self.logger = logger or logging.getLogger("shopbots.engine")
        # channel-independent shop logic (app/core)
        self.catalog = CatalogService(api, page_size=settings.product_page_size)
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
            if not self._allowed(platform, chat_id, event):
                await self._report_security("rate_limited", platform, chat_id)
                if event["type"] == "callback":
                    # stop the button's spinner; no alert per tap
                    await self._answer_callback(adapter, event.get("callback_id"))
                if self.rate_warner.should_warn(platform, chat_id):
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

    def _allowed(self, platform: str, chat_id: str, event: dict) -> bool:
        """Rate limits (v2.6.0): /start always passes (a customer who tapped too
        fast must be able to start over); button taps and messages are counted
        separately, taps with a much higher limit."""
        if event["type"] == "callback":
            return self.callback_limiter.allow(platform, chat_id)
        text = str(event.get("text") or "").strip().lower()
        if text.split("@", 1)[0].split(" ", 1)[0] == "/start":
            return True
        return self.rate_limiter.allow(platform, chat_id)

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
        screen=None,
    ):
        current_state, current_data = self.store.get_conversation(platform, chat_id)
        new_state = state if state is not None else current_state
        new_data = data if data is not None else current_data
        rows = self._nav_rows(platform, chat_id, rows, screen, new_state, new_data)
        merged = self._with_labels(new_data, rows)
        self.store.set_conversation(platform, chat_id, new_state, merged)
        markup = self._markup(adapter, rows)
        body = self._flatten(text, markup, rows)
        if edit_message_id is not None:
            return await self._edit_text(adapter, chat_id, edit_message_id, body, markup)
        return await self._send_text(adapter, chat_id, body, markup)

    # ================= «مرحلهٔ قبل» (v2.8.3) ===================================
    @staticmethod
    def _nav_key(platform: str, chat_id) -> str:
        return f"nav:{platform}:{chat_id}"

    def _nav_load(self, platform: str, chat_id) -> list[dict]:
        try:
            raw = json.loads(self.store.get_value(self._nav_key(platform, chat_id)) or "[]")
        except (TypeError, ValueError):
            return []
        return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []

    def _nav_save(self, platform: str, chat_id, nav: list[dict]) -> None:
        self.store.set_value(self._nav_key(platform, chat_id),
                             json.dumps(nav[-NAV_MAX:], ensure_ascii=False))

    def _nav_rows(self, platform: str, chat_id, rows, screen, state: str, data: dict):
        """Record this screen and, when there is an earlier one, put «مرحلهٔ قبل»
        next to «منوی اصلی» (screens without «منوی اصلی» are left alone).
        ``screen``: NAV_ROOT (the main menu: history starts again), ``(id, cb)``
        or ``(id, cb, drop_prefix, keep_id)`` (earlier screens starting with
        ``drop_prefix`` are forgotten, except ``keep_id``), or None (a one-off
        answer, e.g. «ثبت شد»)."""
        has_menu = any(cb == "menu" for row in rows or [] for _label, cb in row)
        if screen == NAV_ROOT:
            self._nav_save(platform, chat_id, [{"id": NAV_ROOT, "cb": "menu"}])
            return rows
        if not has_menu:
            return rows
        nav = self._nav_load(platform, chat_id)
        if not nav or nav[0].get("id") != NAV_ROOT:
            # every chat starts at the main menu (also after /start or a deep link)
            nav.insert(0, {"id": NAV_ROOT, "cb": "menu"})
        if screen is None:
            if nav[-1].get("id") is None:
                nav = nav[:-1]
            nav.append({"id": None})
        else:
            sid, cb = screen[0], screen[1]
            drop = screen[2] if len(screen) > 2 else ""
            keep = screen[3] if len(screen) > 3 else None
            index = next((i for i, e in enumerate(nav) if e.get("id") == sid), None)
            if index is not None:
                nav = nav[:index]
            # a screen before a one-off answer is still the step before this one
            nav = [e for e in nav if e.get("id") is not None
                   and not (drop and str(e.get("id")).startswith(drop)
                            and e.get("id") != keep)]
            snapshot = {k: v for k, v in (data or {}).items() if k != "labels"}
            nav.append({"id": sid, "cb": cb, "state": state or "", "data": snapshot})
        self._nav_save(platform, chat_id, nav)
        if len(nav) < 2:
            return rows
        out = []
        for row in rows:
            kept = [(label, cb) for label, cb in row if cb != "menu"]
            if kept:
                out.append(kept)
        out.append([(texts.BTN_BACK, "back"), (texts.BTN_MENU, "menu")])
        return out

    async def _go_back(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, message_id, callback_id,
        status: str,
    ) -> None:
        """One screen back with the conversation data that screen had."""
        nav = self._nav_load(platform, chat_id)
        if nav:
            nav.pop()                                    # the screen shown now
        while nav and nav[-1].get("id") is None:
            nav.pop()
        if not nav or nav[-1].get("id") == NAV_ROOT or not nav[-1].get("cb"):
            await self._answer_callback(adapter, callback_id)
            await self._show_main_menu(adapter, platform, chat_id, status=status)
            return
        target = nav[-1]
        self._nav_save(platform, chat_id, nav)
        data = target.get("data") if isinstance(target.get("data"), dict) else {}
        self.store.set_conversation(platform, chat_id, str(target.get("state") or ""), data)
        await self._replay(adapter, platform, chat_id, message_id, callback_id,
                           str(target["cb"]))

    async def _replay(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, message_id, callback_id,
        cb: str,
    ) -> None:
        """Draw a recorded screen again: an internal step or a normal callback."""
        if not cb.startswith("@"):
            await self._dispatch_callback(adapter, platform, chat_id, message_id, callback_id, cb)
            return
        await self._answer_callback(adapter, callback_id)
        kind, _, rest = cb[1:].partition(":")
        if kind == "q":
            page, _, query = rest.partition(":")
            await self._show_products(adapter, platform, chat_id, q=query, group=None,
                                      page=int(page) if page.isdigit() else 1,
                                      edit_message_id=message_id)
        elif kind == "stmt":
            await self._show_statement(adapter, platform, chat_id,
                                       int(rest) if rest.isdigit() else 1,
                                       edit_message_id=message_id)
        elif kind == "model" and rest:
            if not await self._show_model(adapter, platform, chat_id, rest):
                await self._show_main_menu(adapter, platform, chat_id)
        elif kind == "ireqtext":
            _state, data = self.store.get_conversation(platform, chat_id)
            typed = str((data or {}).get("ireq_text") or "")
            if typed:
                await self._item_request_text(adapter, platform, chat_id, typed)
            else:
                await self._ask_item_request(adapter, platform, chat_id)
        else:
            await self._show_main_menu(adapter, platform, chat_id)

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
            self._nav_save(platform, chat_id, [])          # v2.8.3: a fresh history
            args = text.split()[1:]
            # v2.11.0: the site's cart (c_…) -> purchase requests
            cart_ref = args[0] if args and looks_like_cart_ref(args[0]) else None
            model_ref = args[0] if args and not cart_ref and looks_like_model_ref(args[0]) else None
            product_code = (
                parse_product_ref(args[0], allow_bare_code=True)
                if args and not model_ref and not cart_ref else None
            )
            await self._customer_entry(
                adapter, platform, chat_id, welcome=command == "/start",
                product_code=product_code, model_ref=model_ref, cart_ref=cart_ref,
            )
            return

        # registration (the user may not exist in shopapi yet): contact only
        if state == STATE_AWAIT_CONTACT or state in LEGACY_REGISTRATION_STATES:
            if not event.get("contact") and looks_like_cart_ref(text):
                # the site's cart code, typed before registering: keep it
                self.store.set_conversation(
                    platform, chat_id, STATE_AWAIT_CONTACT, {**(data or {}), "cart": text.strip()}
                )
                await self._send_text(
                    adapter, chat_id, texts.SITE_CART_AFTER_CONTACT,
                    contact_keyboard(texts.BTN_SHARE_CONTACT),
                )
                return
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
            cart_ref = text.strip() if looks_like_cart_ref(text) else None
            model_ref = text if not cart_ref and looks_like_model_ref(text) else None
            product_code = None if model_ref or cart_ref else parse_product_ref(
                text, allow_bare_code=True)
            await self._begin_registration(
                adapter, platform, chat_id, product_code=product_code, model_ref=model_ref,
                cart_ref=cart_ref,
            )
            return
        if status == STATUS_REJECTED:
            await self._show_not_approved(adapter, platform, chat_id, status)
            return
        if looks_like_cart_ref(text):
            # the cart code typed or pasted (a deep link that lost its parameter)
            await self._site_cart(adapter, platform, chat_id, text.strip())
            return

        if state == STATE_AWAIT_ITEM_REQUEST and text and not photo and not document:
            await self._item_request_text(adapter, platform, chat_id, text)
            return
        if state == STATE_AWAIT_SEARCH and text:
            self.store.clear_conversation(platform, chat_id)
            # v2.8.0: a phone name in any spelling -> the current price list first
            if await self._phone_search(adapter, platform, chat_id, text):
                return
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

        # v2.8.0: a typed phone name («آیفون ۱۷ پرو», «17pro» …) -> the price list
        if text and not text.startswith("/") and await self._phone_search(
                adapter, platform, chat_id, text):
            return

        # any other text: back to the main menu
        await self._show_main_menu(adapter, platform, chat_id, status=status)

    async def _customer_entry(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, *, welcome: bool = True,
        product_code: int | None = None, model_ref: str | None = None,
        cart_ref: str | None = None,
    ) -> None:
        intro = texts.WELCOME if welcome else None
        status = await self.customers.status(platform, chat_id)
        if status == STATUS_NEW:
            await self._begin_registration(
                adapter, platform, chat_id, intro=intro, product_code=product_code,
                model_ref=model_ref, cart_ref=cart_ref,
            )
            return
        if status == STATUS_REJECTED:
            await self._show_not_approved(adapter, platform, chat_id, status, intro=intro)
            return
        if cart_ref:
            await self._site_cart(adapter, platform, chat_id, cart_ref)
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
        model_ref: str | None = None, cart_ref: str | None = None,
    ) -> None:
        """Ask for the contact - only the share-contact button is accepted.
        A deep-linked product, site model or site cart is remembered and handled
        after registration."""
        data = {"product": int(product_code)} if product_code else {}
        if model_ref:
            data = {"model": str(model_ref)}
        if cart_ref:
            data = {"cart": str(cart_ref)}
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
        cart_ref = (data or {}).get("cart")
        if isinstance(cart_ref, str) and looks_like_cart_ref(cart_ref):
            await self._site_cart(adapter, platform, chat_id, cart_ref)
            return
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
            [(texts.BTN_ITEM_REQUEST, "ireq")],
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
            screen=NAV_ROOT,
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
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str,
        screen=None,
    ) -> None:
        await self._send_options(
            adapter, platform, chat_id, text, [[(texts.BTN_MENU, "menu")]], screen=screen,
        )

    @staticmethod
    def _tree_order(groups: list[dict]) -> list[dict]:
        """Groups with each subgroup right after its parent (shopapi order otherwise)."""
        codes = {g.get("code") for g in groups}
        children: dict = {}
        for g in groups:
            children.setdefault(g.get("parent") if g.get("parent") in codes else None, []).append(g)
        out: list[dict] = []
        seen: set = set()

        def walk(parent) -> None:
            for g in children.get(parent, []):
                if g.get("code") in seen:
                    continue
                seen.add(g.get("code"))
                out.append(g)
                walk(g.get("code"))

        walk(None)
        out.extend(g for g in groups if g.get("code") not in seen)   # a cycle: keep it
        return out

    async def _show_groups(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        groups = await self.catalog.groups()
        if not groups:
            await self._send_options(
                adapter, platform, chat_id, texts.NO_GROUPS, [[(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={}, screen=("groups", "groups"),
            )
            return
        # v2.6.1: a subgroup (e.g. a brand under گوشی) follows its parent, indented.
        shown = {g.get("code") for g in groups}
        rows = [[(("↳ " if g.get("parent") in shown else "") + str(g.get("name") or ""),
                  f"grp:{g.get('code')}")] for g in self._tree_order(groups)]
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, texts.GROUPS_TITLE, rows, state=STATE_NONE, data={},
            screen=("groups", "groups"),
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
            if q:
                # v2.8.0: nothing matched -> the free-text item request, unchanged
                body = texts.PHONE_SEARCH_NONE.format(text=shorten(q, 60))
                rows.append([(texts.BTN_ITEM_REQUEST, "ireq")])
        else:
            lines = [texts.PRODUCTS_TITLE.format(page=page, pages=pages)]
            for product in result.items:
                code = product.code
                cache[str(code)] = product.as_cache()
                if product.on_inquiry:
                    lines.append(texts.PRODUCT_LINE_INQUIRY.format(name=product.name))
                elif product.has_colors:
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
                shown = label if product.in_stock or product.on_inquiry else f"❌ {label}"
                rows.append([(shown, f"prod:{code}")])
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
        replay = (f"@q:{int(page)}:{q}" if q else
                  f"pg:{int(group) if group is not None else 0}:{int(page)}")
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data={"pcache": cache}, edit_message_id=edit_message_id,
            screen=("list", replay),
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
        if product.get("inquiry"):
            # v2.6.1: no price and no cart; the customer asks the shop instead.
            await self._send_options(
                adapter, platform, chat_id,
                texts.PRODUCT_DETAIL_INQUIRY.format(name=product["name"]),
                [[(texts.BTN_BUY_INQUIRY, f"pinq:{code}")], [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=(f"product:{code}", f"prod:{code}"),
            )
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
                [[(texts.BTN_REQUEST_THIS, f"ireqk:{code}")], [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=(f"product:{code}", f"prod:{code}"),
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
            screen=(f"product:{code}", f"qty:{code}:{qty}"),
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
                    rows, state=STATE_NONE, data={}, screen=("model", f"@model:{text}"),
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
                    screen=("model", f"@model:{text}"),
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
        if product.get("inquiry"):
            await self._answer_callback(adapter, callback_id, texts.PRICE_ON_INQUIRY_NO_CART, True)
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
        """One button per color name (its parts are picked next, v2.6.2)."""
        current_name = next((c.get("name") for c in colors if int(c["id"]) == int(current)), None)
        by_name: dict[str, dict] = {}
        for c in colors:
            name = str(c.get("name") or "")
            first = by_name.get(name)
            if first is None or (c.get("available") and not first.get("available")):
                by_name[name] = c
        rows, row = [], []
        for name, c in by_name.items():
            if current and name == current_name:
                continue
            mark = "🎨" if any(v.get("available") for v in colors
                              if str(v.get("name") or "") == name) else "❌"
            row.append((f"{mark} {shorten(name, 20)}", f"col:{code}:{c['id']}"))
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
                f"«{product['name']}»\n{texts.NO_COLORS_PRICE}",
                [[(texts.BTN_BUY_INQUIRY, f"inq:{code}:0")], [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=(f"product:{code}", f"prod:{code}"),
            )
            return
        rows = self._color_rows(code, colors)
        body = texts.CHOOSE_COLOR.format(name=product["name"])
        if await self._shop_closed():
            body = f"{texts.SHOP_CLOSED_NOTICE}\n\n{body}"
            rows.append([(texts.BTN_NOTIFY_SALES, "snot")])
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            screen=(f"product:{code}", f"prod:{code}"),
        )

    async def _show_color(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int,
        color_id: int, qty: int, *, callback_id=None, edit_message_id=None,
        refresh: bool = True, choose_part: bool = False,
    ) -> None:
        """The price of one color. Picking another color announces its price.
        v2.6.2: a color sold in several parts (ZAA / CHA …) first asks for the part
        (``choose_part``); only parts with a price in the current list are offered."""
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

        if choose_part:
            parts = [c for c in colors if c.get("name") == color.get("name")
                     and c.get("part") and c.get("available") and c.get("price")]
            if len(parts) > 1:
                await self._answer_callback(adapter, callback_id)
                rows = [[(f"{shorten(str(p['part']), 20)} — {fmt_num(p['price'])}",
                          f"prt:{code}:{p['id']}")] for p in parts]
                rows += self._color_rows(code, colors, current=color_id)
                rows.append([(texts.BTN_MENU, "menu")])
                await self._send_options(
                    adapter, platform, chat_id,
                    texts.CHOOSE_PART.format(name=product["name"], color=color["name"]), rows,
                    state=STATE_NONE, data={**data, "pcache": cache},
                    edit_message_id=edit_message_id,
                    screen=(f"part:{code}:{color.get('name') or ''}", f"col:{code}:{color_id}"),
                )
                return
            if len(parts) == 1:
                color = parts[0]                 # the only part with a price
                color_id = int(color["id"])

        selected = dict(data.get("color_sel") or {})
        previous = int(selected.get(str(code)) or 0)
        selected[str(code)] = int(color_id)
        data = {**data, "pcache": cache, "color_sel": selected}
        name = product["name"]
        others = self._color_rows(code, colors, current=color_id)
        # v2.8.3: «مرحلهٔ قبل» from the price goes to the part of THIS color (if it
        # was asked), else to the colors
        detail_screen = (f"color:{code}", f"prt:{code}:{color_id}", f"part:{code}:",
                         f"part:{code}:{color.get('name') or ''}")

        if color.get("held"):
            # v2.9.2: the new list price waits for a manager: only a request
            await self._answer_callback(adapter, callback_id)
            await self._send_options(
                adapter, platform, chat_id,
                texts.PRICE_HELD_NOTE.format(
                    name=name, color=color["name"],
                    part=f" — {color['part']}" if color.get("part") else ""),
                [[(texts.BTN_BUY_INQUIRY, f"pbv:{code}:{color_id}")], *others,
                 [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=detail_screen,
            )
            return
        if not color.get("available") or not color.get("price"):
            await self._answer_callback(adapter, callback_id)
            rows = [[(texts.BTN_BUY_INQUIRY, f"inq:{code}:{color_id}")], *others,
                    [(texts.BTN_MENU, "menu")]]
            await self._send_options(
                adapter, platform, chat_id,
                texts.COLOR_NO_PRICE.format(name=name, color=color["name"]), rows,
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=detail_screen,
            )
            return

        qty = clamp_qty(qty)
        price = fmt_num(color["price"])
        chosen = variant_label(color)
        body = texts.PRODUCT_COLOR_DETAIL.format(
            name=name, color=chosen, price=price, qty=fmt_num(qty),
        )
        refusal = await self._phone_refusal(platform, chat_id, code, int(color_id), qty)
        if refusal == "color":
            await self._answer_callback(adapter, callback_id)
            rows = [[(texts.BTN_BUY_INQUIRY, f"inq:{code}:{color_id}")], *others,
                    [(texts.BTN_MENU, "menu")]]
            await self._send_options(
                adapter, platform, chat_id,
                texts.COLOR_NO_PRICE.format(name=name, color=color["name"]), rows,
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=detail_screen,
            )
            return
        if refusal == "stock" or (
                product.get("stock") is not None and float(product.get("stock") or 0) <= 0):
            # v2.8.0: in the list but not in stock in «سازه حساب»: request, never order.
            # v2.8.2: asked from shopapi with the checkout's own rules (also the cart)
            await self._answer_callback(adapter, callback_id)
            await self._send_options(
                adapter, platform, chat_id,
                texts.PHONE_SEARCH_ROW.format(
                    model=name, color=color["name"], price=price,
                    part=texts.PHONE_SEARCH_PART_LINE.format(part=color["part"])
                    if color.get("part") else "") + "\n\n" + texts.PURCHASE_REQUEST_NOTE,
                [[(texts.BTN_BUY_INQUIRY, f"pbv:{code}:{color_id}")], *others,
                 [(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data=data, edit_message_id=edit_message_id,
                screen=detail_screen,
            )
            return
        changed = bool(previous) and previous != int(color_id)
        # The image card goes out on the first color pick of a product view only;
        # later switches keep the short "new price" text (no new image).
        if self.settings.bot_image_cards and data.get("card_code") != int(code):
            from .cards import price_card

            sent_card = await self._send_card(
                adapter, chat_id,
                lambda: price_card(
                    shop=texts.SHOP.get("shop_name", ""), name=name, color=chosen,
                    price=color["price"], in_stock=True,
                    contact={**self._card_contact(), "thanks": ""},
                    currency=texts.SHOP.get("currency", "ریال"),
                ),
                texts.CARD_CAPTION_PRICE.format(name=name, color=chosen, price=price),
            )
            if sent_card:
                data = {**data, "card_code": int(code)}
        if changed:
            notice = texts.COLOR_CHANGED.format(color=chosen, price=price)
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
            screen=(detail_screen[0], f"vqty:{code}:{color_id}:{qty}", *detail_screen[2:]),
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
        if color.get("held"):
            await self._answer_callback(adapter, callback_id)
            await self._show_color(adapter, platform, chat_id, code, int(color_id), 1)
            return
        if not color.get("available") or not color.get("price"):
            await self._answer_callback(adapter, callback_id, texts.OUT_OF_STOCK)
            return
        # v2.8.2: the same checks as the checkout, for the cart's quantity + this one
        refusal = await self._phone_refusal(platform, chat_id, code, int(color_id), qty)
        if refusal in ("stock", "color"):
            await self._answer_callback(adapter, callback_id)
            await self._show_color(adapter, platform, chat_id, code, int(color_id), 1)
            return
        # shopapi prices the order again at checkout (the list may change).
        self.cart.add(platform, chat_id, code, f"{product['name']} — {variant_label(color)}",
                      qty, color["price"], int(color_id))
        await self._answer_callback(adapter, callback_id, texts.QTY_ADDED)
        await self._show_cart(adapter, platform, chat_id)

    async def _phone_refusal(self, platform: str, chat_id: str, code: int, color_id: int,
                             qty: int) -> str | None:
        """v2.8.2: may this phone color be ordered now (with what is already in the
        cart)? ``"stock"`` = no stock in «سازه حساب» (offer «درخواست خرید»),
        ``"color"`` = the color / part is gone, None = fine or unknown (shopapi
        down: the checkout checks again anyway)."""
        in_cart = sum(float(it.get("qty") or 0) for it in self.cart.items(platform, chat_id)
                      if int(it.get("kala_code") or 0) == int(code)
                      and int(it.get("variant_id") or 0) == int(color_id))
        line = {"kala_code": int(code), "qty": float(in_cart + clamp_qty(qty)),
                "variant_id": int(color_id)}
        try:
            await self.api.check_order(platform, chat_id, [line])
        except ShopApiRejected as exc:
            detail = str(exc.detail or "").lower()
            if "no stock" in detail or "insufficient stock" in detail \
                    or "price waits for approval" in detail:
                return "stock"
            if "color" in detail or "not in the current price list" in detail \
                    or "not available for sale" in detail:
                return "color"
            return None
        except ShopApiError:
            return None
        return None

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

    async def _send_price_inquiry(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: int, callback_id=None,
    ) -> None:
        """v2.6.1: «استعلام قیمت» of a price-on-inquiry product = an item request of
        kind ``inquiry`` (ShopAdmin «درخواست کالا»); no order, no payment."""
        _state, data = self.store.get_conversation(platform, chat_id)
        product = (data.get("pcache") or {}).get(str(code)) or {}
        name = str(product.get("name") or code)
        marker = f"pinq:{code}"
        sent_text = texts.PRICE_INQUIRY_SENT.format(name=name)
        if marker in (data.get("inquired") or []):
            await self._answer_callback(adapter, callback_id, sent_text)
            return
        try:
            await self.api.create_item_request(platform, chat_id, kala_code=code, kind="inquiry")
        except ShopApiRejected as exc:
            message = {429: texts.ITEM_REQUEST_TOO_MANY,
                       404: texts.PRODUCT_NOT_FOUND}.get(exc.status or 0, exc.message_fa)
            await self._answer_callback(adapter, callback_id)
            await self._send_options(adapter, platform, chat_id, message,
                                     [[(texts.BTN_MENU, "menu")]], state=STATE_NONE, data={})
            return
        except ShopApiError:
            await self._answer_callback(adapter, callback_id, texts.SERVICE_UNAVAILABLE, True)
            return
        data = {**data, "inquired": [*(data.get("inquired") or [])[-19:], marker]}
        self.store.set_conversation(platform, chat_id, _state, data)
        await self._answer_callback(adapter, callback_id, sent_text)
        await self._send_options(adapter, platform, chat_id, sent_text,
                                 [[(texts.BTN_MENU, "menu")]])

    def _refused_item_text(self, platform: str, chat_id: str, detail: str | None) -> str | None:
        """v2.6.1: a stale cart item refused at the final submit -> a clear message."""
        match = _REFUSED_ITEM.match(str(detail or "").strip())
        if not match or match.group(2) not in REFUSED_ITEM_TEXTS:
            return None
        code = int(match.group(1))
        name = next((str(it.get("name") or "") for it in self.cart.items(platform, chat_id)
                     if int(it.get("kala_code") or 0) == code), "") or str(code)
        return getattr(texts, REFUSED_ITEM_TEXTS[match.group(2)]).format(name=name)

    async def _show_cart(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        items = self.cart.items(platform, chat_id)
        if not items:
            await self._send_options(
                adapter, platform, chat_id, texts.CART_EMPTY, [[(texts.BTN_MENU, "menu")]],
                state=STATE_NONE, data={}, screen=("cart", "cart"),
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
        if state.get("payment_ready") is False:
            # v2.6.0: no card configured -> never a placeholder, no checkout
            lines.append("")
            lines.append(texts.PAYMENT_NOT_READY)
        elif state.get("closed") and self._has_phones(items):
            # Only phones are closed: the customer may remove them and order the rest.
            lines.append("")
            lines.append(self._sales_closed_text(state))
            rows.append([(texts.BTN_NOTIFY_SALES, "snot")])
        else:
            rows.append([(texts.BTN_CHECKOUT, "checkout")])
        rows.append([(texts.BTN_CLEAR_CART, "cclear"), (texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, "\n".join(lines), rows, state=STATE_NONE, data={},
            screen=("cart", "cart"),
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
        # The final step reads the state fresh (never the 30 s cache): sales may
        # have closed since the cart was shown. shopapi checks again anyway.
        self._shop_state = None
        state = await self._sales_state()
        if state.get("payment_ready") is False:
            await self._send_options(
                adapter, platform, chat_id, texts.PAYMENT_NOT_READY, [[(texts.BTN_MENU, "menu")]],
            )
            return
        if state.get("closed") and self._has_phones(self.cart.items(platform, chat_id)):
            await self._send_options(
                adapter, platform, chat_id, self._sales_closed_text(state),
                [[(texts.BTN_NOTIFY_SALES, "snot")], [(texts.BTN_MENU, "menu")]],
            )
            return
        try:
            result = await self.orders.checkout(platform, chat_id)
        except ShopApiRejected as exc:
            if exc.status == 409 and "payment details" in (exc.detail or "").lower():
                self._shop_state = None
                await self._send_options(
                    adapter, platform, chat_id, texts.PAYMENT_NOT_READY,
                    [[(texts.BTN_MENU, "menu")]],
                )
                return
            if exc.status == 409 and "sales are closed" in (exc.detail or "").lower():
                self._shop_state = None          # closed meanwhile: refresh next time
                await self._send_options(
                    adapter, platform, chat_id,
                    self._sales_closed_text(await self._sales_state()),
                    [[(texts.BTN_MENU, "menu")]],
                )
                return
            refused = self._refused_item_text(platform, chat_id, exc.detail) \
                if exc.status == 422 else None
            if refused:
                rows = [[(texts.BTN_CART, "cart")], [(texts.BTN_MENU, "menu")]]
                no_stock = self._no_stock_item(platform, chat_id, exc.detail)
                if no_stock is not None:
                    # v2.8.2: became unavailable since it was added: one tap to request it
                    rows.insert(0, [(texts.BTN_BUY_INQUIRY,
                                     f"pbv:{no_stock[0]}:{no_stock[1]}")])
                await self._send_options(adapter, platform, chat_id, refused, rows)
                return
            raise
        if result.empty_cart:
            await self._send_text(adapter, chat_id, texts.CART_EMPTY)
            return
        if result.price_changes:
            # v2.9.1: a new price list since the items were added: confirm again
            currency = texts.SHOP.get("currency", "ریال")
            lines = "\n".join(texts.CART_PRICE_CHANGED_LINE.format(
                name=name, old=fmt_num(old), new=fmt_num(new), currency=currency)
                for name, old, new in result.price_changes)
            await self._send_text(adapter, chat_id, texts.CART_PRICES_CHANGED.format(items=lines))
            await self._show_cart(adapter, platform, chat_id)
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
        if order.get("payment_info"):
            minutes = state.get("receipt_deadline_minutes") or DEFAULT_RECEIPT_MINUTES
            parts.append(texts.RECEIPT_DEADLINE_NOTE.format(minutes=fmt_num(minutes)))
            parts.append(self._payment_text(order, total))
            self.store.set_conversation(
                platform, chat_id, STATE_AWAIT_RECEIPT, {"order_id": order_id}
            )
        else:
            # v2.8.2: staff send the payment details for this order («ارسال اطلاعات
            # پرداخت»); the receipt deadline starts then.
            parts.append(texts.WAIT_PAYMENT_INFO)
            self.store.set_conversation(platform, chat_id, STATE_NONE, {})
        if self.settings.bot_image_cards and order.get("items") and order.get("payment_info"):
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
        body = "\n\n".join(parts)
        sent = await self._send_options(
            adapter, platform, chat_id, body,
            [[(texts.BTN_CANCEL_ORDER, f"ocx:{order_id}")], [(texts.BTN_MENU, "menu")]],
        )
        self._remember_order_message(order_id, platform, chat_id, sent, body)
        if order_id is not None and not self.store.is_announced("neworder", int(order_id)):
            self.store.mark_announced("neworder", int(order_id), platform, chat_id)
            await self._announce_new_order(order)

    @staticmethod
    def _card_contact() -> dict:
        """Footer of the invoice cards, from the shop texts (messages.fa.json)."""
        return {"address": texts.SHOP.get("shop_address", ""), "phone": texts.SHOP.get("shop_phone", ""),
                "bot_id": texts.SHOP.get("bot_id", ""), "thanks": texts.SHOP.get("invoice_thanks", "")}

    def _no_stock_item(self, platform: str, chat_id: str, detail) -> tuple[int, int] | None:
        """(code, color) of a cart phone refused for lack of stock, or None."""
        match = _REFUSED_ITEM.match(str(detail or "").strip())
        if not match or ("no stock" not in match.group(2)
                         and "price waits for approval" not in match.group(2)):
            return None
        code = int(match.group(1))
        variant = next((int(it.get("variant_id") or 0) for it in self.cart.items(platform, chat_id)
                        if int(it.get("kala_code") or 0) == code), 0)
        return code, variant

    @staticmethod
    def _payment_info_text(order: dict) -> str:
        """v2.8.2: the payment details staff typed for this order; empty fields are
        left out."""
        info = order.get("payment_info") if isinstance(order.get("payment_info"), dict) else {}
        lines = [texts.PAYMENT_INFO_TITLE.format(
            order_id=order.get("id"), total=fmt_num(order.get("total")),
            currency=texts.SHOP.get("currency", "ریال"))]
        for key, text_key in PAYMENT_INFO_LINES:
            value = str(info.get(key) or "").strip()
            if value and key in LTR_PAYMENT_FIELDS:
                value = ltr(value)          # v2.8.3: never reversed by the client
            if value:
                lines.append(getattr(texts, text_key).format(value=value))
        lines.append(texts.PAYMENT_SEND_RECEIPT)
        return "\n".join(lines)

    @staticmethod
    def _payment_text(order: dict, total: str) -> str:
        """Payment details of an order. v2.8.2: what staff sent for this order
        (``payment_info``); the older fixed fields only from an older shopapi."""
        if isinstance(order.get("payment_info"), dict) and order["payment_info"]:
            return BotEngine._payment_info_text(order)
        order_id = order.get("id")
        card = str(order.get("payment_card_number") or "").strip()
        if not card:      # an older shopapi: no card -> no made-up number either
            return texts.PAYMENT_NOT_READY + "\n\n" + texts.ASK_RECEIPT.format(order_id=order_id)
        digits = "".join(ch for ch in card if ch.isdigit())
        if len(digits) == 16:
            card = "-".join(digits[i:i + 4] for i in range(0, 16, 4))
        owner = str(order.get("payment_owner") or "").strip()
        sheba = str(order.get("payment_sheba") or "").strip()
        note = str(order.get("payment_instructions") or "").strip()
        lines = [texts.PAYMENT_DETAILS.format(order_id=order_id, total=total, card=ltr(card))]
        if owner:
            lines.append(texts.PAYMENT_OWNER_LINE.format(owner=owner))
        if sheba:
            lines.append(texts.PAYMENT_SHEBA_LINE.format(sheba=ltr(sheba)))
        if note and "xxxx" not in note.lower():
            lines.append(note)
        lines.append(texts.PAYMENT_SEND_RECEIPT)
        return "\n".join(lines)

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
                state=STATE_NONE, data={}, screen=("orders", "orders"),
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
                    [(f"{texts.BTN_SEND_RECEIPT} ({order.get('id')})", f"rcpt:{order.get('id')}"),
                     (f"{texts.BTN_CANCEL_ORDER} ({order.get('id')})", f"ocx:{order.get('id')}")]
                )
        rows.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, "\n".join(lines), rows, state=STATE_NONE, data={},
            screen=("orders", "orders"),
        )

    # ---- v2.6.2: the customer cancels their own order (no receipt sent yet) ----
    async def _ask_cancel_order(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int,
        callback_id=None,
    ) -> None:
        await self._answer_callback(adapter, callback_id)
        await self._send_options(
            adapter, platform, chat_id, texts.CANCEL_ORDER_CONFIRM.format(order_id=order_id),
            [[(texts.BTN_CANCEL_ORDER_YES, f"ocy:{order_id}")],
             [(texts.BTN_CANCEL_ORDER_NO, "orders")], [(texts.BTN_MENU, "menu")]],
        )

    async def _cancel_order(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int,
        callback_id=None,
    ) -> None:
        try:
            await self.api.cancel_order(order_id, platform, chat_id)
        except ShopApiRejected as exc:
            await self._answer_callback(adapter, callback_id)
            detail = (exc.detail or "").lower()
            text = (texts.CANCEL_ORDER_RECEIPT_SENT if "receipt already sent" in detail
                    else texts.CANCEL_ORDER_NOT_POSSIBLE if exc.status in (404, 409)
                    else exc.message_fa)
            await self._send_options(adapter, platform, chat_id, text,
                                     [[(texts.BTN_ORDERS, "orders")], [(texts.BTN_MENU, "menu")]])
            return
        except ShopApiError:
            await self._answer_callback(adapter, callback_id, texts.SERVICE_UNAVAILABLE, True)
            return
        state, data = self.store.get_conversation(platform, chat_id)
        if state == STATE_AWAIT_RECEIPT and int((data or {}).get("order_id") or 0) == int(order_id):
            self.store.set_conversation(platform, chat_id, STATE_NONE, {})
        await self._answer_callback(adapter, callback_id, texts.CANCEL_ORDER_DONE.format(
            order_id=order_id))
        await self._send_options(
            adapter, platform, chat_id, texts.CANCEL_ORDER_DONE.format(order_id=order_id),
            [[(texts.BTN_ORDERS, "orders")], [(texts.BTN_MENU, "menu")]],
            state=STATE_NONE, data={},
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
                adapter, platform, chat_id, texts.STATEMENT_EMPTY, menu, state=STATE_NONE, data={},
                screen=("stmt", f"@stmt:{page}"),
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
            edit_message_id=edit_message_id, screen=("stmt", f"@stmt:{page}"),
        )

    async def _send_statement_pdf(
        self, adapter: PlatformAdapter, platform: str, chat_id: str
    ) -> bool:
        """The statement as ONE PDF document (v2.6.0). False = not sent (no browser,
        rendering or upload failed, an old shopapi) -> the caller sends the text."""
        result = await self.api.get_statement_full(platform, chat_id)
        if not isinstance(result, dict):
            return False
        from .cards.statement_pdf import statement_pdf

        currency = texts.SHOP.get("currency", "ریال")
        await self._send_text(adapter, chat_id, texts.STATEMENT_PDF_WAIT)
        try:
            pdf = await asyncio.to_thread(
                statement_pdf, result, shop=texts.SHOP.get("shop_name", ""),
                currency=currency, contact=self._card_contact(),
            )
            if not pdf:
                return False
            sides = {"debtor": texts.SIDE_DEBTOR, "creditor": texts.SIDE_CREDITOR,
                     "zero": texts.SIDE_ZERO}
            caption = texts.STATEMENT_PDF_CAPTION.format(
                balance=fmt_num(result.get("balance")), side=sides.get(str(result.get("side")), ""))
            await adapter.send_document_bytes(
                chat_id, pdf, f"statement-{result.get('person_code') or ''}.pdf", caption)
        except BotApiError as exc:
            self.logger.warning("platform=%s statement_pdf_send_failed=%s", adapter.platform, exc.method)
            return False
        except Exception as exc:  # noqa: BLE001 - the text statement is the fallback
            self.logger.warning("platform=%s statement_pdf_failed=%s", adapter.platform,
                                type(exc).__name__)
            return False
        await self._send_options(
            adapter, platform, chat_id, texts.MAIN_MENU, self._main_menu_rows(True),
            state=STATE_NONE, data={}, screen=NAV_ROOT,
        )
        return True

    # ---- v2.8.0: smart phone search in the current price list ---------------------------
    async def _phone_search(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str,
    ) -> bool:
        """Rows of today's list matching a typed phone name (shopapi normalizes any
        spelling). False = nothing matched (the caller goes on as before)."""
        query = " ".join(text.split())[:100]
        if len(query) < 2:
            return False
        try:
            result = await self.api.phone_search(query)
        except ShopApiRejected:
            return False
        items = [i for i in (result.get("items") or []) if isinstance(i, dict) and i.get("row_key")]
        if not items:
            return False
        rows = [{"k": str(i["row_key"]), "m": int(i.get("model_index") or 0),
                 "n": str(i.get("model") or ""), "c": str(i.get("color") or ""),
                 "p": str(i.get("part") or ""), "pr": float(i.get("price") or 0),
                 # v2.9.2: the price waits for a manager (shown «با استعلام»)
                 "h": bool(i.get("price_held")),
                 "code": int(i["kala_code"]) if i.get("kala_code") else 0,
                 "v": int(i["variant_id"]) if i.get("variant_id") else 0,
                 "a": "order" if i.get("action") == "order" else "purchase"}
                for i in items[:40]]
        self.store.set_conversation(platform, chat_id, STATE_NONE, {
            "ps": {"text": query, "rows": rows, "open": bool(result.get("sales_open", True))}})
        models = sorted({r["m"] for r in rows})
        if len(models) == 1:
            await self._ps_model(adapter, platform, chat_id, models[0])
        else:
            await self._ps_models(adapter, platform, chat_id)
        return True

    def _ps_rows(self, platform: str, chat_id: str) -> tuple[dict, list[dict]]:
        _state, data = self.store.get_conversation(platform, chat_id)
        ps = (data or {}).get("ps") if isinstance(data, dict) else None
        rows = (ps or {}).get("rows") if isinstance(ps, dict) else None
        return (data or {}), [r for r in (rows or []) if isinstance(r, dict)]

    async def _ps_models(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                         edit_message_id=None) -> None:
        data, rows = self._ps_rows(platform, chat_id)
        if not rows:
            await self._show_main_menu(adapter, platform, chat_id)
            return
        buttons, seen = [], set()
        for r in rows:
            if r["m"] in seen:
                continue
            seen.add(r["m"])
            low = _lowest(x["pr"] for x in rows if x["m"] == r["m"])
            buttons.append([(f"{shorten(r['n'], 28)} — {_price_or_ask(low)}", f"psm:{r['m']}")])
        buttons.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id,
            texts.PHONE_SEARCH_MODELS.format(text=shorten(data["ps"].get("text") or "", 60)),
            buttons, state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            screen=("ps", "psl"))

    async def _ps_model(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                        model: int, edit_message_id=None) -> None:
        data, rows = self._ps_rows(platform, chat_id)
        mine = [r for r in rows if r["m"] == int(model)]
        if not mine:
            await self._ps_models(adapter, platform, chat_id)
            return
        colors = list(dict.fromkeys(r["c"] for r in mine))
        if len(colors) == 1:
            await self._ps_color(adapter, platform, chat_id, model, 0,
                                 edit_message_id=edit_message_id)
            return
        buttons, row = [], []
        for n, color in enumerate(colors):
            low = _lowest(r["pr"] for r in mine if r["c"] == color)
            row.append((f"🎨 {shorten(color, 16)} — {_price_or_ask(low)}", f"psc:{model}:{n}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        if len({r["m"] for r in rows}) > 1:
            buttons.append([(texts.BTN_OTHER_MODELS, "psl")])
        buttons.append([(texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id, texts.PHONE_SEARCH_COLORS.format(model=mine[0]["n"]),
            buttons, state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            screen=("ps:model", f"psm:{int(model)}"))

    async def _ps_color(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                        model: int, color_index: int, edit_message_id=None) -> None:
        data, rows = self._ps_rows(platform, chat_id)
        mine = [r for r in rows if r["m"] == int(model)]
        colors = list(dict.fromkeys(r["c"] for r in mine))
        if not 0 <= int(color_index) < len(colors):
            await self._ps_models(adapter, platform, chat_id)
            return
        color = colors[int(color_index)]
        parts = [(n, r) for n, r in enumerate(rows) if r["m"] == int(model) and r["c"] == color]
        if len(parts) == 1:
            await self._ps_row(adapter, platform, chat_id, parts[0][0],
                               edit_message_id=edit_message_id)
            return
        buttons = [[(f"{shorten(r['p'] or '—', 20)} — {_price_or_ask(r['pr'])}", f"psr:{n}")]
                   for n, r in parts]
        buttons.append([(texts.BTN_OTHER_MODELS, "psl"), (texts.BTN_MENU, "menu")])
        await self._send_options(
            adapter, platform, chat_id,
            texts.PHONE_SEARCH_PARTS.format(model=parts[0][1]["n"], color=color),
            buttons, state=STATE_NONE, data=data, edit_message_id=edit_message_id,
            screen=("ps:color", f"psc:{int(model)}:{int(color_index)}"))

    async def _ps_row(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                      index: int, *, callback_id=None, edit_message_id=None) -> None:
        """One row: price, then «افزودن به سبد» (mapped, in stock: the usual color
        screen with the price read again) or «درخواست خرید»."""
        data, rows = self._ps_rows(platform, chat_id)
        if not 0 <= int(index) < len(rows):
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
            return
        row = rows[int(index)]
        if row["a"] == "order" and row["code"] and row["v"]:
            product = await self.catalog.product(row["code"])
            if product is not None and product.color(row["v"]) is not None:
                cache = {**(data.get("pcache") or {}), str(product.code): product.as_cache()}
                self.store.set_conversation(platform, chat_id, STATE_NONE,
                                            {**data, "pcache": cache})
                await self._show_color(adapter, platform, chat_id, row["code"], row["v"], 1,
                                       callback_id=callback_id, edit_message_id=edit_message_id,
                                       refresh=False)
                return
        await self._answer_callback(adapter, callback_id)
        if row.get("h") or not row["pr"]:
            # v2.9.2: the new list price waits for a manager: never the old one
            body = texts.PRICE_HELD_NOTE.format(
                name=row["n"], color=row["c"] or "—",
                part=f" — {row['p']}" if row["p"] else "")
        else:
            body = texts.PHONE_SEARCH_ROW.format(
                model=row["n"], color=row["c"] or "—", price=fmt_num(row["pr"]),
                part=texts.PHONE_SEARCH_PART_LINE.format(part=row["p"]) if row["p"] else "")
            body += "\n\n" + texts.PURCHASE_REQUEST_NOTE
        if not (data.get("ps") or {}).get("open", True):
            body = f"{texts.SALES_CLOSED_SEARCH}\n\n{body}"
        buttons = [[(texts.BTN_BUY_INQUIRY, f"pbr:{int(index)}")]]
        if len({r["m"] for r in rows}) > 1:
            buttons.append([(texts.BTN_OTHER_MODELS, "psl")])
        buttons.append([(texts.BTN_MENU, "menu")])
        await self._send_options(adapter, platform, chat_id, body, buttons, state=STATE_NONE,
                                 data=data, edit_message_id=edit_message_id,
                                 screen=("ps:row", f"psr:{int(index)}"))

    async def _site_cart(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, code: str,
    ) -> None:
        """v2.11.0: the site's cart (``c_…``) -> one «درخواست خرید - استعلام قیمت»
        per line (shopapi decodes it); the customer sees what was registered."""
        menu = [[(texts.BTN_MENU, "menu")]]
        try:
            result = await self.api.create_cart_requests(platform, chat_id, code)
        except ShopApiRejected as exc:
            message = {429: texts.ITEM_REQUEST_TOO_MANY,
                       422: texts.SITE_CART_FAILED}.get(exc.status or 0, exc.message_fa)
            await self._send_options(adapter, platform, chat_id, message, menu,
                                     state=STATE_NONE, data={})
            return
        except ShopApiError:
            await self._send_text(adapter, chat_id, texts.SERVICE_UNAVAILABLE)
            return
        result = result if isinstance(result, dict) else {}
        created = [c for c in result.get("created") or [] if isinstance(c, dict)]
        if result.get("repeated"):
            body = texts.SITE_CART_REPEATED
        elif not created:
            body = texts.SITE_CART_FAILED
        else:
            lines = "\n".join(texts.SITE_CART_LINE.format(
                name=shorten(str(c.get("name") or ""), 60),
                color=texts.SITE_CART_COLOR.format(color=c["color"]) if c.get("color") else "",
                qty=int(c.get("qty") or 1)) for c in created)
            body = texts.SITE_CART_SENT.format(lines=lines)
        if result.get("unknown") and not result.get("repeated"):
            body += "\n" + texts.SITE_CART_UNKNOWN.format(
                count=int(result["unknown"]))
        await self._send_options(adapter, platform, chat_id, body, menu, state=STATE_NONE, data={})

    async def _purchase_request(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, callback_id=None, *,
        row: int | None = None, code: int | None = None, variant_id: int | None = None,
    ) -> None:
        """«درخواست خرید»: no order and no payment; staff confirm the stock in
        ShopAdmin and the bot then sends the payment details."""
        data, rows = self._ps_rows(platform, chat_id)
        kwargs: dict = {}
        name = ""
        if row is not None:
            if not 0 <= int(row) < len(rows):
                await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
                return
            picked = rows[int(row)]
            kwargs = {"row_key": picked["k"]}
            name = " — ".join(p for p in (picked["n"], picked["c"], picked["p"]) if p)
            marker = f"pbr:{picked['k']}"
        else:
            product = (data.get("pcache") or {}).get(str(code)) or {}
            color = next((c for c in product.get("colors") or []
                          if int(c.get("id") or 0) == int(variant_id or 0)), {})
            kwargs = {"kala_code": int(code or 0), "variant_id": int(variant_id or 0)}
            name = " — ".join(p for p in (str(product.get("name") or ""), variant_label(color))
                              if p)
            marker = f"pbv:{code}:{variant_id}"
        sent_text = texts.PURCHASE_REQUEST_SENT.format(name=shorten(name, 80) or "این کالا")
        if marker in (data.get("inquired") or []):
            await self._answer_callback(adapter, callback_id, sent_text)
            return
        try:
            await self.api.create_purchase_request(platform, chat_id, **kwargs)
        except ShopApiRejected as exc:
            message = {429: texts.ITEM_REQUEST_TOO_MANY,
                       404: texts.COLOR_GONE}.get(exc.status or 0, exc.message_fa)
            await self._answer_callback(adapter, callback_id)
            await self._send_options(adapter, platform, chat_id, message,
                                     [[(texts.BTN_MENU, "menu")]], state=STATE_NONE, data={})
            return
        except ShopApiError:
            await self._answer_callback(adapter, callback_id, texts.SERVICE_UNAVAILABLE, True)
            return
        data = {**data, "inquired": [*(data.get("inquired") or [])[-19:], marker]}
        self.store.set_conversation(platform, chat_id, STATE_NONE, data)
        if code is not None:
            # v2.8.2: requested instead of ordered: no longer in the cart
            self.cart.remove(platform, chat_id, int(code), int(variant_id or 0))
        await self._answer_callback(adapter, callback_id, sent_text)
        await self._send_options(adapter, platform, chat_id, sent_text,
                                 [[(texts.BTN_MENU, "menu")]])

    async def _notify_purchase_order(self, order_id: int) -> bool:
        """v2.8.0: staff confirmed the stock of a purchase request: the order is
        ready, the customer pays now (same receipt flow and deadline)."""
        marker = "notified:purchase_order"
        if self.store.is_announced(marker, order_id):
            return False
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            return False
        if not isinstance(order, dict):
            self.store.mark_announced(marker, order_id, "", "")
            return False
        target = await self._find_order_chat(int(order_id))
        self.store.mark_announced(marker, order_id, str((target or {}).get("platform") or ""),
                                  (target or {}).get("chat_id") or "")
        if not target or order.get("status") != "awaiting_payment":
            return False
        adapter = self.adapters.get(str(target.get("platform") or ""))
        if adapter is None:
            return False
        platform, chat_id = str(target["platform"]), str(target["chat_id"])
        self.store.mark_announced("neworder", int(order_id), platform, chat_id)
        items = [it for it in order.get("items") or [] if isinstance(it, dict)]
        total = fmt_num(order.get("total"))
        state = await self._sales_state()
        minutes = state.get("receipt_deadline_minutes") or DEFAULT_RECEIPT_MINUTES
        parts = [texts.PURCHASE_ORDER_READY.format(
                     name=shorten(str((items[0] if items else {}).get("name") or ""), 80),
                     order_id=order_id, total=total)]
        if order.get("payment_info"):
            parts += [texts.RECEIPT_DEADLINE_NOTE.format(minutes=fmt_num(minutes)),
                      self._payment_text(order, total)]
            self.store.set_conversation(platform, chat_id, STATE_AWAIT_RECEIPT,
                                        {"order_id": int(order_id)})
        else:
            # v2.8.2: staff send the payment details next (their own message)
            parts.append(texts.WAIT_PAYMENT_INFO)
        body = "\n\n".join(parts)
        sent = await self._send_options(
            adapter, platform, chat_id, body,
            [[(texts.BTN_CANCEL_ORDER, f"ocx:{order_id}")], [(texts.BTN_MENU, "menu")]],
        )
        self._remember_order_message(order_id, platform, chat_id, sent, body)
        return True

    async def _send_payment_info(self, order_id: int, event_id: int) -> bool:
        """v2.8.2: staff sent the payment details of an order: the customer gets
        them (only the filled fields) and the bot waits for the receipt. Sending
        again (new details) sends a new message."""
        marker = "notified:payment_info"
        if self.store.is_announced(marker, int(event_id)):
            return False
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            return False
        target = await self._find_order_chat(int(order_id))
        self.store.mark_announced(marker, int(event_id), str((target or {}).get("platform") or ""),
                                  (target or {}).get("chat_id") or "")
        if not isinstance(order, dict) or not target or order.get("status") != "awaiting_payment" \
                or not order.get("payment_info"):
            return False
        adapter = self.adapters.get(str(target.get("platform") or ""))
        if adapter is None:
            return False
        platform, chat_id = str(target["platform"]), str(target["chat_id"])
        state = await self._sales_state()
        minutes = state.get("receipt_deadline_minutes") or DEFAULT_RECEIPT_MINUTES
        text = "\n\n".join((self._payment_info_text(order),
                             texts.RECEIPT_DEADLINE_NOTE.format(minutes=fmt_num(minutes))))
        self.store.set_conversation(platform, chat_id, STATE_AWAIT_RECEIPT,
                                    {"order_id": int(order_id)})
        if self.settings.bot_image_cards and order.get("items"):
            from .cards import pre_invoice_card

            info = order["payment_info"]
            await self._send_card(
                adapter, chat_id,
                lambda: pre_invoice_card(
                    shop=texts.SHOP.get("shop_name", ""), order_id=order_id,
                    items=order.get("items"), total=order.get("total"),
                    payment={"card_number": info.get("card_number"), "sheba": info.get("sheba"),
                             "owner": info.get("holder")},
                    contact=self._card_contact(),
                    currency=texts.SHOP.get("currency", "ریال"),
                    date=order.get("created_at"),
                ),
                texts.CARD_CAPTION_PRE_INVOICE.format(
                    order_id=order_id, total=fmt_num(order.get("total")),
                    currency=texts.SHOP.get("currency", "ریال")),
            )
        sent = await self._send_options(
            adapter, platform, chat_id, text,
            [[(texts.BTN_CANCEL_ORDER, f"ocx:{order_id}")], [(texts.BTN_MENU, "menu")]],
        )
        self._remember_order_message(order_id, platform, chat_id, sent, text)
        return True

    # ---- v2.9.3: an order that ended: its old buttons stop working -----------------
    @staticmethod
    def _order_messages_key(order_id) -> str:
        return f"ordermsgs:{int(order_id)}"

    def _remember_order_message(self, order_id, platform: str, chat_id, sent, text: str) -> None:
        """Keep where the message with «لغو سفارش» went, to take its buttons away
        when the order is cancelled (by staff or after the receipt deadline)."""
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        if order_id is None or message_id is None:
            return
        key = self._order_messages_key(order_id)
        try:
            kept = json.loads(self.store.get_value(key) or "[]")
        except ValueError:
            kept = []
        kept = [m for m in kept if isinstance(m, dict)][-(ORDER_MESSAGES_KEEP - 1):]
        kept.append({"platform": str(platform), "chat_id": str(chat_id),
                     "message_id": int(message_id), "text": str(text)[:3500]})
        self.store.set_value(key, json.dumps(kept, ensure_ascii=False))

    async def _retire_order_buttons(self, order_id: int) -> int:
        """The order's earlier messages lose their buttons and say it was cancelled
        (an edit without a keyboard). Returns how many were changed."""
        key = self._order_messages_key(order_id)
        try:
            kept = json.loads(self.store.get_value(key) or "[]")
        except ValueError:
            kept = []
        changed = 0
        for message in kept if isinstance(kept, list) else []:
            adapter = self.adapters.get(str(message.get("platform") or ""))
            if adapter is None or not message.get("message_id"):
                continue
            text = f"{message.get('text') or ''}\n\n{texts.ORDER_CANCELLED_MARK}".strip()
            try:
                await adapter.edit_text(message["chat_id"], int(message["message_id"]), text)
                changed += 1
            except BotApiError as exc:
                self.logger.info("platform=%s order_buttons_not_retired=%s", adapter.platform,
                                 exc.method)
        self.store.set_value(key, "[]")
        return changed

    async def _order_closed(self, platform: str, chat_id: str, order_id: int) -> bool:
        """True when this customer's order was cancelled / expired / rejected."""
        try:
            orders = await self.orders.list_for(platform, chat_id, limit=50)
        except ShopApiError:
            return False
        for order in orders:
            if int(order.get("id") or 0) == int(order_id):
                return str(order.get("status") or "") in CLOSED_ORDER_STATUSES
        return False

    async def _closed_order_tapped(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                                   order_id: int, callback_id=None) -> bool:
        """An old «لغو سفارش» / «ارسال رسید» of an order that ended: say so."""
        if not await self._order_closed(platform, chat_id, order_id):
            return False
        await self._answer_callback(adapter, callback_id,
                                    texts.ORDER_IS_CANCELLED.format(order_id=order_id), True)
        state, data = self.store.get_conversation(platform, chat_id)
        if state == STATE_AWAIT_RECEIPT and int((data or {}).get("order_id") or 0) == int(order_id):
            self.store.set_conversation(platform, chat_id, STATE_NONE, {})
        await self._send_options(adapter, platform, chat_id,
                                 texts.ORDER_IS_CANCELLED.format(order_id=order_id),
                                 [[(texts.BTN_ORDERS, "orders")], [(texts.BTN_MENU, "menu")]])
        return True

    async def _watch_sales_opening(self) -> int:
        """v2.8.0: «وقتی فروش باز شد خبرم کن» - one message per opening; the
        watcher is removed after it (asks again next time). Nobody waiting = no call."""
        if not self.store.list_sales_watch():
            self.store.set_value(SALES_SEEN_KEY, "")
            return 0
        self._shop_state = None
        state = await self._sales_state()
        if not state:
            return 0
        now_open = not state.get("closed")
        before = self.store.get_value(SALES_SEEN_KEY)
        self.store.set_value(SALES_SEEN_KEY, "1" if now_open else "0")
        if not now_open or before != "0":
            return 0
        sent = 0
        for watcher in self.store.list_sales_watch():
            adapter = self.adapters.get(str(watcher.get("platform") or ""))
            self.store.remove_sales_watch(watcher["platform"], watcher["chat_id"])
            if adapter is None:
                continue
            await self._send_text(adapter, watcher["chat_id"], texts.SALES_OPENED_NOTICE)
            sent += 1
        return sent

    # ---- «درخواست کالای ناموجود» (v2.6.0): no order, no payment, no accounting write ----
    async def _ask_item_request(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        await self._send_options(
            adapter, platform, chat_id, texts.ITEM_REQUEST_ASK, [[(texts.BTN_MENU, "menu")]],
            state=STATE_AWAIT_ITEM_REQUEST, data={}, screen=("ireq", "ireq"),
        )

    async def _item_request_text(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, text: str
    ) -> None:
        typed = " ".join(text.split())[:300]
        if len(typed) < 2:
            await self._send_text(adapter, chat_id, texts.ITEM_REQUEST_SHORT)
            return
        try:
            found = await self.api.item_request_search(typed) if len(typed) <= 100 else []
        except ShopApiRejected:
            found = []
        rows = [[(shorten(str(f.get("name") or ""), 40) or str(f.get("code")),
                  f"ireqk:{int(f['code'])}")]
                for f in found[:8] if f.get("code") is not None]
        rows.append([(texts.BTN_REQUEST_TEXT, "ireqt")])
        rows.append([(texts.BTN_MENU, "menu")])
        body = (texts.ITEM_REQUEST_PICK if found else texts.ITEM_REQUEST_NONE).format(text=typed)
        await self._send_options(
            adapter, platform, chat_id, body, rows,
            state=STATE_AWAIT_ITEM_REQUEST, data={"ireq_text": typed},
            screen=("ireq:text", "@ireqtext"),
        )

    async def _submit_item_request(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, kala_code: int | None,
        text: str,
    ) -> None:
        if not kala_code and len(text) < 2:
            await self._ask_item_request(adapter, platform, chat_id)
            return
        try:
            await self.api.create_item_request(platform, chat_id, kala_code=kala_code, text=text)
        except ShopApiRejected as exc:
            message = {429: texts.ITEM_REQUEST_TOO_MANY, 422: texts.ITEM_REQUEST_SHORT,
                       404: texts.PRODUCT_NOT_FOUND}.get(exc.status or 0, exc.message_fa)
            await self._send_options(adapter, platform, chat_id, message,
                                     [[(texts.BTN_MENU, "menu")]], state=STATE_NONE, data={})
            return
        await self._send_options(adapter, platform, chat_id, texts.ITEM_REQUEST_SENT,
                                 [[(texts.BTN_MENU, "menu")]], state=STATE_NONE, data={})

    async def _ask_receipt(
        self, adapter: PlatformAdapter, platform: str, chat_id: str, order_id: int
    ) -> None:
        self.store.set_conversation(
            platform, chat_id, STATE_AWAIT_RECEIPT, {"order_id": int(order_id)}
        )
        await self._send_options(
            adapter, platform, chat_id, texts.ASK_RECEIPT.format(order_id=order_id),
            [[(texts.BTN_MENU, "menu")]], screen=("rcpt", f"rcpt:{int(order_id)}"),
        )

    async def _ask_search(self, adapter: PlatformAdapter, platform: str, chat_id: str) -> None:
        await self._send_options(
            adapter, platform, chat_id, texts.ASK_SEARCH, [[(texts.BTN_MENU, "menu")]],
            state=STATE_AWAIT_SEARCH, data={}, screen=("search", "search"),
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
            await self._show_static(adapter, platform, chat_id, text, screen=(action, action))
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
        elif action == "back":
            await self._go_back(adapter, platform, chat_id, message_id, callback_id, status)
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
                callback_id=callback_id, edit_message_id=message_id, choose_part=True,
            )
        elif action == "prt":
            await self._show_color(
                adapter, platform, chat_id, args[0], args[1], 1,
                callback_id=callback_id, edit_message_id=message_id,
            )
        elif action == "ocx":
            if await self._closed_order_tapped(adapter, platform, chat_id, args[0], callback_id):
                return
            await self._ask_cancel_order(adapter, platform, chat_id, args[0], callback_id)
        elif action == "ocy":
            await self._cancel_order(adapter, platform, chat_id, args[0], callback_id)
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
        elif action == "pinq":
            await self._send_price_inquiry(adapter, platform, chat_id, args[0], callback_id)
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
            if await self._closed_order_tapped(adapter, platform, chat_id, args[0], callback_id):
                return
            await self._answer_callback(adapter, callback_id)
            await self._ask_receipt(adapter, platform, chat_id, args[0])
        elif action == "search":
            await self._answer_callback(adapter, callback_id)
            await self._ask_search(adapter, platform, chat_id)
        elif action == "stmt":
            await self._answer_callback(adapter, callback_id)
            if args[0] == 1 and await self._send_statement_pdf(adapter, platform, chat_id):
                return
            await self._show_statement(
                adapter, platform, chat_id, args[0], edit_message_id=message_id
            )
        elif action == "psl":
            await self._answer_callback(adapter, callback_id)
            await self._ps_models(adapter, platform, chat_id, edit_message_id=message_id)
        elif action == "psm":
            await self._answer_callback(adapter, callback_id)
            await self._ps_model(adapter, platform, chat_id, args[0], edit_message_id=message_id)
        elif action == "psc":
            await self._answer_callback(adapter, callback_id)
            await self._ps_color(adapter, platform, chat_id, args[0], args[1],
                                 edit_message_id=message_id)
        elif action == "psr":
            await self._ps_row(adapter, platform, chat_id, args[0], callback_id=callback_id,
                               edit_message_id=message_id)
        elif action == "pbr":
            await self._purchase_request(adapter, platform, chat_id, callback_id, row=args[0])
        elif action == "pbv":
            await self._purchase_request(adapter, platform, chat_id, callback_id,
                                         code=args[0], variant_id=args[1])
        elif action in ("pok", "pno"):
            await self._answer_offer(adapter, platform, chat_id, args[0], action == "pok",
                                     callback_id)
        elif action == "snot":
            self.store.add_sales_watch(platform, chat_id)
            if not self.store.get_value(SALES_SEEN_KEY):
                # asked because sales are closed now: the next «open» is the opening
                self.store.set_value(SALES_SEEN_KEY, "0")
            await self._answer_callback(adapter, callback_id, texts.SALES_NOTIFY_OK)
            await self._send_options(adapter, platform, chat_id, texts.SALES_NOTIFY_OK,
                                     [[(texts.BTN_MENU, "menu")]])
        elif action == "ireq":
            await self._answer_callback(adapter, callback_id)
            await self._ask_item_request(adapter, platform, chat_id)
        elif action == "ireqt":
            await self._answer_callback(adapter, callback_id)
            _state, data = self.store.get_conversation(platform, chat_id)
            await self._submit_item_request(adapter, platform, chat_id, None,
                                            str((data or {}).get("ireq_text") or ""))
        elif action == "ireqk":
            await self._answer_callback(adapter, callback_id)
            _state, data = self.store.get_conversation(platform, chat_id)
            await self._submit_item_request(adapter, platform, chat_id, args[0],
                                            str((data or {}).get("ireq_text") or ""))
        else:  # pragma: no cover - parse_callback already restricts actions
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)

    # ================= admin flow =========================================
    async def admin_sweep(self) -> dict:
        """Announce new pending users and new receipts to the admin chats, and
        tell customers about decisions (made here or in ShopAdmin)."""
        announced = {"users": 0, "orders": 0, "notified": 0}
        try:
            # v2.8.2: the fast events loop normally got there first (same lock)
            announced["notified"] = await self.notify_customers_from_events()
        except ShopApiError:
            pass
        try:
            announced["notified"] += await self._watch_sales_opening()
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
        if not self.settings.admin_chat_order_notices:
            return            # v2.9.1: ShopAdmin only (the admin chat = problems)
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
        decision. The first run only records the current position (no replay).
        v2.8.2: one reader at a time (the fast events loop and the sweep)."""
        lock = getattr(self, "_events_lock", None)
        if lock is None:
            lock = self._events_lock = asyncio.Lock()
        async with lock:
            return await self._read_events()

    async def _read_events(self) -> int:
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
            elif kind == ITEM_REQUEST_MESSAGE_EVENT and ref_id is not None:
                if await self._deliver_item_request_message(int(ref_id)):
                    sent += 1
            elif kind == PURCHASE_ORDER_EVENT and ref_id is not None:
                if await self._notify_purchase_order(int(ref_id)):
                    sent += 1
            elif kind == PAYMENT_INFO_EVENT and ref_id is not None:
                if await self._send_payment_info(int(ref_id), int(event.get("id") or 0)):
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
        if kind in OWNER_INFO_KINDS and not self.settings.admin_chat_order_notices:
            return False          # v2.9.1: the admin chat is for problems only
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

    async def _deliver_item_request_message(self, message_id: int) -> bool:
        """v2.6.1: a staff reply from ShopAdmin «درخواست کالا» -> the customer, on the
        messenger the request came from; the outcome goes back to shopapi (ShopAdmin
        shows «ارسال شد» or the error). Each reply is delivered at most once."""
        marker = "ireqmsg"
        if self.store.is_announced(marker, message_id):
            return False
        try:
            msg = await self.api.admin_get_item_request_message(message_id)
        except ShopApiError:
            return False
        if not isinstance(msg, dict) or msg.get("status") != "pending":
            self.store.mark_announced(marker, message_id, "", "")
            return False
        platform = str(msg.get("platform") or "")
        chat_id = str(msg.get("chat_id") or "")
        self.store.mark_announced(marker, message_id, platform, chat_id)
        adapter = self.adapters.get(platform)
        ok, error = False, ""
        if adapter is None or not chat_id:
            error = f"ربات پیام‌رسان «{platform or '-'}» روی سرور فعال نیست."
        else:
            product = str(msg.get("product_name") or msg.get("request_text") or "").strip()
            body = texts.ITEM_REQUEST_REPLY.format(
                product=f" («{shorten(product, 60)}»)" if product else "",
                text=str(msg.get("text") or ""),
            )
            markup = None
            if msg.get("purpose") == "offer" and msg.get("offer_price_rial"):
                body, markup = self._offer_message(adapter, msg, message_id)
            try:
                await adapter.send_text(chat_id, body, markup)
                ok = True
            except BotApiError as exc:
                error = ("پیام‌رسان در دسترس نبود (اینترنت سرور)." if exc.network else
                         f"پیام‌رسان پیام را نپذیرفت: {shorten(str(exc.description), 200)}")
                self.logger.warning("platform=%s item_request_reply_failed", platform)
        try:
            await self.api.admin_item_request_message_result(message_id, ok, error)
        except ShopApiError:
            pass
        return ok

    def _offer_message(self, adapter: PlatformAdapter, msg: dict,
                       message_id: int) -> tuple[str, dict | None]:
        """v2.9.2: the price staff offered, with «تأیید و خرید» / «نمی‌خواهم». The
        buttons carry the staff message id: an older offer's buttons are refused."""
        price = float(msg.get("offer_price_rial") or 0)
        qty = float(msg.get("qty") or 1)
        name = " — ".join(p for p in (str(msg.get("product_name") or "").strip(),
                                      str(msg.get("color") or "").strip(),
                                      str(msg.get("part") or "").strip()) if p)
        currency = texts.SHOP.get("currency", "ریال")
        # v2.9.3: «قیمت امروز این کالا»; quantity / total only for more than one,
        # staff's own words (from «پیام به مشتری») under it
        qty_line = texts.PURCHASE_OFFER_QTY.format(qty=fmt_num(qty), total=fmt_num(qty * price),
                                                   currency=currency) if qty > 1 else ""
        note = str(msg.get("note") or "").strip()
        note_line = texts.PURCHASE_OFFER_NOTE.format(note=note) if note else ""
        body = texts.PURCHASE_OFFER.format(
            name=shorten(name, 80) or "کالای درخواستی", qty=fmt_num(qty),
            price=fmt_num(price), total=fmt_num(qty * price), currency=currency,
            qty_line=qty_line, note=note_line)
        self.store.mark_announced("offer", int(message_id), str(msg.get("platform") or ""),
                                  str(msg.get("chat_id") or ""),
                                  {"request_id": int(msg.get("request_id") or 0),
                                   "price": int(price)})
        rows = [[(texts.BTN_OFFER_ACCEPT, f"pok:{int(message_id)}"),
                 (texts.BTN_OFFER_DECLINE, f"pno:{int(message_id)}")]]
        markup = self._markup(adapter, rows)
        return self._flatten(body, markup, rows), markup

    async def _answer_offer(self, adapter: PlatformAdapter, platform: str, chat_id: str,
                            message_id: int, accept: bool, callback_id=None) -> None:
        """v2.9.2: «تأیید و خرید» -> the order at the offered price (staff send the
        payment details next); «نمی‌خواهم» -> the request is closed."""
        notice = self.store.get_notice("offer", int(message_id))
        if not notice or str(notice.get("platform")) != str(platform) \
                or str(notice.get("chat_id")) != str(chat_id):
            await self._answer_callback(adapter, callback_id, texts.BAD_CALLBACK)
            return
        payload = notice.get("payload") or {}
        try:
            result = await self.api.admin_answer_offer(int(payload.get("request_id") or 0),
                                                       accept, int(payload.get("price") or 0))
        except ShopApiRejected as exc:
            detail = str(exc.detail or "").lower()
            text = (self._sales_closed_text(await self._sales_state())
                    if "sales are closed" in detail else texts.PURCHASE_OFFER_GONE)
            await self._answer_callback(adapter, callback_id)
            await self._send_options(adapter, platform, chat_id, text,
                                     [[(texts.BTN_MENU, "menu")]])
            return
        except ShopApiError:
            await self._answer_callback(adapter, callback_id, texts.SERVICE_UNAVAILABLE, True)
            return
        await self._answer_callback(adapter, callback_id)
        order = (result or {}).get("order") if isinstance(result, dict) else None
        if accept and isinstance(order, dict) and order.get("id"):
            # the usual «سفارش ثبت شد» message (also sent by the events feed: once)
            if await self._notify_purchase_order(int(order["id"])):
                return
            await self._send_options(adapter, platform, chat_id, texts.PURCHASE_OFFER_ACCEPTED,
                                     [[(texts.BTN_MENU, "menu")]])
            return
        await self._send_options(adapter, platform, chat_id, texts.PURCHASE_OFFER_DECLINED,
                                 [[(texts.BTN_MENU, "menu")]])

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
            text = getattr(texts, ORDER_EVENT_TEXTS[kind]).format(order_id=ref_id, reason="")
            if kind == "order_shipped":
                text = await self._shipped_text(ref_id, text)
            elif kind == "order_cancelled_by_staff":
                text = await self._staff_cancel_text(ref_id)
        self.store.mark_announced(
            marker, ref_id, str((target or {}).get("platform") or ""),
            (target or {}).get("chat_id") or "",
        )
        if not target:
            return False
        if kind in INVOICE_EVENT_KINDS and await self._send_invoice_card(kind, ref_id, target, text):
            return True
        if kind in ORDER_ENDED_KINDS:
            # v2.9.3: no more waiting for payment details / a receipt for this order
            platform, chat_id = str(target.get("platform") or ""), str(target.get("chat_id") or "")
            state, data = self.store.get_conversation(platform, chat_id)
            if state == STATE_AWAIT_RECEIPT and \
                    int((data or {}).get("order_id") or 0) == int(ref_id):
                self.store.set_conversation(platform, chat_id, STATE_NONE, {})
            await self._retire_order_buttons(int(ref_id))
        await self._notify_customer(target, text)
        return True

    async def _staff_cancel_text(self, order_id: int) -> str:
        """v2.9.3: «سفارش … از طرف فروشگاه لغو شد» + the short reason staff gave."""
        reason = ""
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            order = None
        note = " ".join(str((order or {}).get("cancel_note") or "").split())
        if note:
            reason = texts.ORDER_CANCEL_REASON.format(reason=note)
        return texts.ORDER_CANCELLED_BY_STAFF.format(order_id=order_id, reason=reason)

    async def _shipped_text(self, order_id: int, text: str) -> str:
        """v2.7.0: «ارسال شد» + the courier, only when staff entered one."""
        try:
            order = await self.api.admin_get_order(int(order_id))
        except ShopApiError:
            return text
        if not isinstance(order, dict):
            return text
        name = " ".join(str(order.get("courier_name") or "").split())
        phone = str(order.get("courier_phone") or "").strip()
        if not name and not phone:
            return text
        if name and phone:
            line = texts.ORDER_SHIPPED_COURIER.format(name=name, phone=phone)
        elif name:
            line = texts.ORDER_SHIPPED_COURIER_NAME.format(name=name)
        else:
            line = texts.ORDER_SHIPPED_COURIER_PHONE.format(phone=phone)
        return f"{text}\n{line}"

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
        if not self.settings.admin_chat_order_notices:
            return            # v2.9.1: ShopAdmin only (the admin chat = problems)
        order_id = order.get("id")
        body = texts.NEW_ORDER_NOTICE.format(
            order_id=order_id, total=fmt_num(order.get("total")), items=self._items_text(order)
        )
        await self._broadcast_admin(body, [[(texts.BTN_ORDER_STATUS, f"adst:{order_id}")]])

    async def _announce_order(self, order: dict) -> None:
        if not self.settings.admin_chat_order_notices:
            return            # v2.9.1: ShopAdmin only (the admin chat = problems)
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
