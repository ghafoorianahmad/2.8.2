"""Sign-in and staff account management — all decided BY THE SERVER.

Staff accounts, passwords, roles, lockouts and sessions live in shopapi. This
module is the desktop side of that conversation: it sends the username and
password once, keeps the session token the server returns, and maps every
server answer to a Persian message. Nothing here can grant a right the server
does not grant.

«مرا به خاطر بسپار» keeps the server's long-lived session token in the Windows
Credential Manager (``credentials.py``); the password is never stored.
"""
from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from typing import Optional

from .api_client import (
    ApiAuthError,
    ApiError,
    MSG_BAD_CREDENTIALS,
    MSG_DISABLED,
    MSG_LOCKED,
    ShopApiClient,
)
from .logging_setup import get_logger
from .permissions import Principal, has_permission
from .persian import to_english_digits
from .statuses import ALL_ROLES
from .store import Store

log = get_logger("auth")

#: Mirrors the server policy so most mistakes are caught before a round trip.
MAX_FAILED_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

MSG_INVALID_CREDENTIALS = MSG_BAD_CREDENTIALS
MSG_USER_DISABLED = MSG_DISABLED
MSG_USER_LOCKED = MSG_LOCKED
MSG_EMPTY_FIELDS = "نام کاربری و گذرواژه را وارد کنید."
MSG_PASSWORD_TOO_SHORT = f"گذرواژه باید حداقل {MIN_PASSWORD_LENGTH} نویسه باشد."
MSG_PASSWORD_LETTERS_DIGITS = "گذرواژه باید هم حرف و هم عدد داشته باشد."
MSG_PASSWORD_MISMATCH = "تکرار گذرواژه با گذرواژهٔ جدید یکسان نیست."
MSG_USERNAME_INVALID = "نام کاربری باید ۳ تا ۳۲ نویسهٔ انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد."
MSG_NAME_REQUIRED = "نام و نام خانوادگی را وارد کنید."
MSG_ROLE_INVALID = "نقش انتخاب‌شده معتبر نیست."
MSG_CANNOT_DEACTIVATE_SELF = "نمی‌توانید حساب کاربری خودتان را غیرفعال کنید."


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


def validate_password_strength(password: str) -> Optional[str]:
    """Return a Persian error message, or ``None`` when acceptable."""
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        return MSG_PASSWORD_TOO_SHORT
    if not re.search(r"[A-Za-z؀-ۿ]", text) or not re.search(r"\d", to_english_digits(text)):
        return MSG_PASSWORD_LETTERS_DIGITS
    return None


def principal_from_staff(row: dict) -> Principal:
    return Principal(
        user_id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row.get("full_name") or ""),
        role=str(row["role"]),
    )


def _code_for(exc: ApiError) -> str:
    if exc.kind in ("connection", "timeout"):
        return "offline"
    return {401: "invalid_credentials", 403: "forbidden", 423: "user_locked",
            429: "rate_limited", 409: "conflict", 422: "invalid", 404: "not_found"}.get(
        exc.status_code or 0, "server_error")


def _auth_error(exc: ApiError) -> AuthError:
    return AuthError(exc.message, _code_for(exc))


def client_name() -> str:
    """A label for this computer in the server's session list and audit log."""
    try:
        return socket.gethostname()[:60]
    except OSError:  # pragma: no cover
        return ""


class AuthService:
    def __init__(self, store: Store, api: ShopApiClient) -> None:
        self.store = store
        self.api = api

    # ---- server bootstrap (first super admin) ------------------------------
    def server_needs_first_admin(self) -> bool:
        """Asks the server; raises :class:`AuthError` when it cannot be reached."""
        try:
            return bool(self.api.auth_status().get("bootstrap_required"))
        except ApiError as exc:
            raise _auth_error(exc) from exc

    def create_first_super_admin(self, service_key: str, username: str, full_name: str,
                                 password: str) -> Principal:
        """Only possible on the server computer, with the server's service key."""
        username = to_english_digits(str(username or "")).strip()
        self._check_new_account(username, full_name, password)
        try:
            row = self.api.bootstrap(service_key, username, str(full_name).strip(), password)
        except ApiError as exc:
            raise _auth_error(exc) from exc
        log.info("first super admin created on the server")
        return principal_from_staff(row)

    # ---- login -----------------------------------------------------------
    def authenticate(self, username: str, password: str, *, remember: bool = False) -> LoginResult:
        username = to_english_digits(str(username or "")).strip()
        password = str(password or "")
        if not username or not password:
            raise AuthError(MSG_EMPTY_FIELDS, "empty_fields")
        try:
            payload = self.api.login(username, password, remember=remember,
                                     client_name=client_name())
        except ApiError as exc:
            log.warning("login refused by the server (%s)", _code_for(exc))
            raise _auth_error(exc) from exc
        user = payload["user"]
        log.info("signed in: staff id=%s role=%s", user["id"], user["role"])
        return LoginResult(principal=principal_from_staff(user),
                           must_change_password=bool(user.get("must_change_password")))

    def logout(self) -> None:
        """End the session on the server and forget any saved login here."""
        self.forget_remembered()
        self.api.logout()

    # ---- remember me (server session token, never the password) ---------------
    def remember_user(self, username: str) -> str:
        """Keep the current session token for automatic sign-in next time.

        Returns the storage backend used: 'keyring', 'file' or 'none'.
        """
        from .credentials import save_token

        if not self.api.token:
            return "none"
        backend = save_token(str(username), self.api.token)
        if backend != "none":
            self.store.save_remembered_user(str(username))
        return backend

    def remembered_username(self) -> Optional[str]:
        remembered = self.store.get_remembered_user()
        name = str((remembered or {}).get("username") or "").strip()
        return name or None

    def has_saved_session(self) -> bool:
        from .credentials import load_token

        username = self.remembered_username()
        return bool(username and load_token(username))

    def try_auto_login(self) -> Optional[LoginResult]:
        """Resume the saved server session, or return ``None``.

        A rejected token (expired, revoked, account disabled) is forgotten. A
        server that is simply unreachable keeps the token for next time.
        """
        from .credentials import load_token

        username = self.remembered_username()
        if not username:
            return None
        token = load_token(username)
        if not token:
            self.forget_remembered()
            return None
        self.api.set_token(token)
        try:
            me = self.api.me()
        except ApiAuthError:
            log.info("saved session was rejected by the server; forgetting it")
            self.forget_remembered()
            return None
        except ApiError as exc:
            log.info("auto login not possible right now (%s)", exc.kind)
            self.api.set_token("")
            return None
        user = me.get("user") or {}
        if not user:
            self.api.set_token("")
            return None
        log.info("resumed saved session for staff id=%s", user.get("id"))
        return LoginResult(principal=principal_from_staff(user),
                           must_change_password=bool(user.get("must_change_password")))

    def forget_remembered(self) -> None:
        from .credentials import clear_token

        username = self.remembered_username()
        if username:
            clear_token(username)
        self.store.clear_remembered_user()

    # ---- own password ----------------------------------------------------
    def change_own_password(self, current_password: str, new_password: str,
                            confirm_password: str) -> None:
        if new_password != confirm_password:
            raise AuthError(MSG_PASSWORD_MISMATCH, "password_mismatch")
        problem = validate_password_strength(new_password)
        if problem:
            raise AuthError(problem, "weak_password")
        try:
            self.api.change_password(current_password, new_password)
        except ApiError as exc:
            raise _auth_error(exc) from exc

    # ---- staff management (super admin; enforced by the server) ---------------
    def list_users(self) -> list[dict]:
        try:
            return self.api.list_staff()
        except ApiError as exc:
            raise _auth_error(exc) from exc

    def create_user(self, username: str, full_name: str, password: str, role: str,
                    *, must_change_password: bool = True) -> Principal:
        username = to_english_digits(str(username or "")).strip()
        self._check_new_account(username, full_name, password)
        if role not in ALL_ROLES:
            raise AuthError(MSG_ROLE_INVALID, "role_invalid")
        try:
            row = self.api.create_staff(username, str(full_name).strip(), role, password,
                                        must_change_password=must_change_password)
        except ApiError as exc:
            raise _auth_error(exc) from exc
        return principal_from_staff(row)

    def update_user(self, user_id: int, *, full_name: str | None = None,
                    role: str | None = None, is_active: bool | None = None,
                    actor_id: int | None = None) -> Principal:
        if role is not None and role not in ALL_ROLES:
            raise AuthError(MSG_ROLE_INVALID, "role_invalid")
        if full_name is not None and not str(full_name).strip():
            raise AuthError(MSG_NAME_REQUIRED, "name_required")
        if is_active is False and actor_id is not None and int(user_id) == int(actor_id):
            raise AuthError(MSG_CANNOT_DEACTIVATE_SELF, "self_deactivate")
        try:
            row = self.api.update_staff(int(user_id), full_name=full_name, role=role,
                                        active=is_active)
        except ApiError as exc:
            raise _auth_error(exc) from exc
        return principal_from_staff(row)

    def delete_user(self, user_id: int) -> None:
        try:
            self.api.delete_staff(int(user_id))
        except ApiError as exc:
            raise _auth_error(exc) from exc

    def reset_password(self, user_id: int, new_password: str,
                       *, must_change_password: bool = True) -> None:
        problem = validate_password_strength(new_password)
        if problem:
            raise AuthError(problem, "weak_password")
        try:
            self.api.reset_staff_password(int(user_id), new_password,
                                          must_change_password=must_change_password)
        except ApiError as exc:
            raise _auth_error(exc) from exc

    def unlock_user(self, user_id: int) -> None:
        try:
            self.api.unlock_staff(int(user_id))
        except ApiError as exc:
            raise _auth_error(exc) from exc

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _check_new_account(username: str, full_name: str, password: str) -> None:
        if not USERNAME_RE.match(username):
            raise AuthError(MSG_USERNAME_INVALID, "username_invalid")
        if not str(full_name or "").strip():
            raise AuthError(MSG_NAME_REQUIRED, "name_required")
        problem = validate_password_strength(password)
        if problem:
            raise AuthError(problem, "weak_password")

    @staticmethod
    def is_allowed(role: str, permission: str) -> bool:
        return has_permission(role, permission)
