"""Role-based permissions (v2.7.0: two roles plus per-user ticks).

* «مدیر» (``super_admin``) — everything, always.
* «کاربر فروش» (``operator``, the default for new users) — starts with the daily work;
  v2.17.0: every page and action is a tick a manager can give or take away. Only
  signing in and out and changing one's own password need no tick.

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
CUSTOMER_PRIVATE_VIEW = "customer_private.view"   # v2.18.1: national code and address
CUSTOMER_PRIVATE_EDIT = "customer_private.edit"
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
ARCHIVE_MANUAL = "archive_manual.edit"   # v2.18.0: archive / restore at once, any user's order
ACTIVITY_VIEW = "activity.view"          # v2.8.0: «گزارش فعالیت» (manager only)
SHOP_STATE = "shop.state"                # open / close phone sales
ORDERS_WRITE_ACCOUNTING = "orders.write_accounting"   # v2.17.0: «ثبت در حسابداری»
ORDERS_CLAIM = "orders.claim"            # v2.17.0: «برداشت»
SITE_VIEW = "site.view"                  # v2.17.0: «سایت» has its own ticks
SITE_MANAGE = "site.manage"
HEALTH_VIEW = "health.view"
SHOP_RULES_VIEW = "shop_rules.view"      # any of the three parts of «قواعد فروشگاه»
STATUS_CODES_VIEW = "status_codes.view"
STATUS_CODES_EDIT = "status_codes.edit"
WORK_HOURS_VIEW = "work_hours.view"
WORK_HOURS_EDIT = "work_hours.edit"
STAFF_ALERTS_VIEW = "staff_alerts.view"
STAFF_ALERTS_EDIT = "staff_alerts.edit"
AUTO_INVOICE_VIEW = "auto_invoice.view"
AUTO_INVOICE_EDIT = "auto_invoice.edit"
AUTO_QUOTE_VIEW = "auto_quote.view"
AUTO_QUOTE_EDIT = "auto_quote.edit"
PRODUCT_ALIAS = "product_alias.edit"
FAQ_VIEW = "faq.view"
FAQ_EDIT = "faq.edit"
STAFF_CHAT_VIEW = "staff_chat.view"
STAFF_CHAT_SEND = "staff_chat.edit"
OWN_PREFS = "own_prefs.edit"             # own notification sound / look
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

#: v2.17.0: every section (same rows as shopapi ``staff.ALL_SECTIONS``):
#: (section, Persian name, has «دیدن», has «تغییر»).
ALL_SECTIONS: tuple[tuple[str, str, bool, bool], ...] = (
    ("dashboard", "داشبورد", True, False),
    ("orders", "سفارش‌ها", True, False),
    ("receipts", "تأیید و رد رسید", False, True),
    ("payinfo", "ارسال اطلاعات پرداخت", False, True),
    ("ship", "ثبت «ارسال شد»", False, True),
    ("cancel", "لغو سفارش", False, True),
    ("acctwrite", "دکمهٔ «ثبت در حسابداری»", False, True),
    ("claim", "برداشتن کار تازه («برداشت»)", False, True),
    ("requests", "درخواست کالا (پیام، یادداشت، تأیید موجودی)", True, True),
    ("customers", "مشتریان (تأیید و رد مشتری)", True, True),
    ("customer_private", "کد ملی و نشانی مشتری", True, True),
    ("assign", "ارجاع کار به همکار", False, True),
    ("archive", "بایگانی", True, False),
    ("archive_manual", "بایگانی دستی سفارش‌ها و برگرداندن (هر کاربر)", False, True),
    ("products", "محصولات و موجودی", True, False),
    ("groups", "گروه‌های کالا", True, True),
    ("pricelist", "لیست قیمت و نگاشت", True, True),
    ("proxies", "پراکسی‌ها", False, True),
    ("models", "مدل‌های سایت", True, True),
    ("site", "سایت (کالاها، ظاهر، انتشار)", True, True),
    ("sales", "فروش گوشی (باز و بسته کردن)", True, True),
    ("reports", "گزارش‌ها", True, False),
    ("reports_export", "خروجی گزارش (Excel / CSV)", False, True),
    ("activity", "گزارش فعالیت", True, False),
    ("passwords", "درخواست‌های گذرواژه", True, True),
    ("staff", "کاربران سیستم و دسترسی‌ها", True, True),
    ("server", "تنظیمات سرور فروشگاه", True, True),
    ("health", "سلامت سیستم", True, False),
    ("status_codes", "کدهای وضعیت «سازه حساب»", True, True),
    ("work_hours", "ساعت کار", True, True),
    ("staff_alerts", "اعلان کارکنان (دیدن = دریافت در بله/تلگرام، تغییر = روشن و خاموش)",
     True, True),
    ("auto_invoice", "صدور خودکار فاکتور", True, True),
    ("auto_quote", "پاسخ خودکار قیمت کالای غیرموجود (و گزارش آن)", True, True),
    ("product_alias", "یاد دادن نام کالا به ربات", False, True),
    ("faq", "پاسخ‌گوی خودکار ربات", True, True),
    ("staff_chat", "گفت‌وگوی همکاران (دیدن = خواندن، تغییر = فرستادن)", True, True),
    ("app_settings", "تنظیمات برنامه (همین رایانه)", True, True),
    ("own_prefs", "اعلان‌ها و ظاهرِ خودم", False, True),
)
SECTION_PERMISSIONS = frozenset(
    [f"{k}.view" for k, _l, v, _e in ALL_SECTIONS if v]
    + [f"{k}.edit" for k, _l, _v, e in ALL_SECTIONS if e])
#: The permission table of «کاربران سیستم» (shopapi ``staff.SECTIONS``).
SECTIONS: tuple[tuple[str, str, bool, bool], ...] = ALL_SECTIONS
#: Ticks shown in the table.
TABLE_PERMISSIONS = SECTION_PERMISSIONS
#: What a new «کاربر فروش» starts with (shopapi ``staff.PERMISSIONS``).
SALES_SERVER_PERMISSIONS = frozenset({
    "dashboard.view", "orders.view", "receipts.edit", "payinfo.edit", "ship.edit",
    "cancel.edit", "claim.edit", "requests.view", "requests.edit", "customers.view",
    "customers.edit", "assign.edit", "archive.view", "reports.view", "reports_export.edit",
    "staff_alerts.view", "own_prefs.edit",
})
#: An action needs its page (shopapi ``staff.REQUIRES``).
REQUIRES: dict[str, str] = {
    "receipts.edit": "orders.view", "payinfo.edit": "orders.view", "ship.edit": "orders.view",
    "cancel.edit": "orders.view", "acctwrite.edit": "orders.view",
    "proxies.edit": "pricelist.view", "reports_export.edit": "reports.view",
}

#: shopapi permission -> what it unlocks on the screens.
SERVER_TO_CLIENT: dict[str, frozenset[str]] = {
    # ---- v2.8.2 sections («دیدن» / «تغییر») ----
    "dashboard.view": frozenset({DASHBOARD_VIEW}),
    "orders.view": frozenset({ORDERS_VIEW}),
    "receipts.edit": frozenset({ORDERS_APPROVE_PAYMENT, ORDERS_REJECT_PAYMENT,
                                ORDERS_UPLOAD_RECEIPT}),
    "payinfo.edit": frozenset({ORDERS_PAYMENT_INFO}),
    "ship.edit": frozenset({ORDERS_SHIP}),
    "cancel.edit": frozenset({ORDERS_CANCEL, ORDERS_EXPIRE}),
    "acctwrite.edit": frozenset({ORDERS_WRITE_ACCOUNTING}),
    "claim.edit": frozenset({ORDERS_CLAIM}),
    "requests.view": frozenset({ITEM_REQUESTS_VIEW}),
    "requests.edit": frozenset({ITEM_REQUESTS}),
    "customers.view": frozenset({CUSTOMERS_VIEW}),
    "customers.edit": frozenset({CUSTOMERS_APPROVE, CUSTOMERS_REJECT}),
    "customer_private.view": frozenset({CUSTOMER_PRIVATE_VIEW}),
    "customer_private.edit": frozenset({CUSTOMER_PRIVATE_EDIT}),
    "assign.edit": frozenset({ORDERS_ASSIGN}),
    "archive.view": frozenset({ARCHIVE_VIEW}),
    "archive_manual.edit": frozenset({ARCHIVE_MANUAL}),
    "products.view": frozenset({PRODUCTS_VIEW}),
    "groups.view": frozenset({GROUPS_VIEW}),
    "groups.edit": frozenset({GROUPS_MANAGE}),
    "pricelist.view": frozenset({PRICELIST_VIEW}),
    "pricelist.edit": frozenset({PRICELIST_MANAGE}),
    "proxies.edit": frozenset({PROXIES_MANAGE}),
    "models.view": frozenset({CATALOG_VIEW}),
    "models.edit": frozenset({CATALOG_MANAGE}),
    "site.view": frozenset({SITE_VIEW}),
    "site.edit": frozenset({SITE_MANAGE}),
    "sales.view": frozenset({SALES_VIEW}),
    "sales.edit": frozenset({SHOP_STATE}),
    "reports.view": frozenset({REPORTS_VIEW}),
    "reports_export.edit": frozenset({REPORTS_EXPORT}),
    "activity.view": frozenset({ACTIVITY_VIEW}),
    "passwords.view": frozenset({PASSWORDS_VIEW}),
    "passwords.edit": frozenset({PASSWORDS_DECIDE}),
    "staff.view": frozenset({USERS_VIEW}),
    "staff.edit": frozenset({USERS_MANAGE}),
    "server.view": frozenset({SERVER_VIEW}),
    "server.edit": frozenset({SERVER_MANAGE, SETTINGS_EDIT_CONNECTION}),
    "health.view": frozenset({HEALTH_VIEW}),
    "status_codes.view": frozenset({STATUS_CODES_VIEW, SHOP_RULES_VIEW}),
    "status_codes.edit": frozenset({STATUS_CODES_EDIT}),
    "work_hours.view": frozenset({WORK_HOURS_VIEW, SHOP_RULES_VIEW}),
    "work_hours.edit": frozenset({WORK_HOURS_EDIT}),
    "staff_alerts.view": frozenset({STAFF_ALERTS_VIEW}),
    "staff_alerts.edit": frozenset({STAFF_ALERTS_EDIT}),
    "auto_invoice.view": frozenset({AUTO_INVOICE_VIEW, SHOP_RULES_VIEW}),
    "auto_invoice.edit": frozenset({AUTO_INVOICE_EDIT}),
    "auto_quote.view": frozenset({AUTO_QUOTE_VIEW, SHOP_RULES_VIEW}),
    "auto_quote.edit": frozenset({AUTO_QUOTE_EDIT}),
    "product_alias.edit": frozenset({PRODUCT_ALIAS}),
    "faq.view": frozenset({FAQ_VIEW, SHOP_RULES_VIEW}),
    "faq.edit": frozenset({FAQ_EDIT}),
    "staff_chat.view": frozenset({STAFF_CHAT_VIEW}),
    "staff_chat.edit": frozenset({STAFF_CHAT_SEND}),
    "app_settings.view": frozenset({SETTINGS_VIEW}),
    "app_settings.edit": frozenset({SETTINGS_EDIT_GENERAL, SETTINGS_VIEW_LOG}),
    "own_prefs.edit": frozenset({OWN_PREFS}),
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
#: v2.17.0: the only thing without a tick: everyone changes their own password.
ALWAYS = frozenset({SETTINGS_CHANGE_OWN_PASSWORD})

#: Persian names of the server permissions, in display order (v2.8.2: per section).
SERVER_PERMISSION_FA: dict[str, str] = {}
for _key, _label, _view, _edit in ALL_SECTIONS:
    if _view:
        SERVER_PERMISSION_FA[f"{_key}.view"] = f"{_label} — دیدن"
    if _edit:
        SERVER_PERMISSION_FA[f"{_key}.edit"] = f"{_label} — تغییر"
ROLE_SERVER_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: SECTION_PERMISSIONS,
    ROLE_OPERATOR: SALES_SERVER_PERMISSIONS,
    # earlier roles (the server maps them on start: admin -> manager, viewer -> sales)
    ROLE_ADMIN: SECTION_PERMISSIONS,
    ROLE_VIEWER: SALES_SERVER_PERMISSIONS,
}


def required_view(name: str) -> str | None:
    """The «دیدن» an «تغییر» cannot go without (None for a tick on its own)."""
    if name in REQUIRES:
        return REQUIRES[name]
    if name.endswith(".edit") and f"{name[:-5]}.view" in SECTION_PERMISSIONS:
        return f"{name[:-5]}.view"
    return None


def with_implied(names) -> set[str]:
    """«تغییر» includes «دیدن» of the same section."""
    out = set(names)
    for name in list(out):
        view = required_view(name)
        if view:
            out.add(view)
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
