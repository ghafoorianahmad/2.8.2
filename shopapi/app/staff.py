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

# --- permissions -----------------------------------------------------------
P_ORDERS_VIEW = "orders.view"            # orders list / detail / receipt image
P_PAYMENTS_DECIDE = "payments.decide"    # confirm / reject a payment receipt
P_ORDERS_SHIP = "orders.ship"            # mark an order as sent (courier optional)
P_ORDERS_CANCEL = "orders.cancel"        # cancel an order (local only)
P_REQUESTS = "requests.handle"           # item requests: view, reply, mark handled
P_CUSTOMERS_VIEW = "customers.view"
P_EVENTS = "events.view"                 # notification feed (badges, desktop notices)
P_ORDERS_ASSIGN = "orders.assign"        # v2.8.0: reassign an order / request to a colleague
P_VIEW = "view"                          # everything else read-only: dashboard, products,
#                                          reports, product groups, price lists, site models
P_CUSTOMERS_DECIDE = "customers.decide"  # match person, approve / reject customer
P_ORDERS_EXPIRE = "orders.expire"
P_SHOP_STATE = "shop.state"              # open / close phone sales
P_PRICELIST = "pricelist.manage"        # upload / approve price lists, map rows
P_CATALOG = "catalog.manage"            # product groups, site models (§9a)
P_PROXIES = "proxies.manage"             # Telegram proxy pool
P_PASSWORD_REQUESTS = "passwords.decide"  # approve / reject forgot-password requests
P_STAFF_MANAGE = "staff.manage"
P_SERVER_MANAGE = "server.manage"

#: Every permission with its Persian name, in the order ShopAdmin lists them
#: («کاربران سیستم» › per-user ticks).
PERMISSION_LABELS: dict[str, str] = {
    P_ORDERS_VIEW: "دیدن سفارش‌ها",
    P_PAYMENTS_DECIDE: "تأیید یا رد رسید پرداخت",
    P_ORDERS_SHIP: "ثبت «ارسال شد»",
    P_ORDERS_CANCEL: "لغو سفارش",
    P_REQUESTS: "درخواست‌های کالا (دیدن، پاسخ، رسیدگی)",
    P_CUSTOMERS_VIEW: "دیدن مشتریان",
    P_EVENTS: "اعلان‌ها",
    P_ORDERS_ASSIGN: "ارجاع سفارش",
    P_VIEW: "داشبورد، کالاها، گزارش‌ها و سایر صفحه‌ها (فقط دیدن)",
    P_CUSTOMERS_DECIDE: "تأیید یا رد مشتری",
    P_ORDERS_EXPIRE: "لغو سفارش‌های بی‌رسید و هماهنگی فاکتورها",
    P_SHOP_STATE: "باز و بسته کردن فروش",
    P_PRICELIST: "لیست قیمت و نگاشت",
    P_CATALOG: "گروه‌های کالا و مدل‌های سایت",
    P_PROXIES: "پراکسی‌های تلگرام",
    P_PASSWORD_REQUESTS: "درخواست‌های گذرواژه",
    P_STAFF_MANAGE: "کاربران سیستم",
    P_SERVER_MANAGE: "تنظیمات و سرور فروشگاه",
}
ALL_PERMISSIONS = frozenset(PERMISSION_LABELS)

_SALES = frozenset({P_ORDERS_VIEW, P_PAYMENTS_DECIDE, P_ORDERS_SHIP, P_ORDERS_CANCEL,
                    P_REQUESTS, P_CUSTOMERS_VIEW, P_EVENTS})

PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: ALL_PERMISSIONS,
    ROLE_SALES: _SALES,
    # the bots on the server: the shop workflows only
    ROLE_SERVICE: frozenset(_SALES | {P_VIEW, P_CUSTOMERS_DECIDE, P_ORDERS_EXPIRE,
                                      P_SHOP_STATE}),
}
# Legacy role codes (only seen before the start-up migration ran).
PERMISSIONS[ROLE_ADMIN] = PERMISSIONS[ROLE_SUPER_ADMIN]
PERMISSIONS[ROLE_VIEWER] = PERMISSIONS[ROLE_SALES]


def parse_permission_list(raw) -> frozenset[str]:
    """A stored comma list (or any iterable) -> known permission names only."""
    if raw is None:
        return frozenset()
    items = raw.split(",") if isinstance(raw, str) else raw
    return frozenset(p.strip() for p in items if str(p).strip() in ALL_PERMISSIONS)


def effective_permissions(role: str | None, grants=None, revokes=None) -> frozenset[str]:
    """The role's permissions plus the per-user ticks (v2.7.0): ``grants`` added,
    ``revokes`` removed. Unknown names are ignored."""
    base = PERMISSIONS.get(str(role or ""), frozenset())
    return frozenset((base | parse_permission_list(grants)) - parse_permission_list(revokes))


def has_permission(role: str | None, permission: str) -> bool:
    return permission in PERMISSIONS.get(str(role or ""), frozenset())


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
