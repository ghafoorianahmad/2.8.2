"""Role-based permissions (v2.7.0: two roles plus per-user ticks).

* «مدیر» (``super_admin``) — everything.
* «کاربر فروش» (``operator``, the default for new users) — orders (view, confirm a
  receipt, mark as sent with an optional courier, cancel), item requests (view,
  reply, mark handled) and customers (view only).

The server decides: after sign-in it sends the account's effective permissions
(role + the ticks a manager set in «کاربران سیستم») and :func:`client_permissions`
turns them into the names the screens check. A menu item without permission is
hidden; the same rule is enforced again by shopapi on every request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER

# --- permission names used by the screens ------------------------------------
DASHBOARD_VIEW = "dashboard.view"
CUSTOMERS_VIEW = "customers.view"
CUSTOMERS_APPROVE = "customers.approve"
CUSTOMERS_REJECT = "customers.reject"
ORDERS_VIEW = "orders.view"
ORDERS_APPROVE_PAYMENT = "orders.approve_payment"
ORDERS_REJECT_PAYMENT = "orders.reject_payment"
ORDERS_UPLOAD_RECEIPT = "orders.upload_receipt"
ORDERS_SHIP = "orders.ship"
ORDERS_CANCEL = "orders.cancel"          # v2.7.0
ORDERS_EXPIRE = "orders.expire"          # cancel overdue orders, sync invoices
ITEM_REQUESTS = "item_requests.handle"   # v2.7.0: view, reply, mark handled
SHOP_STATE = "shop.state"                # open / close phone sales
PRODUCTS_VIEW = "products.view"
REPORTS_VIEW = "reports.view"
REPORTS_EXPORT = "reports.export"
SETTINGS_VIEW = "settings.view"
SETTINGS_EDIT_CONNECTION = "settings.edit_connection"
SETTINGS_EDIT_GENERAL = "settings.edit_general"
SETTINGS_CHANGE_OWN_PASSWORD = "settings.change_own_password"
SETTINGS_VIEW_LOG = "settings.view_log"
USERS_VIEW = "users.view"
USERS_MANAGE = "users.manage"
SERVER_MANAGE = "server.manage"
PRICELIST_VIEW = "pricelist.view"
PRICELIST_MANAGE = "pricelist.manage"
PROXIES_MANAGE = "proxies.manage"
CATALOG_VIEW = "catalog.view"
CATALOG_MANAGE = "catalog.manage"
PASSWORDS_DECIDE = "passwords.decide"

#: The two roles a manager can give (most privileged first).
ALL_ROLES = (ROLE_SUPER_ADMIN, ROLE_OPERATOR)
DEFAULT_ROLE = ROLE_OPERATOR

#: shopapi permission -> what it unlocks on the screens.
SERVER_TO_CLIENT: dict[str, frozenset[str]] = {
    "orders.view": frozenset({ORDERS_VIEW}),
    "payments.decide": frozenset({ORDERS_APPROVE_PAYMENT, ORDERS_REJECT_PAYMENT,
                                  ORDERS_UPLOAD_RECEIPT}),
    "orders.ship": frozenset({ORDERS_SHIP}),
    "orders.cancel": frozenset({ORDERS_CANCEL}),
    "requests.handle": frozenset({ITEM_REQUESTS}),
    "customers.view": frozenset({CUSTOMERS_VIEW}),
    "events.view": frozenset(),
    "view": frozenset({DASHBOARD_VIEW, PRODUCTS_VIEW, REPORTS_VIEW, REPORTS_EXPORT,
                       PRICELIST_VIEW, CATALOG_VIEW}),
    "customers.decide": frozenset({CUSTOMERS_APPROVE, CUSTOMERS_REJECT}),
    "orders.expire": frozenset({ORDERS_EXPIRE}),
    "shop.state": frozenset({SHOP_STATE}),
    "pricelist.manage": frozenset({PRICELIST_MANAGE, PRICELIST_VIEW}),
    "catalog.manage": frozenset({CATALOG_MANAGE, CATALOG_VIEW}),
    "proxies.manage": frozenset({PROXIES_MANAGE}),
    "passwords.decide": frozenset({PASSWORDS_DECIDE}),
    "staff.manage": frozenset({USERS_VIEW, USERS_MANAGE}),
    "server.manage": frozenset({SERVER_MANAGE, SETTINGS_VIEW, SETTINGS_EDIT_CONNECTION,
                                SETTINGS_EDIT_GENERAL, SETTINGS_VIEW_LOG}),
}
#: Everyone may change their own password (top bar «گذرواژهٔ من»).
ALWAYS = frozenset({SETTINGS_CHANGE_OWN_PASSWORD})

#: Persian names of the server permissions (per-user ticks), in display order.
SERVER_PERMISSION_FA: dict[str, str] = {
    "orders.view": "دیدن سفارش‌ها",
    "payments.decide": "تأیید یا رد رسید پرداخت",
    "orders.ship": "ثبت «ارسال شد»",
    "orders.cancel": "لغو سفارش",
    "requests.handle": "درخواست‌های کالا (دیدن، پاسخ، رسیدگی)",
    "customers.view": "دیدن مشتریان",
    "events.view": "اعلان‌ها",
    "view": "داشبورد، کالاها، گزارش‌ها و سایر صفحه‌ها (فقط دیدن)",
    "customers.decide": "تأیید یا رد مشتری",
    "orders.expire": "لغو سفارش‌های بی‌رسید و هماهنگی فاکتورها",
    "shop.state": "باز و بسته کردن فروش",
    "pricelist.manage": "لیست قیمت",
    "catalog.manage": "گروه‌های کالا و مدل‌های سایت",
    "proxies.manage": "پراکسی‌های تلگرام",
    "passwords.decide": "درخواست‌های گذرواژه",
    "staff.manage": "کاربران سیستم",
    "server.manage": "تنظیمات و سرور فروشگاه",
}
SALES_SERVER_PERMISSIONS = frozenset({"orders.view", "payments.decide", "orders.ship",
                                      "orders.cancel", "requests.handle", "customers.view",
                                      "events.view"})
ROLE_SERVER_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: frozenset(SERVER_PERMISSION_FA),
    ROLE_OPERATOR: SALES_SERVER_PERMISSIONS,
    # earlier roles (the server maps them on start: admin -> manager, viewer -> sales)
    ROLE_ADMIN: frozenset(SERVER_PERMISSION_FA),
    ROLE_VIEWER: SALES_SERVER_PERMISSIONS,
}


def client_permissions(server_permissions: Iterable[str]) -> frozenset[str]:
    out = set(ALWAYS)
    for name in server_permissions or ():
        out |= SERVER_TO_CLIENT.get(str(name), frozenset())
    return frozenset(out)


PERMISSIONS: dict[str, frozenset[str]] = {
    role: client_permissions(perms) for role, perms in ROLE_SERVER_PERMISSIONS.items()
}


def role_permissions(role: str | None) -> frozenset[str]:
    return PERMISSIONS.get(str(role or ""), frozenset())


def has_permission(role: str | None, permission: str) -> bool:
    return permission in role_permissions(role)


def is_sales_role(role: str | None) -> bool:
    return str(role or "") in (ROLE_OPERATOR, ROLE_VIEWER)


@dataclass(frozen=True)
class Principal:
    """The signed-in internal user."""

    user_id: int
    username: str
    full_name: str
    role: str
    #: v2.7.0: the effective screen permissions from the server (role + ticks);
    #: ``None`` = an older server: the role table decides.
    permissions: Optional[frozenset] = None

    @property
    def can(self) -> "PermissionCheck":
        return PermissionCheck(self.role, self.permissions)

    @property
    def is_super_admin(self) -> bool:
        return self.role == ROLE_SUPER_ADMIN


class PermissionCheck:
    """``principal.can(ORDERS_APPROVE_PAYMENT)`` reads nicely at call sites."""

    __slots__ = ("_role", "_permissions")

    def __init__(self, role: str, permissions: Optional[frozenset] = None) -> None:
        self._role = role
        self._permissions = permissions

    def __call__(self, permission: str) -> bool:
        if self._permissions is not None:
            return permission in self._permissions
        return has_permission(self._role, permission)
