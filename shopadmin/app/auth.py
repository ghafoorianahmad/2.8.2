"""Authentication and account management for INTERNAL admin users.

These are the shop owner's staff — a small fixed group. Customer accounts are a
completely different concept and live in shopapi; they are never handled here.

Passwords are hashed with bcrypt (never stored or logged in plain text).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import bcrypt

from .logging_setup import get_logger
from .permissions import Principal, has_permission
from .persian import to_english_digits
from .statuses import ALL_ROLES, ROLE_SUPER_ADMIN
from .store import Store

log = get_logger("auth")

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 6
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

#: Sentinel stored in ``remembered_sessions.expires_at`` for a token that never
#: expires. The «مرا به خاطر بسپار» session must survive indefinitely — it ends
#: only when the user logs out or unticks the box.
NO_EXPIRY = "never"

# Persian messages for every failure mode the UI can hit.
MSG_INVALID_CREDENTIALS = "نام کاربری یا گذرواژه نادرست است."
MSG_USER_DISABLED = "این حساب کاربری غیرفعال شده است. با مدیر کل تماس بگیرید."
MSG_USER_LOCKED = "حساب کاربری به دلیل تلاش‌های ناموفق موقتاً قفل شده است. کمی بعد دوباره تلاش کنید."
MSG_EMPTY_FIELDS = "نام کاربری و گذرواژه را وارد کنید."
MSG_WRONG_CURRENT_PASSWORD = "گذرواژهٔ فعلی نادرست است."
MSG_PASSWORD_TOO_SHORT = f"گذرواژه باید حداقل {MIN_PASSWORD_LENGTH} نویسه باشد."
MSG_PASSWORD_MISMATCH = "تکرار گذرواژه با گذرواژهٔ جدید یکسان نیست."
MSG_USERNAME_TAKEN = "این نام کاربری قبلاً استفاده شده است."
MSG_USERNAME_INVALID = "نام کاربری باید ۳ تا ۳۲ نویسهٔ انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد."
MSG_NAME_REQUIRED = "نام و نام خانوادگی را وارد کنید."
MSG_ROLE_INVALID = "نقش انتخاب‌شده معتبر نیست."
MSG_LAST_SUPER_ADMIN = "حداقل یک مدیر کل فعال باید باقی بماند."
MSG_CANNOT_DELETE_SELF = "نمی‌توانید حساب کاربری خودتان را حذف کنید."
MSG_CANNOT_DEACTIVATE_SELF = "نمی‌توانید حساب کاربری خودتان را غیرفعال کنید."
MSG_NOT_FOUND = "کاربر مورد نظر یافت نشد."


class AuthError(Exception):
    """Authentication/authorisation failure carrying a Persian message."""

    def __init__(self, message: str, code: str = "auth_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class LoginResult:
    principal: Principal
    must_change_password: bool = False


# --------------------------------------------------------------------------
# password hashing
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """bcrypt hash with a per-password salt."""
    raw = str(password).encode("utf-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(str(password).encode("utf-8"), str(password_hash).encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> Optional[str]:
    """Return a Persian error message, or ``None`` when acceptable."""
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        return MSG_PASSWORD_TOO_SHORT
    return None


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
class AuthService:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ---- bootstrap -------------------------------------------------------
    @property
    def needs_first_super_admin(self) -> bool:
        return self.store.count_admin_users() == 0

    def create_first_super_admin(self, username: str, full_name: str, password: str) -> Principal:
        """Used by the first-run wizard. Only valid while no user exists."""
        if not self.needs_first_super_admin:
            raise AuthError("کاربر مدیر کل از قبل ساخته شده است.", "already_initialised")
        return self.create_user(username, full_name, password, ROLE_SUPER_ADMIN, actor="setup")

    # ---- login -----------------------------------------------------------
    def authenticate(self, username: str, password: str) -> LoginResult:
        username = to_english_digits(str(username or "")).strip()
        password = str(password or "")
        if not username or not password:
            raise AuthError(MSG_EMPTY_FIELDS, "empty_fields")

        user = self.store.get_admin_user_by_username(username)
        if user is None:
            # Do a dummy hash comparison so a missing user is not obviously faster.
            verify_password(password, "$2b$12$" + "." * 53)
            log.warning("login failed: unknown username")
            raise AuthError(MSG_INVALID_CREDENTIALS, "invalid_credentials")

        if not int(user["is_active"]):
            log.warning("login refused: inactive admin user id=%s", user["id"])
            raise AuthError(MSG_USER_DISABLED, "user_disabled")

        locked_until = _parse_lock(user.get("locked_until"))
        if locked_until is not None and locked_until > datetime.now(timezone.utc):
            log.warning("login refused: admin user id=%s still locked", user["id"])
            raise AuthError(MSG_USER_LOCKED, "user_locked")

        if not verify_password(password, user["password_hash"]):
            updated = self.store.register_failed_attempt(
                int(user["id"]), MAX_FAILED_ATTEMPTS, LOCK_MINUTES
            )
            attempts = int(updated.get("failed_attempts", 1))
            log.warning("login failed: bad password for admin user id=%s", user["id"])
            if attempts >= MAX_FAILED_ATTEMPTS:
                raise AuthError(MSG_USER_LOCKED, "user_locked")
            raise AuthError(MSG_INVALID_CREDENTIALS, "invalid_credentials")

        self.store.clear_failed_attempts(int(user["id"]))
        self.store.audit(user["username"], "login", "ورود موفق به برنامه")
        log.info("login ok: admin user id=%s role=%s", user["id"], user["role"])
        return LoginResult(principal=principal_from_row(user))

    # ---- remember me (token only, never the password) ---------------------
    def create_remember_token(self, user_id: int, days: int | None = None) -> str:
        """Issue a random refresh token; only its SHA-256 hash is stored locally.

        ``days=None`` (the default) means the token does NOT expire: it stays
        valid until the user logs out or unticks «مرا به خاطر بسپار». Pass a
        number of days only for tests / temporary sessions.
        """
        import secrets
        from datetime import timedelta

        token = secrets.token_urlsafe(32)
        if days is None:
            expires = NO_EXPIRY
        else:
            expires = (
                datetime.now(timezone.utc) + timedelta(days=days)
            ).isoformat(timespec="seconds")
        self.store.save_session_token(int(user_id), _hash_token(token), expires)
        log.info("remember-me token issued for admin user id=%s (expires=%s)",
                 user_id, expires)
        return token

    def authenticate_with_token(self, user_id: int, token: str) -> LoginResult:
        row = self.store.get_session_token(int(user_id))
        if row is None or not token:
            raise AuthError(MSG_INVALID_CREDENTIALS, "invalid_token")
        expires = _parse_lock(row.get("expires_at"))
        # NO_EXPIRY keeps the session alive indefinitely; only an explicit
        # logout (or unticking «مرا به خاطر بسپار») invalidates it.
        if expires is not None and expires <= datetime.now(timezone.utc):
            self.store.clear_session_token(int(user_id))
            raise AuthError("اعتبار ورود خودکار به پایان رسیده است. گذرواژه را وارد کنید.",
                            "token_expired")
        import hmac

        if not hmac.compare_digest(str(row["token_hash"]), _hash_token(token)):
            self.store.clear_session_token(int(user_id))
            raise AuthError(MSG_INVALID_CREDENTIALS, "invalid_token")

        user = self.store.get_admin_user(int(user_id))
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        if not int(user["is_active"]):
            raise AuthError(MSG_USER_DISABLED, "user_disabled")
        self.store.clear_failed_attempts(int(user["id"]))
        self.store.audit(user["username"], "login_token", "ورود خودکار با نشانهٔ ذخیره‌شده")
        return LoginResult(principal=principal_from_row(user))

    def try_auto_login(self) -> Optional[LoginResult]:
        """Silently sign in from the saved token, or return ``None``.

        This is what lets a returning user land straight on the dashboard.
        Any failure (no token, revoked, disabled account, tampered hash) clears
        the saved state so the user simply sees the login window instead.
        """
        from .credentials import clear_token, load_token

        remembered = self.store.get_remembered_user()
        if not remembered:
            return None
        username = str(remembered.get("username") or "").strip()
        if not username:
            self.store.clear_remembered_user()
            return None

        user = self.store.get_admin_user_by_username(username)
        if user is None:
            self.forget_remembered()
            return None

        token = load_token(username)
        if not token:
            # Nothing usable stored: forget it so we do not retry every launch.
            clear_token(username)
            self.forget_remembered()
            return None

        try:
            result = self.authenticate_with_token(int(user["id"]), token)
        except AuthError as exc:
            log.info("auto login refused for %s (%s)", username, exc.code)
            clear_token(username)
            self.forget_remembered()
            return None
        log.info("auto login succeeded for admin user id=%s", user["id"])
        return result

    def has_saved_session(self) -> bool:
        """True when an automatic login is likely to succeed."""
        from .credentials import load_token

        remembered = self.store.get_remembered_user()
        if not remembered:
            return False
        username = str(remembered.get("username") or "")
        if not username:
            return False
        user = self.store.get_admin_user_by_username(username)
        if user is None or not int(user["is_active"]):
            return False
        if self.store.get_session_token(int(user["id"])) is None:
            return False
        return bool(load_token(username))

    def remembered_user_id(self) -> Optional[int]:
        remembered = self.store.get_remembered_user()
        if not remembered:
            return None
        user = self.store.get_admin_user_by_username(remembered.get("username", ""))
        if user is None:
            self.store.clear_remembered_user()
            return None
        return int(user["id"])

    def remember_user(self, user_id: int) -> str:
        """Persist the «remember me» choice and return the storage backend used."""
        from .credentials import save_token

        user = self.store.get_admin_user(int(user_id))
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        token = self.create_remember_token(int(user_id))
        backend = save_token(str(user["username"]), token)
        self.store.save_remembered_user(str(user["username"]), "")
        return backend

    def forget_remembered(self) -> None:
        """Forget the saved login: clears the DB rows and the stored token."""
        from .credentials import clear_token

        remembered = self.store.get_remembered_user()
        if remembered:
            username = str(remembered.get("username") or "")
            if username:
                clear_token(username)
        user_id = self.remembered_user_id()
        if user_id is not None:
            self.store.clear_session_token(int(user_id))
        self.store.clear_remembered_user()

    # ---- user management (Super Admin only) ------------------------------
    def create_user(
        self,
        username: str,
        full_name: str,
        password: str,
        role: str,
        *,
        is_active: bool = True,
        actor: str = "system",
    ) -> Principal:
        username = to_english_digits(str(username or "")).strip()
        full_name = str(full_name or "").strip()
        if not USERNAME_RE.match(username):
            raise AuthError(MSG_USERNAME_INVALID, "username_invalid")
        if not full_name:
            raise AuthError(MSG_NAME_REQUIRED, "name_required")
        if role not in ALL_ROLES:
            raise AuthError(MSG_ROLE_INVALID, "role_invalid")
        problem = validate_password_strength(password)
        if problem:
            raise AuthError(problem, "weak_password")
        if self.store.get_admin_user_by_username(username) is not None:
            raise AuthError(MSG_USERNAME_TAKEN, "username_taken")

        row = self.store.create_admin_user(username, full_name, hash_password(password), role, is_active)
        self.store.audit(actor, "user_create", f"username={username} role={role}")
        return principal_from_row(row)

    def update_user(
        self,
        user_id: int,
        *,
        full_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        actor: str = "system",
        actor_id: int | None = None,
    ) -> Principal:
        user = self.store.get_admin_user(user_id)
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        if role is not None and role not in ALL_ROLES:
            raise AuthError(MSG_ROLE_INVALID, "role_invalid")
        if full_name is not None and not str(full_name).strip():
            raise AuthError(MSG_NAME_REQUIRED, "name_required")
        if is_active is False and actor_id is not None and int(user_id) == int(actor_id):
            raise AuthError(MSG_CANNOT_DEACTIVATE_SELF, "self_deactivate")

        demoting = (role is not None and role != ROLE_SUPER_ADMIN
                    and user["role"] == ROLE_SUPER_ADMIN and int(user["is_active"]))
        deactivating = (is_active is False and user["role"] == ROLE_SUPER_ADMIN
                        and int(user["is_active"]))
        if demoting or deactivating:
            others = self.store.count_active_super_admins(exclude_user_id=int(user_id))
            if others == 0:
                raise AuthError(MSG_LAST_SUPER_ADMIN, "last_super_admin")

        updated = self.store.update_admin_user(
            int(user_id), full_name=full_name, role=role, is_active=is_active
        )
        self.store.audit(actor, "user_update", f"id={user_id} role={role} active={is_active}")
        return principal_from_row(updated)

    def delete_user(self, user_id: int, *, actor: str = "system", actor_id: int | None = None) -> None:
        user = self.store.get_admin_user(user_id)
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        if actor_id is not None and int(user_id) == int(actor_id):
            raise AuthError(MSG_CANNOT_DELETE_SELF, "self_delete")
        if user["role"] == ROLE_SUPER_ADMIN and int(user["is_active"]):
            if self.store.count_active_super_admins(exclude_user_id=int(user_id)) == 0:
                raise AuthError(MSG_LAST_SUPER_ADMIN, "last_super_admin")
        self.store.delete_admin_user(int(user_id))
        self.store.audit(actor, "user_delete", f"id={user_id}")

    def reset_password(
        self, user_id: int, new_password: str, *, actor: str = "system", require_super_admin: bool = True
    ) -> None:
        user = self.store.get_admin_user(user_id)
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        problem = validate_password_strength(new_password)
        if problem:
            raise AuthError(problem, "weak_password")
        self.store.set_admin_password(int(user_id), hash_password(new_password))
        self.store.audit(actor, "password_reset", f"id={user_id}")

    def change_own_password(
        self, user_id: int, current_password: str, new_password: str, confirm_password: str
    ) -> None:
        user = self.store.get_admin_user(user_id)
        if user is None:
            raise AuthError(MSG_NOT_FOUND, "not_found")
        if not verify_password(current_password, user["password_hash"]):
            raise AuthError(MSG_WRONG_CURRENT_PASSWORD, "wrong_current_password")
        if new_password != confirm_password:
            raise AuthError(MSG_PASSWORD_MISMATCH, "password_mismatch")
        problem = validate_password_strength(new_password)
        if problem:
            raise AuthError(problem, "weak_password")
        self.store.set_admin_password(int(user_id), hash_password(new_password))
        self.store.audit(user["username"], "password_change", "تغییر گذرواژه توسط خود کاربر")

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def is_allowed(role: str, permission: str) -> bool:
        return has_permission(role, permission)


def principal_from_row(row: dict) -> Principal:
    return Principal(
        user_id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"]),
        role=str(row["role"]),
    )


def _hash_token(token: str) -> str:
    """Tokens are stored only as a SHA-256 digest."""
    import hashlib

    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _parse_lock(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment
