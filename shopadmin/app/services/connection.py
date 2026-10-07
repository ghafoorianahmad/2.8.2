"""Watch whether the shop server answers. Probe only — never launch anything.

The management console is a pure client: the server (``ShopServer``: API +
bots) runs separately on the server computer and is the only component that
touches the accounting database. This module therefore never looks for,
starts or stops a server program, not even when the configured address is
``127.0.0.1``. It only asks the configured address for ``/health`` and
reports the result, with a clear Persian message and a retry when it is down.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal

from ..api_client import ApiError, ShopApiClient
from ..logging_setup import get_logger

log = get_logger("connection")

MSG_SERVER_UNREACHABLE = "سرور در دسترس نیست"


def unreachable_message(base_url: str) -> str:
    """The Persian explanation shown when the server does not answer."""
    # U+2066/U+2069 isolate the Latin address so RTL text around it stays in order.
    address = f"⁦{base_url}⁩" if base_url else "(تنظیم نشده)"
    return (
        f"{MSG_SERVER_UNREACHABLE}. نشانی سرور:\n{address}\n"
        "رایانهٔ سرور باید روشن و در همین شبکه باشد؛ سپس «تلاش دوباره» را بزنید. "
        "اگر نشانی سرور عوض شده، آن را در «تنظیمات» اصلاح کنید."
    )


class ConnectionState(str, Enum):
    """What the top-bar indicator shows."""

    CHECKING = "checking"
    CONNECTED = "connected"
    OFFLINE = "offline"

    @property
    def label_fa(self) -> str:
        return {
            ConnectionState.CHECKING: "سرور: در حال بررسی",
            ConnectionState.CONNECTED: "سرور: متصل",
            ConnectionState.OFFLINE: MSG_SERVER_UNREACHABLE,
        }[self]


def probe(base_url: str, server_cert_pem: str = "", *, timeout: float = 4.0) -> bool:
    """True when ``base_url`` answers ``/health``. Never raises."""
    if not base_url:
        return False
    client = ShopApiClient(base_url, "", timeout=timeout, server_cert_pem=server_cert_pem)
    try:
        client.health()
        return True
    except ApiError:
        return False
    except Exception:  # noqa: BLE001 - a probe must never crash the app
        return False
    finally:
        client.close()


class ServerMonitor(QObject):
    """Qt-facing reachability check; the probe runs on a worker thread."""

    state_changed = Signal(object)   # ConnectionState
    unreachable = Signal(str)        # Persian message incl. the address

    def __init__(self, base_url: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url
        self.server_cert_pem = ""
        self._state = ConnectionState.CHECKING
        self._busy = False

    @property
    def state(self) -> ConnectionState:
        return self._state

    def set_base_url(self, base_url: str, server_cert_pem: str | None = None) -> None:
        self.base_url = base_url
        if server_cert_pem is not None:
            self.server_cert_pem = server_cert_pem

    def _set_state(self, state: ConnectionState) -> None:
        if state == self._state:
            return
        self._state = state
        log.info("server state -> %s", state.value)
        self.state_changed.emit(state)

    def check_async(self, *, report: bool = True) -> None:
        """Probe the server. With ``report``, an outage emits :attr:`unreachable`."""
        if self._busy:
            return
        self._busy = True
        self._set_state(ConnectionState.CHECKING)
        base_url, pem = self.base_url, self.server_cert_pem

        def done(reachable: bool) -> None:
            if reachable:
                self._set_state(ConnectionState.CONNECTED)
                return
            log.warning("the server at the configured address does not answer")
            self._set_state(ConnectionState.OFFLINE)
            if report:
                self.unreachable.emit(unreachable_message(base_url))

        def failed(_message: str, _kind: str) -> None:
            done(False)

        from ..ui.async_utils import run_async

        run_async(lambda: probe(base_url, pem), on_success=done, on_error=failed,
                  on_done=self._mark_idle)

    def _mark_idle(self) -> None:
        self._busy = False

    def shutdown(self) -> None:
        """Nothing to stop: the console never owns a server process."""
