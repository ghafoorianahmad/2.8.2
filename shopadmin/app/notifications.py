"""Desktop notifications: new customers, new orders and new payment receipts.

The server keeps a small event feed (``GET /admin/events``) that holds only an
event kind and an id — no names, no phone numbers. :class:`EventWatcher` polls
it in the background with its own copy of the session token, and
:class:`TrayNotifier` turns new items into a Windows notification, a sound and
the unread counters shown in the sidebar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .api_client import ApiAuthError, ApiError, ShopApiClient
from .logging_setup import get_logger
from .persian import to_persian_digits

log = get_logger("notify")

KIND_CUSTOMER = "customer_registered"
KIND_ORDER = "order_created"
KIND_RECEIPT = "receipt_uploaded"
KIND_PASSWORD = "password_request"
#: Kinds that ask a person to act; the rest only refresh the screens.
ATTENTION_KINDS = (KIND_CUSTOMER, KIND_ORDER, KIND_RECEIPT, KIND_PASSWORD)

#: Server health (REQUIREMENTS §8): ``health_<check>_down`` / ``health_<check>_up``.
HEALTH_PREFIX = "health_"
HEALTH_LABELS = {
    "sql": "پایگاه دادهٔ حسابداری (SQL)",
    "bot": "ربات بله",
    "bale": "اتصال ربات به بله",
    "tg": "کارگر تلگرام (لیست قیمت)",
    "backup": "پشتیبان‌گیری روزانه",
}
#: Problems reported by other code paths, shown the same way.
SERVER_WARNINGS = {
    "pricelist_held": "لیست قیمت جدید به‌خاطر تغییر زیاد قیمت نگه داشته شد؛ بررسی و تأیید کنید.",
    "pricelist_failed": "لیست قیمت جدید خوانده نشد؛ قیمت‌های قبلی همچنان فعال است.",
    "proxies_all_dead": "هیچ پراکسی تلگرامی کار نمی‌کند؛ یک پراکسی تازه وارد کنید.",
    "telegram_login_required": "کارگر تلگرام نیاز به ورود دوباره دارد.",
    "telegram_unreachable": "کارگر تلگرام به تلگرام وصل نمی‌شود.",
    "security_alert": "فعالیت مشکوک (ربات یا ورود به کنسول) دیده شد؛ گزارش ممیزی را ببینید.",
    "model_review": "بررسی شبانه: کالای یک مدل سایت در حسابداری پیدا نشد یا نامش عوض شده؛ "
                    "مدل تا تأیید شما از دید مشتری پنهان است.",
    # v2.5.0: nothing is ever deleted in the accounting DB; a person decides there.
    "accounting_duplicate_order": "شمارهٔ سفارش حسابداری تکراری شد (برنامهٔ دیگری هم‌زمان همان "
                                  "شماره را نوشت). چیزی حذف نشده؛ در «سازه حساب» بررسی کنید.",
    "order_timeout_written": "مهلت رسید یک سفارش گذشته ولی آن سفارش قبلاً در حسابداری ثبت شده؛ "
                             "لغو نشد. در «سازه حساب» تصمیم بگیرید.",
}

#: Sales window changes (v2.5.0): informational, no counter.
SALES_NOTICES = {
    "sales_opened": "فروش گوشی با لیست قیمت جدید باز شد.",
    "sales_closed": "فروش گوشی بسته شد (ساعت پایان فروش، جمعه یا نرسیدن لیست قیمت جدید)؛ "
                    "لوازم جانبی قابل سفارش است.",
    "sales_opened_manual": "فروش گوشی به‌دست یکی از کاربران باز شد.",
    "sales_closed_manual": "فروش گوشی به‌دست یکی از کاربران بسته شد.",
    "sales_holiday": "امروز تعطیل اعلام شد؛ فروش گوشی تا صبح فردا بسته است.",
}
KIND_AUTO_CANCELLED = "order_auto_cancelled"

#: Which page (and filter) a notification opens.
TARGETS = {
    KIND_CUSTOMER: ("customers", "pending"),
    KIND_ORDER: ("orders", "awaiting_payment"),
    KIND_RECEIPT: ("orders", "receipt_uploaded"),
    KIND_PASSWORD: ("password_requests", ""),
    "pricelist_held": ("pricelist", ""),
    "pricelist_failed": ("pricelist", ""),
    "proxies_all_dead": ("pricelist", ""),
    "model_review": ("catalog", "review"),
    KIND_AUTO_CANCELLED: ("orders", "cancelled"),
    "accounting_duplicate_order": ("orders", "written"),
    "order_timeout_written": ("orders", "awaiting_payment"),
    # the accounting program was opened (sazeh_watch)
    "sazeh_orders": ("orders", "awaiting_payment"),
    "sazeh_customers": ("customers", "pending"),
}


@dataclass(frozen=True)
class Notice:
    kind: str
    title: str
    body: str
    ref_id: Optional[int]
    warning: bool = False

    @property
    def is_server(self) -> bool:
        return self.kind.startswith(HEALTH_PREFIX) or self.kind in SERVER_WARNINGS

    @property
    def target(self) -> tuple[str, str]:
        return TARGETS.get(self.kind, ("dashboard", ""))


def notice_for(event: dict) -> Optional[Notice]:
    """Persian text for one feed item, or ``None`` for kinds nobody must act on."""
    kind = str(event.get("kind") or "")
    ref = event.get("ref_id")
    ref_fa = to_persian_digits(ref) if ref is not None else ""
    if kind == KIND_CUSTOMER:
        return Notice(kind, "مشتری جدید", "یک مشتری جدید ثبت‌نام کرده و منتظر تأیید است.", ref)
    if kind == KIND_ORDER:
        return Notice(kind, "سفارش جدید", f"سفارش شمارهٔ {ref_fa} ثبت شد.", ref)
    if kind == KIND_RECEIPT:
        return Notice(kind, "فیش پرداخت جدید",
                      f"برای سفارش شمارهٔ {ref_fa} فیش پرداخت ارسال شد و منتظر بررسی است.", ref)
    if kind == KIND_PASSWORD:
        return Notice(kind, "درخواست گذرواژه",
                      "یکی از کاربران گذرواژه‌اش را فراموش کرده و منتظر تأیید شماست.", ref)
    if kind.startswith(HEALTH_PREFIX):
        check, _, state = kind[len(HEALTH_PREFIX):].rpartition("_")
        label = HEALTH_LABELS.get(check)
        if label is None or state not in ("down", "up"):
            return None
        if check == "backup":
            if state == "down":
                return Notice(kind, "هشدار سرور فروشگاه",
                              "پشتیبان‌گیری روزانه ناموفق بود یا عقب افتاده است.", None, warning=True)
            return Notice(kind, "سرور فروشگاه", "پشتیبان‌گیری روزانه دوباره موفق شد.", None)
        if state == "down":
            return Notice(kind, "هشدار سرور فروشگاه", f"{label} در دسترس نیست.", None, warning=True)
        return Notice(kind, "سرور فروشگاه", f"{label} دوباره کار می‌کند.", None)
    if kind in SERVER_WARNINGS:
        return Notice(kind, "هشدار سرور فروشگاه", SERVER_WARNINGS[kind], ref, warning=True)
    if kind == KIND_AUTO_CANCELLED:
        return Notice(kind, "سفارش لغو شد",
                      f"سفارش شمارهٔ {ref_fa} چون رسید پرداخت در مهلت نرسید، خودکار لغو شد.", ref)
    if kind in SALES_NOTICES:
        return Notice(kind, "وضعیت فروش گوشی", SALES_NOTICES[kind], None)
    return None


def summarize(notices: list[Notice]) -> Notice:
    """One balloon for a burst of events (e.g. after the computer wakes up)."""
    if len(notices) == 1:
        return notices[0]
    counts: dict[str, int] = {}
    for n in notices:
        counts[n.kind] = counts.get(n.kind, 0) + 1
    parts = []
    labels = {KIND_CUSTOMER: "مشتری جدید", KIND_ORDER: "سفارش جدید", KIND_RECEIPT: "فیش جدید",
              KIND_PASSWORD: "درخواست گذرواژه"}
    for kind in ATTENTION_KINDS:
        if counts.get(kind):
            parts.append(f"{to_persian_digits(counts[kind])} {labels[kind]}")
    first = notices[-1]
    return Notice(first.kind, "موارد جدید در فروشگاه", "، ".join(parts) + ".", None)


class EventWatcher(QObject):
    """Polls the server's event feed on a worker thread.

    Signals are delivered on the GUI thread. The first poll only records the
    current position, so starting the app never replays old history as new.
    """

    events_arrived = Signal(list)      # list[dict] — every new feed item
    session_lost = Signal()            # the token stopped working
    reachability_changed = Signal(bool)

    def __init__(self, base_url: str, token: str, *, interval_seconds: int = 15,
                 client: ShopApiClient | None = None, parent: QObject | None = None,
                 server_cert_pem: str = "") -> None:
        super().__init__(parent)
        self.client = client or ShopApiClient(base_url, token, timeout=10,
                                              server_cert_pem=server_cert_pem)
        self.last_id: Optional[int] = None
        self._busy = False
        self._reachable = True
        self._timer = QTimer(self)
        self._timer.setInterval(max(5, int(interval_seconds)) * 1000)
        self._timer.timeout.connect(self.poll)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self._timer.start()
        self.poll()

    def stop(self) -> None:
        self._timer.stop()

    def set_interval(self, seconds: int) -> None:
        self._timer.setInterval(max(5, int(seconds)) * 1000)

    def set_token(self, token: str) -> None:
        self.client.set_token(token)

    def poll(self) -> None:
        if self._busy:
            return
        from .ui.async_utils import run_async

        self._busy = True
        after = self.last_id

        def work() -> dict:
            return self.client.events(after=after)

        run_async(work, on_success=self._on_result, on_error=self._on_error,
                  on_done=self._done)

    # ---- callbacks (GUI thread) --------------------------------------------
    def _done(self) -> None:
        self._busy = False

    def _set_reachable(self, ok: bool) -> None:
        if ok != self._reachable:
            self._reachable = ok
            self.reachability_changed.emit(ok)

    def _on_result(self, payload: dict) -> None:
        self._set_reachable(True)
        items = list(payload.get("items") or [])
        new_last = payload.get("last_id")
        first_poll = self.last_id is None
        if isinstance(new_last, int):
            self.last_id = new_last
        if items and not first_poll:
            self.events_arrived.emit(items)

    def _on_error(self, message: str, kind: str) -> None:
        if kind == "auth":
            log.info("event feed: session no longer valid; stopping")
            self.stop()
            self.session_lost.emit()
            return
        self._set_reachable(False)

    def handle_exception(self, exc: Exception) -> None:  # pragma: no cover - debug aid
        if isinstance(exc, ApiAuthError):
            self._on_error(str(exc), "auth")
        elif isinstance(exc, ApiError):
            self._on_error(exc.message, exc.kind)


class TrayNotifier(QObject):
    """System-tray icon, Windows balloon notifications and unread counters."""

    open_requested = Signal(str, str)   # page key, filter
    quit_requested = Signal()
    counts_changed = Signal(dict)       # {kind: unread count}

    def __init__(self, store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.unread: dict[str, int] = {k: 0 for k in ATTENTION_KINDS}
        self._last_notice: Optional[Notice] = None
        self.tray = None
        self._build_tray()

    def _build_tray(self) -> None:
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("no system tray on this desktop; notifications stay in-app")
            return
        from .ui import theme

        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        self.tray.setToolTip("مدیریت فروشگاه")
        menu = QMenu()
        menu.setLayoutDirection(menu.layoutDirection().RightToLeft)
        open_action = menu.addAction("باز کردن مدیریت فروشگاه")
        open_action.triggered.connect(lambda: self.open_requested.emit("", ""))
        menu.addSeparator()
        quit_action = menu.addAction("خروج کامل از برنامه")
        quit_action.triggered.connect(self.quit_requested.emit)
        self._menu = menu  # keep a reference: Qt does not own it
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.messageClicked.connect(self._on_message_clicked)
        self.tray.show()

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit("", "")

    def _on_message_clicked(self) -> None:
        notice = self._last_notice
        page, filter_key = notice.target if notice else ("", "")
        self.open_requested.emit(page, filter_key)

    # ---- incoming events -----------------------------------------------------
    def handle_events(self, events: list[dict]) -> list[Notice]:
        notices = [n for n in (notice_for(e) for e in events) if n is not None]
        if not notices:
            return []
        attention = [n for n in notices if n.kind in ATTENTION_KINDS]
        server = [n for n in notices if n.is_server]
        for n in attention:
            self.unread[n.kind] = self.unread.get(n.kind, 0) + 1
        if attention:
            self.counts_changed.emit(dict(self.unread))
        # A server problem matters more than a counter: it is the one shown.
        shown = server[-1] if server else summarize(attention)
        self.show_notice(shown)
        self._update_tooltip()
        return notices

    def show_notice(self, notice: Notice) -> None:
        """One Windows balloon (and the sound), clicking it opens ``notice.target``."""
        self._last_notice = notice
        if self.store.get_setting("notify_desktop", True) and self.tray is not None:
            from PySide6.QtWidgets import QSystemTrayIcon

            icon = (QSystemTrayIcon.MessageIcon.Warning if notice.warning
                    else QSystemTrayIcon.MessageIcon.Information)
            self.tray.showMessage(notice.title, notice.body, icon, 10000 if notice.warning else 8000)
        if self.store.get_setting("notify_sound", True):
            play_notification_sound()

    def mark_seen(self, *kinds: str) -> None:
        changed = False
        for kind in kinds or tuple(self.unread):
            if self.unread.get(kind):
                self.unread[kind] = 0
                changed = True
        if changed:
            self.counts_changed.emit(dict(self.unread))
            self._update_tooltip()

    def total_unread(self) -> int:
        return sum(self.unread.values())

    def _update_tooltip(self) -> None:
        if self.tray is None:
            return
        total = self.total_unread()
        text = "مدیریت فروشگاه"
        if total:
            text += f" — {to_persian_digits(total)} مورد جدید"
        self.tray.setToolTip(text)

    def hide(self) -> None:
        if self.tray is not None:
            self.tray.hide()


def play_notification_sound() -> None:
    """The standard Windows notification sound; silently skipped elsewhere."""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001 - a sound must never break anything
        pass
