"""Staff (internal user) accounts: password hashing, roles and permissions.

Staff are the shop's own employees who sign in from ShopAdmin. They are kept
strictly apart from customers (``users`` table, bots/site). Every access
decision for a staff member is made HERE, on the server — a client can hide a
button, but only this table decides what an account may do.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

# --- roles -----------------------------------------------------------------
#: v2.7.0: two built-in roles. The stored codes stay the same as before so old
#: databases (a CHECK constraint lists them) keep working.
ROLE_SUPER_ADMIN = "super_admin"   # «مدیر»: everything
ROLE_SALES = "operator"            # «کاربر فروش»: orders, item requests, customers (view)
#: Earlier roles, migrated on start (``OwnDB``): admin -> manager, viewer -> sales.
ROLE_ADMIN = "admin"
ROLE_OPERATOR = ROLE_SALES
ROLE_VIEWER = "viewer"
STAFF_ROLES = (ROLE_SUPER_ADMIN, ROLE_SALES)
LEGACY_ROLE_MAP = {ROLE_ADMIN: ROLE_SUPER_ADMIN, ROLE_VIEWER: ROLE_SALES}

#: The in-process service identity (ADMIN_API_KEY, used by the bots on the
#: server itself). It may run the shop workflows but never manage staff or the
#: server.
ROLE_SERVICE = "service"

# --- permissions (v2.17.0: every page, section and action has its own tick) ---------
#: (section key, Persian name, has «دیدن», has «تغییر»), in the order ShopAdmin
#: shows the table in «کاربران سیستم». A permission is ``<section>.view`` or
#: ``<section>.edit``; «تغییر» always includes «دیدن». A section without «دیدن»
#: is hidden from the menu, and every endpoint checks the same names here.
#: Only signing in and out and changing one's own password need no tick, and «مدیر»
#: always has everything.
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
#: The permission table of «کاربران سیستم» (rows = sections).
SECTIONS = ALL_SECTIONS


def _names() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, label, view, edit in ALL_SECTIONS:
        if view:
            out[f"{key}.view"] = f"{label} — دیدن"
        if edit:
            out[f"{key}.edit"] = f"{label} — تغییر"
    return out


#: Every permission with its Persian name (also returned by /admin/permissions).
PERMISSION_LABELS: dict[str, str] = _names()
ALL_PERMISSIONS = frozenset(PERMISSION_LABELS)

# The names the endpoints check (kept as constants; v2.8.2 values).
P_DASHBOARD = "dashboard.view"
P_ORDERS_VIEW = "orders.view"
P_ORDERS_EDIT = "payinfo.edit"           # «ارسال اطلاعات پرداخت»
P_PAYMENTS_DECIDE = "receipts.edit"      # confirm / reject a payment receipt
P_ORDERS_SHIP = "ship.edit"              # mark an order as sent (courier optional)
P_ORDERS_CANCEL = "cancel.edit"          # cancel an order (local only)
P_ORDERS_EXPIRE = P_ORDERS_CANCEL        # cancel overdue orders, sync invoices
P_ACCOUNTING_WRITE = "acctwrite.edit"    # v2.17.0: write a waiting order later
P_CLAIM = "claim.edit"                   # v2.17.0: «برداشت»
P_REQUESTS_VIEW = "requests.view"
P_REQUESTS_EDIT = "requests.edit"
P_REQUESTS = P_REQUESTS_EDIT
P_CUSTOMERS_VIEW = "customers.view"
P_CUSTOMERS_DECIDE = "customers.edit"
P_CUSTOMER_PRIVATE_VIEW = "customer_private.view"   # v2.18.1: the rest see a masked code
P_CUSTOMER_PRIVATE_EDIT = "customer_private.edit"
P_ORDERS_ASSIGN = "assign.edit"          # hand an order / request to a colleague
P_ARCHIVE = "archive.view"
P_ARCHIVE_MANUAL = "archive_manual.edit"  # v2.18.0: archive / restore at once, any user's order
P_PRODUCTS = "products.view"
P_GROUPS_VIEW = "groups.view"
P_GROUPS_EDIT = "groups.edit"
P_PRICELIST_VIEW = "pricelist.view"
P_PRICELIST = "pricelist.edit"
P_PROXIES = "proxies.edit"
P_MODELS_VIEW = "models.view"
P_MODELS_EDIT = "models.edit"
P_SITE_VIEW = "site.view"
P_SITE_EDIT = "site.edit"
P_SALES_VIEW = "sales.view"
P_SHOP_STATE = "sales.edit"              # open / close phone sales
P_REPORTS = "reports.view"
P_REPORTS_EXPORT = "reports_export.edit"
P_ACTIVITY = "activity.view"
P_PASSWORDS_VIEW = "passwords.view"
P_PASSWORD_REQUESTS = "passwords.edit"
P_STAFF_VIEW = "staff.view"
P_STAFF_MANAGE = "staff.edit"
P_SERVER_VIEW = "server.view"
P_SERVER_MANAGE = "server.edit"
P_HEALTH = "health.view"
P_STATUS_CODES_VIEW = "status_codes.view"
P_STATUS_CODES_EDIT = "status_codes.edit"
P_AUTO_QUOTE_VIEW = "auto_quote.view"
P_AUTO_QUOTE_EDIT = "auto_quote.edit"
P_PRODUCT_ALIAS = "product_alias.edit"
P_FAQ_VIEW = "faq.view"
P_FAQ_EDIT = "faq.edit"
P_STAFF_CHAT_VIEW = "staff_chat.view"
P_STAFF_CHAT_SEND = "staff_chat.edit"
P_WORK_HOURS_VIEW = "work_hours.view"
P_WORK_HOURS_EDIT = "work_hours.edit"
P_STAFF_ALERTS_VIEW = "staff_alerts.view"
P_STAFF_ALERTS_EDIT = "staff_alerts.edit"
P_AUTO_INVOICE_VIEW = "auto_invoice.view"
P_AUTO_INVOICE_EDIT = "auto_invoice.edit"
#: Product / group reads for staff (low sensitivity: names, prices, stock).
#: v2.8.3: not «داشبورد» (it must not open the catalog).
CATALOG_READERS = ("products.view", "groups.view", "pricelist.view", "models.view")
#: Notifications: every staff member gets the feed (filtered to what they may see).
P_EVENTS = "events.view"

#: v2.17.0: what a new «کاربر فروش» starts with (the daily work; each tick can be
#: taken away). Admin and settings sections are never in here.
_SALES = frozenset({
    "dashboard.view", "orders.view", "receipts.edit", "payinfo.edit", "ship.edit",
    "cancel.edit", "claim.edit", "requests.view", "requests.edit", "customers.view",
    "customers.edit", "assign.edit", "archive.view", "reports.view", "reports_export.edit",
    "staff_alerts.view", "own_prefs.edit",
})

PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: ALL_PERMISSIONS,
    ROLE_SALES: _SALES,
    # the bots on the server: the shop workflows only (never staff / server)
    ROLE_SERVICE: frozenset({"dashboard.view", "orders.view", "receipts.edit", "payinfo.edit",
                             "ship.edit", "cancel.edit", "acctwrite.edit", "claim.edit",
                             "requests.view", "requests.edit", "customers.view", "customers.edit",
                             "assign.edit", "archive.view", "products.view", "groups.view",
                             "pricelist.view", "models.view", "sales.view", "sales.edit",
                             "reports.view", "activity.view"}),
}
# Legacy role codes (only seen before the start-up migration ran).
PERMISSIONS[ROLE_ADMIN] = PERMISSIONS[ROLE_SUPER_ADMIN]
PERMISSIONS[ROLE_VIEWER] = PERMISSIONS[ROLE_SALES]

#: v2.8.2: the per-user ticks of v2.7.0 – v2.8.1 -> the sections they now mean.
LEGACY_PERMISSION_MAP: dict[str, tuple[str, ...]] = {
    "orders.view": ("orders.view", "archive.view"),
    "orders.edit": ("receipts.edit", "payinfo.edit", "ship.edit", "cancel.edit"),
    "payments.decide": ("receipts.edit",),
    "orders.ship": ("ship.edit",),
    "orders.cancel": ("cancel.edit",),
    "orders.expire": ("cancel.edit",),
    "requests.handle": ("requests.view", "requests.edit"),
    "customers.view": ("customers.view",),
    "customers.decide": ("customers.edit",),
    "orders.assign": ("assign.edit",),
    "view": ("dashboard.view", "products.view", "reports.view", "groups.view",
             "pricelist.view", "models.view", "sales.view"),
    "shop.state": ("sales.edit",),
    "pricelist.manage": ("pricelist.edit",),
    "proxies.manage": ("proxies.edit",),
    "catalog.manage": ("groups.edit", "models.edit"),
    "passwords.decide": ("passwords.edit",),
    "staff.manage": ("staff.edit", "activity.view"),
    "server.manage": ("server.edit",),
    "events.view": (),
}
#: The v2.8.1 role tables, to rebuild a user's old effective rights exactly.
_LEGACY_SALES = frozenset({"orders.view", "payments.decide", "orders.ship", "orders.cancel",
                           "requests.handle", "customers.view", "events.view"})
_LEGACY_ROLES = {ROLE_SUPER_ADMIN: frozenset(LEGACY_PERMISSION_MAP), ROLE_SALES: _LEGACY_SALES}


#: v2.17.0: an action needs its page: ticking it ticks the page's «دیدن» too.
REQUIRES: dict[str, str] = {
    "receipts.edit": "orders.view", "payinfo.edit": "orders.view", "ship.edit": "orders.view",
    "cancel.edit": "orders.view", "acctwrite.edit": "orders.view",
    "proxies.edit": "pricelist.view", "reports_export.edit": "reports.view",
}


def required_view(name: str) -> str | None:
    """The «دیدن» an «تغییر» cannot go without (None for a tick on its own)."""
    if name in REQUIRES:
        return REQUIRES[name]
    if name.endswith(".edit") and f"{name[:-5]}.view" in ALL_PERMISSIONS:
        return f"{name[:-5]}.view"
    return None


def with_implied(perms) -> frozenset[str]:
    """«تغییر» includes «دیدن» of the same section (when the section has one)."""
    out = set(perms)
    for name in list(out):
        view = required_view(name)
        if view:
            out.add(view)
    return frozenset(out)


def migrate_ticks(role: str, grants: str, revokes: str) -> tuple[str, str] | None:
    """Old per-user ticks -> the same rights as section ticks (relative to the new
    role table). None when nothing needs migrating."""
    old = {p.strip() for p in f"{grants},{revokes}".split(",") if p.strip()}
    if not old or old <= ALL_PERMISSIONS:
        return None
    base_old = _LEGACY_ROLES.get(role, frozenset())
    old_effective = (base_old | {p.strip() for p in grants.split(",") if p.strip()}) \
        - {p.strip() for p in revokes.split(",") if p.strip()}
    new_effective: set[str] = set()
    for name in old_effective:
        if name in LEGACY_PERMISSION_MAP:
            new_effective.update(LEGACY_PERMISSION_MAP[name])
        elif name in ALL_PERMISSIONS:
            new_effective.add(name)
    new_effective = set(with_implied(new_effective))
    base_new = PERMISSIONS.get(role, frozenset())
    # only what the old names could say anything about; a newer tick keeps its default
    known = with_implied(name for names in LEGACY_PERMISSION_MAP.values() for name in names)
    return (",".join(sorted(new_effective - base_new)),
            ",".join(sorted((base_new & known) - new_effective)))


#: v2.8.3 – v2.16: these were always on and never stored as ticks.
_FORMERLY_ALWAYS = frozenset({
    "dashboard.view", "orders.view", "orders.edit", "requests.view", "requests.edit",
    "customers.view", "customers.edit", "assign.edit", "archive.view", "reports.view",
})


def strip_always(raw: str) -> str | None:
    """v2.8.3: a stored tick list without the then always-on names (None = unchanged).
    Only for a database older than v2.17.0; today every name is a real tick."""
    items = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    kept = [p for p in items if p not in _FORMERLY_ALWAYS]
    return ",".join(sorted(set(kept))) if len(kept) != len(items) else None


def upgrade_ticks_2170(role: str, grants: str) -> str:
    """v2.17.0, once: rights that were split into their own ticks stay with whoever
    had them: every existing sales user keeps «تنظیمات برنامه»; the parts that came
    with another section stay with that section's holders. New users get none of it."""
    if str(role or "") not in (ROLE_SALES, ROLE_VIEWER):
        return grants
    have = {p.strip() for p in str(grants or "").split(",") if p.strip()}
    extra = {"app_settings.view", "app_settings.edit"}
    if "pricelist.edit" in have:
        extra.add("proxies.edit")
    if "models.edit" in have:
        extra.update(("site.view", "site.edit"))
    if have & {"server.view", "server.edit"}:
        extra.update(("health.view", "status_codes.view", "work_hours.view", "auto_invoice.view"))
    if "server.edit" in have:
        extra.update(("status_codes.edit", "work_hours.edit", "staff_alerts.edit",
                      "auto_invoice.edit"))
    return ",".join(sorted(have | extra))


def parse_permission_list(raw) -> frozenset[str]:
    """A stored comma list (or any iterable) -> known permission names only."""
    if raw is None:
        return frozenset()
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(p.strip() for p in items if str(p).strip() in ALL_PERMISSIONS)


def effective_permissions(role: str | None, grants=None, revokes=None) -> frozenset[str]:
    """The role's permissions plus the per-user ticks: ``grants`` added, ``revokes``
    removed; «تغییر» implies «دیدن», and an action whose «دیدن» was taken away goes
    with it. «مدیر» always has everything. Every staff member gets the (filtered)
    notification feed."""
    role = str(role or "")
    if role in (ROLE_SUPER_ADMIN, ROLE_ADMIN):
        return ALL_PERMISSIONS | {P_EVENTS}
    base = PERMISSIONS.get(role, frozenset())
    taken = parse_permission_list(revokes)
    perms = (base | parse_permission_list(grants)) - taken
    perms = {p for p in perms if required_view(p) not in taken}
    return with_implied(perms) | {P_EVENTS}


def has_permission(role: str | None, permission: str) -> bool:
    if permission == P_EVENTS:
        return str(role or "") in PERMISSIONS
    return permission in PERMISSIONS.get(str(role or ""), frozenset())


def sections_out() -> list[dict]:
    """The permission table for ShopAdmin (rows = sections)."""
    return [{"key": key, "label": label,
             "view": f"{key}.view" if view else None,
             "edit": f"{key}.edit" if edit else None}
            for key, label, view, edit in SECTIONS]


#: Password a super admin can reset an account to. It is deliberately weak and
#: therefore ALWAYS paired with must_change_password: the account can do
#: nothing but pick a new (policy-checked) password until it has.
DEFAULT_RESET_PASSWORD = "12345"

# --- validation ------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3-32 characters: letters, digits, . _ -"
    return None


def validate_password(password: str) -> str | None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    if len(password) > MAX_PASSWORD_LEN:
        return "Password is too long"
    if not re.search(r"[A-Za-z؀-ۿ]", password) or not re.search(r"\d", password):
        return "Password must contain letters and digits"
    return None


# --- password hashing (stdlib scrypt; no extra dependency) -----------------
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = str(stored).split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            str(password).encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


#: Verified against when the username does not exist, so a wrong username and
#: a wrong password take the same time (no account enumeration by timing).
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# --- session tokens ----------------------------------------------------------
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Only this hash is stored; a stolen database holds no usable token."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()
