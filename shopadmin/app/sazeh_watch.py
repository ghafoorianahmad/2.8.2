"""Tray reminder when the accounting program starts (REQUIREMENTS §8).

When «سازه حساب» is opened on this computer, the owner is usually about to
work on invoices - a good moment for "X new orders, Y customers awaiting
approval". :class:`SazehWatcher` checks the running programs every few seconds
(on a worker thread) and emits ``started`` once each time the program goes from
not running to running. Its exe name carries the version
(``Sazeh Hesab Integrated 1405.06.05.exe``), so names are matched by prefix;
the prefixes are a setting (``sazeh_process_names``).
"""
from __future__ import annotations

import csv
import io
import subprocess
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .logging_setup import get_logger
from .persian import to_persian_digits

log = get_logger("sazeh_watch")

DEFAULT_PREFIXES = "Sazeh Hesab, SazehHesab"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def parse_prefixes(text: str) -> list[str]:
    return [p.strip().lower() for p in (text or "").split(",") if p.strip()]


def running_process_names() -> list[str]:
    """Image names of the running processes (``tasklist``; no extra packages)."""
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                            errors="replace", timeout=20, creationflags=CREATE_NO_WINDOW)
    names = []
    for row in csv.reader(io.StringIO(result.stdout or "")):
        if row:
            names.append(row[0])
    return names


def is_running(names: Iterable[str], prefixes: list[str]) -> bool:
    return any(name.strip().lower().startswith(prefix) for name in names for prefix in prefixes)


def pending_summary(api) -> tuple[int, int]:
    """(orders that need attention, customers awaiting approval)."""
    orders = len(api.list_orders("awaiting_payment")) + len(api.list_orders("receipt_uploaded"))
    customers = len(api.list_customers("pending"))
    return orders, customers


def summary_text(orders: int, customers: int) -> str:
    if not orders and not customers:
        return "سفارش یا مشتری منتظری در فروشگاه نیست."
    parts = []
    if orders:
        parts.append(f"{to_persian_digits(orders)} سفارش جدید")
    if customers:
        parts.append(f"{to_persian_digits(customers)} مشتری در انتظار تأیید")
    return "، ".join(parts) + ". برای دیدن، اینجا را بزنید."


class SazehWatcher(QObject):
    """Emits ``started`` when the accounting program appears."""

    started = Signal()

    def __init__(self, prefixes: str = DEFAULT_PREFIXES, *, interval_seconds: int = 10,
                 lister: Callable[[], list[str]] = running_process_names,
                 parent: QObject | None = None, run_in_thread: bool = True) -> None:
        super().__init__(parent)
        self.prefixes = parse_prefixes(prefixes) or parse_prefixes(DEFAULT_PREFIXES)
        self.lister = lister
        #: None until the first check: a program already open at start is not "started".
        self.was_running: Optional[bool] = None
        self._busy = False
        self._run_in_thread = run_in_thread
        self.timer = QTimer(self)
        self.timer.setInterval(max(2, int(interval_seconds)) * 1000)
        self.timer.timeout.connect(self.check)

    def start(self) -> None:
        self.timer.start()
        self.check()

    def stop(self) -> None:
        self.timer.stop()

    def check(self) -> None:
        if self._busy:
            return
        if not self._run_in_thread:
            self._apply(self._probe())
            return
        from .ui.async_utils import run_async

        self._busy = True

        def done(result) -> None:
            self._busy = False
            self._apply(result)

        def failed(_message: str, _kind: str) -> None:
            self._busy = False

        run_async(self._probe, on_success=done, on_error=failed)

    def _probe(self) -> Optional[bool]:
        try:
            return is_running(self.lister(), self.prefixes)
        except Exception as exc:  # noqa: BLE001 - try again next tick
            log.debug("process list failed: %s", type(exc).__name__)
            return None

    def _apply(self, running: Optional[bool]) -> None:
        if running is None:
            return
        previous, self.was_running = self.was_running, running
        if running and previous is False:
            log.info("the accounting program was started")
            self.started.emit()
