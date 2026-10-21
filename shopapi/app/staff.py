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

# --- permissions (v2.8.2: one row per section, «دیدن» and «تغییر») -----------------
#: (section key, Persian name, has «دیدن», has «تغییر»), in the order ShopAdmin
#: shows the table in «کاربران سیستم». A permission is ``<section>.view`` or
#: ``<section>.edit``; «تغییر» always includes «دیدن». A section without «دیدن»
#: is hidden from the menu, and every endpoint checks the same names here.
#: v2.8.3: every section that exists (names stay valid for old ticks and checks).
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
#: v2.8.3: the daily work of every staff member is always on and is no longer in
#: the table (each user still sees only their own work and new free work).
ALWAYS_SECTIONS = frozenset({"dashboard", "orders", "requests", "customers", "assign",
                             "archive", "reports"})
#: The permission table of «کاربران سیستم» (rows = sections).
SECTIONS: tuple[tuple[str, str, bool, bool], ...] = tuple(
    s for s in ALL_SECTIONS if s[0] not in ALWAYS_SECTIONS)


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
#: v2.8.3: what every staff member always has (not a tick any more).
ALWAYS_PERMISSIONS = frozenset(name for name in ALL_PERMISSIONS
                               if name.split(".", 1)[0] in ALWAYS_SECTIONS)

# The names the endpoints check (kept as constants; v2.8.2 values).
P_DASHBOARD = "dashboard.view"
P_ORDERS_VIEW = "orders.view"
P_ORDERS_EDIT = "orders.edit"
P_PAYMENTS_DECIDE = P_ORDERS_EDIT        # confirm / reject a payment receipt
P_ORDERS_SHIP = P_ORDERS_EDIT            # mark an order as sent (courier optional)
P_ORDERS_CANCEL = P_ORDERS_EDIT          # cancel an order (local only)
P_ORDERS_EXPIRE = P_ORDERS_EDIT          # cancel overdue orders, sync invoices
P_REQUESTS_VIEW = "requests.view"
P_REQUESTS_EDIT = "requests.edit"
P_REQUESTS = P_REQUESTS_EDIT
P_CUSTOMERS_VIEW = "customers.view"
P_CUSTOMERS_DECIDE = "customers.edit"
P_ORDERS_ASSIGN = "assign.edit"          # hand an order / request to a colleague
P_ARCHIVE = "archive.view"
P_PRODUCTS = "products.view"
P_GROUPS_VIEW = "groups.view"
P_GROUPS_EDIT = "groups.edit"
P_PRICELIST_VIEW = "pricelist.view"
P_PRICELIST = "pricelist.edit"
P_PROXIES = P_PRICELIST
P_MODELS_VIEW = "models.view"
P_MODELS_EDIT = "models.edit"
P_SALES_VIEW = "sales.view"
P_SHOP_STATE = "sales.edit"              # open / close phone sales
P_REPORTS = "reports.view"
P_ACTIVITY = "activity.view"
P_PASSWORDS_VIEW = "passwords.view"
P_PASSWORD_REQUESTS = "passwords.edit"
P_STAFF_VIEW = "staff.view"
P_STAFF_MANAGE = "staff.edit"
P_SERVER_VIEW = "server.view"
P_SERVER_MANAGE = "server.edit"
#: Product / group reads for staff (low sensitivity: names, prices, stock).
#: v2.8.3: not «داشبورد» any more (it is always on; it must not open the catalog).
CATALOG_READERS = ("products.view", "groups.view", "pricelist.view", "models.view")
#: Notifications: every staff member gets the feed (filtered to what they may see).
P_EVENTS = "events.view"

_SALES = ALWAYS_PERMISSIONS

PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: ALL_PERMISSIONS,
    ROLE_SALES: _SALES,
    # the bots on the server: the shop workflows only (never staff / server)
    ROLE_SERVICE: frozenset({"dashboard.view", "orders.view", "orders.edit", "requests.view",
                             "requests.edit", "customers.view", "customers.edit",
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
    "payments.decide": ("orders.edit",),
    "orders.ship": ("orders.edit",),
    "orders.cancel": ("orders.edit",),
    "orders.expire": ("orders.edit",),
    "requests.handle": ("requests.view", "requests.edit"),
    "customers.view": ("customers.view",),
    "customers.decide": ("customers.edit",),
    "orders.assign": ("assign.edit",),
    "view": ("dashboard.view", "products.view", "reports.view", "groups.view",
             "pricelist.view", "models.view", "sales.view"),
    "shop.state": ("sales.edit",),
    "pricelist.manage": ("pricelist.edit",),
    "proxies.manage": ("pricelist.edit",),
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


def with_implied(perms) -> frozenset[str]:
    """«تغییر» includes «دیدن» of the same section (when the section has one)."""
    out = set(perms)
    for name in list(out):
        if name.endswith(".edit"):
            view = name[:-5] + ".view"
            if view in ALL_PERMISSIONS:
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
    return (",".join(sorted(new_effective - base_new)), ",".join(sorted(base_new - new_effective)))


def strip_always(raw: str) -> str | None:
    """v2.8.3: a stored tick list without the always-on names (None = unchanged)."""
    items = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    kept = [p for p in items if p not in ALWAYS_PERMISSIONS]
    return ",".join(sorted(set(kept))) if len(kept) != len(items) else None


def parse_permission_list(raw) -> frozenset[str]:
    """A stored comma list (or any iterable) -> known permission names only."""
    if raw is None:
        return frozenset()
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(p.strip() for p in items if str(p).strip() in ALL_PERMISSIONS)


def effective_permissions(role: str | None, grants=None, revokes=None) -> frozenset[str]:
    """The role's permissions plus the per-user ticks: ``grants`` added,
    ``revokes`` removed; «تغییر» implies «دیدن»; every staff member gets the
    (filtered) notification feed."""
    base = PERMISSIONS.get(str(role or ""), frozenset())
    perms = with_implied((base | parse_permission_list(grants)) - parse_permission_list(revokes))
    if str(role or "") in PERMISSIONS:
        perms = perms | ALWAYS_PERMISSIONS        # v2.8.3: never a tick
    return perms | {P_EVENTS}


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
