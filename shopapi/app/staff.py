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
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"          # مدیر فروش
ROLE_OPERATOR = "operator"    # اپراتور
ROLE_VIEWER = "viewer"        # ناظر
STAFF_ROLES = (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)

#: The in-process service identity (ADMIN_API_KEY, used by the bots on the
#: server itself). It may run the shop workflows but never manage staff or the
#: server.
ROLE_SERVICE = "service"

# --- permissions -----------------------------------------------------------
P_VIEW = "view"                          # customers, orders, products, events, system info
P_CUSTOMERS_DECIDE = "customers.decide"  # match person, approve / reject customer
P_PAYMENTS_DECIDE = "payments.decide"    # approve / reject payment
P_ORDERS_EXPIRE = "orders.expire"
P_ORDERS_SHIP = "orders.ship"            # mark an order as shipped
P_SHOP_STATE = "shop.state"              # open / close the shop (closed mode)
P_PRICELIST = "pricelist.manage"        # upload / approve price lists, map rows
P_CATALOG = "catalog.manage"            # site models <-> accounting products (§9a)
P_PROXIES = "proxies.manage"             # Telegram proxy pool
P_PASSWORD_REQUESTS = "passwords.decide"  # approve / reject forgot-password requests
P_STAFF_MANAGE = "staff.manage"
P_SERVER_MANAGE = "server.manage"

_WORKFLOW = {
    P_VIEW, P_CUSTOMERS_DECIDE, P_PAYMENTS_DECIDE, P_ORDERS_EXPIRE, P_ORDERS_SHIP, P_SHOP_STATE,
}

PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_VIEWER: frozenset({P_VIEW}),
    ROLE_OPERATOR: frozenset({P_VIEW, P_ORDERS_SHIP}),
    ROLE_ADMIN: frozenset(_WORKFLOW | {P_PRICELIST, P_CATALOG, P_PASSWORD_REQUESTS}),
    ROLE_SUPER_ADMIN: frozenset(
        _WORKFLOW | {P_PRICELIST, P_CATALOG, P_PROXIES, P_STAFF_MANAGE, P_SERVER_MANAGE,
                 P_PASSWORD_REQUESTS}
    ),
    ROLE_SERVICE: frozenset(_WORKFLOW),
}


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
