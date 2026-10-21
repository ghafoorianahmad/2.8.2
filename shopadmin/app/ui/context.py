"""Shared runtime state handed to every page and dialog.

Holds the local store, the shopapi client, the signed-in principal and the
resolved shopapi system information (including the dry-run banner flag).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..api_client import ShopApiClient, SystemInfo
from ..auth import AuthService
from ..logging_setup import get_logger
from ..permissions import Principal, has_permission
from ..store import Store

log = get_logger("context")


@dataclass
class AppContext(QObject):
    """Everything the UI needs, plus the signals that keep pages in sync."""

    store: Store
    auth: AuthService
    api: ShopApiClient
    principal: Optional[Principal] = None
    system_info: SystemInfo = field(default_factory=SystemInfo.unavailable)
    connection_ok: bool = False
    #: TrayNotifier (unread counters, desktop notifications); None in tests.
    notifier: Optional[object] = None
    #: v2.8.3: ids of the orders this user is reminded to send payment details for
    payment_info_due: frozenset = field(default_factory=frozenset)
    #: v2.9.0: closes and reopens the program (a new look); None in tests
    restart_app: Optional[object] = None

    # emitted when the shopapi connection state changes (green/red dot)
    connection_changed = Signal(bool)
    # emitted when /admin/system-info changed the dry-run assumption
    system_info_changed = Signal(object)
    # emitted after any write action so refreshable pages can reload
    data_changed = Signal()
    # emitted with the raw server events (new customer / order / receipt…)
    server_events = Signal(list)

    def __post_init__(self) -> None:
        super().__init__()

    # ---- permissions -----------------------------------------------------
    @property
    def role(self) -> str:
        return self.principal.role if self.principal else ""

    def can(self, permission: str) -> bool:
        """Permission check behind every menu item and privileged button: the
        server's list for this account (role + per-user ticks), else the role."""
        if self.principal is not None and self.principal.permissions is not None:
            return permission in self.principal.permissions
        return has_permission(self.role, permission)

    @property
    def display_name(self) -> str:
        if self.principal is None:
            return ""
        return self.principal.full_name or self.principal.username

    # ---- settings --------------------------------------------------------
    @property
    def auto_refresh_seconds(self) -> int:
        return self.store.get_int_setting("auto_refresh_seconds", 30, minimum=0, maximum=3600)

    @property
    def session_timeout_minutes(self) -> int:
        return self.store.get_int_setting("session_timeout_minutes", 30, minimum=1, maximum=480)

    @property
    def dry_run_mode(self) -> bool:
        """True when shopapi will NOT really write to the accounting system.

        Only meaningful when the server actually reports the flag; an older
        build without ``/admin/system-info`` must not raise a false alarm.
        """
        if not self.connection_ok:
            return False
        if not self.system_info.write_mode_known:
            return False
        return not self.system_info.accounting_write_enabled

    # ---- connection state ------------------------------------------------
    def set_connection(self, ok: bool) -> None:
        if ok == self.connection_ok:
            return
        self.connection_ok = ok
        self.connection_changed.emit(ok)

    def apply_system_info(self, info: SystemInfo) -> None:
        self.system_info = info
        self.set_connection(info.reachable)
        self.system_info_changed.emit(info)

    def mark_offline(self) -> None:
        self.system_info = SystemInfo.unavailable()
        self.set_connection(False)
        self.system_info_changed.emit(self.system_info)

    def mark_seen(self, *kinds: str) -> None:
        """Clear unread notification counters (when the user opens that list)."""
        if self.notifier is not None:
            self.notifier.mark_seen(*kinds)

    def audit(self, action: str, detail: str = "") -> None:
        actor = self.principal.username if self.principal else "system"
        self.store.audit(actor, action, detail)
