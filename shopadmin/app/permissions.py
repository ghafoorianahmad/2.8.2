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
ITEM_REQUESTS = "item_requests.handle"   # v2.7.0: reply, note, status, stock
ITEM_REQUESTS_VIEW = "item_requests.view"  # v2.8.2: «درخواست کالا — دیدن»
ORDERS_PAYMENT_INFO = "orders.payment_info"  # v2.8.2: «ارسال اطلاعات پرداخت»
GROUPS_VIEW = "groups.view"              # v2.8.2: «گروه‌های کالا» (own section)
GROUPS_MANAGE = "groups.manage"
SALES_VIEW = "sales.view"                # v2.8.2: phone-sales state
PASSWORDS_VIEW = "passwords.view"
SERVER_VIEW = "server.view"              # v2.8.2: «تنظیمات سرور فروشگاه — دیدن»
ORDERS_ASSIGN = "orders.assign"          # v2.8.0: hand any order / request to a colleague
ARCHIVE_VIEW = "archive.view"            # v2.8.0: «بایگانی» (own rows; the manager: all)
ACTIVITY_VIEW = "activity.view"          # v2.8.0: «گزارش فعالیت» (manager only)
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

#: v2.8.2: every section (same rows as shopapi ``staff.ALL_SECTIONS``):
#: (section, Persian name, has «دیدن», has «تغییر»).
ALL_SECTIONS: tuple[tuple[str, str, bool, bool], ...] = (
    ("dashboard", "داشبورد", True, False),
    ("orders", "سفارش‌ها و رسیدها (تأیید/رد رسید، اطلاعات پرداخت، ارسال، لغو)", True, True),
    ("requests", "درخواست کالا (پیام، یادداشت، تأیید موجودی)", True, True),
    ("customers", "مشتریان (تأیید و رد مشتری)", True, True),
    ("assign", "ارجاع کار به همکار", False, True),
    ("archive", "بایگانی", True, False),
    ("products", "محصولات و موجودی", True, False),
    ("groups", "گروه‌های کالا", True, True),
    ("pricelist", "لیست قیمت، نگاشت و پراکسی", True, True),
    ("models", "مدل‌های سایت", True, True),
    ("sales", "فروش گوشی (باز و بسته کردن)", True, True),
    ("reports", "گزارش‌ها", True, False),
    ("activity", "گزارش فعالیت", True, False),
    ("passwords", "درخواست‌های گذرواژه", True, True),
    ("staff", "کاربران سیستم و دسترسی‌ها", True, True),
    ("server", "تنظیمات سرور فروشگاه", True, True),
)
SECTION_PERMISSIONS = frozenset(
    [f"{k}.view" for k, _l, v, _e in ALL_SECTIONS if v]
    + [f"{k}.edit" for k, _l, _v, e in ALL_SECTIONS if e])
#: v2.8.3: the daily work is always on for every user and is not in the table
#: (each user still sees only their own work and new free work).
ALWAYS_SECTIONS = frozenset({"dashboard", "orders", "requests", "customers", "assign",
                             "archive", "reports"})
ALWAYS_SERVER_PERMISSIONS = frozenset(
    name for name in SECTION_PERMISSIONS if name.split(".", 1)[0] in ALWAYS_SECTIONS)
#: The permission table of «کاربران سیستم» (shopapi ``staff.SECTIONS``).
SECTIONS: tuple[tuple[str, str, bool, bool], ...] = tuple(
    row for row in ALL_SECTIONS if row[0] not in ALWAYS_SECTIONS)
#: Ticks shown in the table.
TABLE_PERMISSIONS = SECTION_PERMISSIONS - ALWAYS_SERVER_PERMISSIONS

_ORDERS_EDIT = frozenset({ORDERS_APPROVE_PAYMENT, ORDERS_REJECT_PAYMENT, ORDERS_UPLOAD_RECEIPT,
                          ORDERS_SHIP, ORDERS_CANCEL, ORDERS_EXPIRE, ORDERS_PAYMENT_INFO})

#: shopapi permission -> what it unlocks on the screens.
SERVER_TO_CLIENT: dict[str, frozenset[str]] = {
    # ---- v2.8.2 sections («دیدن» / «تغییر») ----
    "dashboard.view": frozenset({DASHBOARD_VIEW}),
    "orders.view": frozenset({ORDERS_VIEW}),
    "orders.edit": _ORDERS_EDIT,
    "requests.view": frozenset({ITEM_REQUESTS_VIEW}),
    "requests.edit": frozenset({ITEM_REQUESTS}),
    "customers.view": frozenset({CUSTOMERS_VIEW}),
    "customers.edit": frozenset({CUSTOMERS_APPROVE, CUSTOMERS_REJECT}),
    "assign.edit": frozenset({ORDERS_ASSIGN}),
    "archive.view": frozenset({ARCHIVE_VIEW}),
    "products.view": frozenset({PRODUCTS_VIEW}),
    "groups.view": frozenset({GROUPS_VIEW}),
    "groups.edit": frozenset({GROUPS_MANAGE}),
    "pricelist.view": frozenset({PRICELIST_VIEW}),
    "pricelist.edit": frozenset({PRICELIST_MANAGE, PROXIES_MANAGE}),
    "models.view": frozenset({CATALOG_VIEW}),
    "models.edit": frozenset({CATALOG_MANAGE}),
    "sales.view": frozenset({SALES_VIEW}),
    "sales.edit": frozenset({SHOP_STATE}),
    "reports.view": frozenset({REPORTS_VIEW, REPORTS_EXPORT}),
    "activity.view": frozenset({ACTIVITY_VIEW}),
    "passwords.view": frozenset({PASSWORDS_VIEW}),
    "passwords.edit": frozenset({PASSWORDS_DECIDE}),
    "staff.view": frozenset({USERS_VIEW}),
    "staff.edit": frozenset({USERS_MANAGE}),
    "server.view": frozenset({SERVER_VIEW}),
    "server.edit": frozenset({SERVER_MANAGE, SETTINGS_EDIT_CONNECTION}),
    "events.view": frozenset(),
    # ---- names of a v2.7.0 – v2.8.1 server (until it is updated) ----
    "orders.assign": frozenset({ORDERS_ASSIGN}),
    "payments.decide": frozenset({ORDERS_APPROVE_PAYMENT, ORDERS_REJECT_PAYMENT,
                                  ORDERS_UPLOAD_RECEIPT}),
    "orders.ship": frozenset({ORDERS_SHIP}),
    "orders.cancel": frozenset({ORDERS_CANCEL}),
    "requests.handle": frozenset({ITEM_REQUESTS, ITEM_REQUESTS_VIEW}),
    "view": frozenset({DASHBOARD_VIEW, PRODUCTS_VIEW, REPORTS_VIEW, REPORTS_EXPORT,
                       PRICELIST_VIEW, CATALOG_VIEW, GROUPS_VIEW, SALES_VIEW}),
    "customers.decide": frozenset({CUSTOMERS_APPROVE, CUSTOMERS_REJECT}),
    "orders.expire": frozenset({ORDERS_EXPIRE}),
    "shop.state": frozenset({SHOP_STATE, SALES_VIEW}),
    "pricelist.manage": frozenset({PRICELIST_MANAGE, PRICELIST_VIEW}),
    "catalog.manage": frozenset({CATALOG_MANAGE, CATALOG_VIEW, GROUPS_MANAGE, GROUPS_VIEW}),
    "proxies.manage": frozenset({PROXIES_MANAGE}),
    "passwords.decide": frozenset({PASSWORDS_DECIDE, PASSWORDS_VIEW}),
    "staff.manage": frozenset({USERS_VIEW, USERS_MANAGE, ACTIVITY_VIEW}),
    "server.manage": frozenset({SERVER_MANAGE, SERVER_VIEW, SETTINGS_EDIT_CONNECTION}),
}
#: v2.8.2: «تنظیمات برنامه» (this computer: intervals, notifications, look, log)
#: is for everyone; only pointing the computer at another server needs
#: «تنظیمات سرور فروشگاه — تغییر». Everyone changes their own password.
ALWAYS = frozenset({SETTINGS_CHANGE_OWN_PASSWORD, SETTINGS_VIEW, SETTINGS_EDIT_GENERAL,
                    SETTINGS_VIEW_LOG})

#: Persian names of the server permissions, in display order (v2.8.2: per section).
SERVER_PERMISSION_FA: dict[str, str] = {}
for _key, _label, _view, _edit in ALL_SECTIONS:
    if _view:
        SERVER_PERMISSION_FA[f"{_key}.view"] = f"{_label} — دیدن"
    if _edit:
        SERVER_PERMISSION_FA[f"{_key}.edit"] = f"{_label} — تغییر"
SALES_SERVER_PERMISSIONS = ALWAYS_SERVER_PERMISSIONS
ROLE_SERVER_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: SECTION_PERMISSIONS,
    ROLE_OPERATOR: SALES_SERVER_PERMISSIONS,
    # earlier roles (the server maps them on start: admin -> manager, viewer -> sales)
    ROLE_ADMIN: SECTION_PERMISSIONS,
    ROLE_VIEWER: SALES_SERVER_PERMISSIONS,
}


def with_implied(names) -> set[str]:
    """«تغییر» includes «دیدن» of the same section."""
    out = set(names)
    for name in list(out):
        if name.endswith(".edit") and f"{name[:-5]}.view" in SECTION_PERMISSIONS:
            out.add(f"{name[:-5]}.view")
    return out


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

    @property
    def is_manager(self) -> bool:
        """v2.8.0: «مدیر» (also the older «admin» code): sees everyone's work."""
        return self.role in (ROLE_SUPER_ADMIN, ROLE_ADMIN)


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
