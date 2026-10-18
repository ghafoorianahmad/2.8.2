"""Staff sign-in: login, logout, current account, password change, bootstrap.

Passwords are verified here and only a hash of the session token is stored.
A wrong username and a wrong password give the same answer in the same time.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import deps, security_watch
from ..config import Settings
from ..db_own import OwnDB
from ..schemas import (
    BootstrapIn,
    ChangePasswordIn,
    ForgotCompleteIn,
    ForgotIn,
    ForgotOut,
    ForgotStatusIn,
    LoginIn,
    LoginOut,
    MeOut,
    StaffOut,
)
from ..security import Identity, get_identity, get_staff_identity, is_local_request
from ..staff import (
    DUMMY_HASH,
    ROLE_SUPER_ADMIN,
    effective_permissions,
    parse_permission_list,
    hash_password,
    hash_token,
    new_session_token,
    validate_password,
    validate_username,
    verify_password,
)
from ..util import now_utc

router = APIRouter(prefix="/auth")

GENERIC_LOGIN_ERROR = "Invalid username or password"


class LoginRateLimiter:
    """Per-address cap on login attempts (in memory; resets on restart).

    Account lockout stops guessing one password; this stops one machine from
    cycling through many usernames.
    """

    def __init__(self, max_attempts: int = 20, window_seconds: float = 300.0) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.max_attempts:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = LoginRateLimiter()
#: Forgot-password calls are public, so they get their own, tighter cap.
forgot_limiter = LoginRateLimiter(max_attempts=10, window_seconds=300.0)

#: A request nobody answers lapses after a day; once approved, the person has
#: this long to choose the new password.
FORGOT_PENDING_HOURS = 24
FORGOT_APPROVED_MINUTES = 30


def staff_out(row: dict) -> StaffOut:
    locked_until = row.get("locked_until")
    locked = bool(locked_until) and locked_until > now_utc().isoformat(timespec="seconds")
    grants = parse_permission_list(row.get("perm_grant"))
    revokes = parse_permission_list(row.get("perm_revoke"))
    return StaffOut(
        extra_permissions=sorted(grants),
        removed_permissions=sorted(revokes),
        permissions=sorted(effective_permissions(row["role"], grants, revokes)),
        id=row["id"],
        username=row["username"],
        full_name=row["full_name"] or "",
        role=row["role"],
        active=bool(row["active"]),
        must_change_password=bool(row["must_change_password"]),
        locked=locked,
        created_at=row["created_at"],
        last_login_at=row.get("last_login_at"),
    )


def _permissions(role: str, row: dict | None = None) -> list[str]:
    row = row or {}
    return sorted(effective_permissions(role, row.get("perm_grant"), row.get("perm_revoke")))


@router.get("/status")
def auth_status(db: OwnDB = Depends(deps.get_db)) -> dict:
    """Public: whether the first super admin still has to be created."""
    return {"bootstrap_required": db.count_staff() == 0}


@router.post("/bootstrap", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def bootstrap(
    payload: BootstrapIn,
    identity: Identity = Depends(get_identity),
    db: OwnDB = Depends(deps.get_db),
) -> StaffOut:
    """Create the very first super admin.

    Only the server-local service key may do this (it never leaves the server),
    and only while no staff account exists at all.
    """
    if identity.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    if db.count_staff() > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Staff accounts already exist")
    for problem in (validate_username(payload.username), validate_password(payload.password)):
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    row = db.create_staff(payload.username, payload.full_name.strip(), ROLE_SUPER_ADMIN,
                          hash_password(payload.password))
    db.audit("service", "staff_bootstrap", f"staff id={row['id']} username={row['username']}")
    return staff_out(row)


@router.post("/login", response_model=LoginOut)
def login(
    payload: LoginIn,
    request: Request,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> LoginOut:
    address = request.client.host if request.client else "?"
    if not login_limiter.check(address):
        security_watch.report(db, "login_throttled", address)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts")

    user = db.get_staff_by_username(payload.username.strip())
    if user is None:
        verify_password(payload.password, DUMMY_HASH)  # equal timing
        db.audit("anonymous", "login_failed", f"unknown username from {address}")
        security_watch.report(db, "login_failed", address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    now = now_utc()
    now_s = now.isoformat(timespec="seconds")
    if user["locked_until"] and user["locked_until"] > now_s:
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked")

    if not verify_password(payload.password, user["password_hash"]):
        attempts = int(user["failed_attempts"]) + 1
        if attempts >= settings.login_max_attempts:
            lock_until = (now + timedelta(minutes=settings.login_lock_minutes)).isoformat(
                timespec="seconds")
            db.update_staff(user["id"], failed_attempts=0, locked_until=lock_until)
            db.audit(user["username"], "account_locked", f"from {address}")
            security_watch.report(db, "account_locked", address)
        else:
            db.update_staff(user["id"], failed_attempts=attempts)
        db.audit(user["username"], "login_failed", f"from {address}")
        security_watch.report(db, "login_failed", address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    if not user["active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    db.purge_expired_sessions()
    lifetime = (timedelta(days=settings.staff_remember_days) if payload.remember
                else timedelta(hours=settings.staff_session_hours))
    expires_at = (now + lifetime).isoformat(timespec="seconds")
    token = new_session_token()
    db.create_session(hash_token(token), user["id"], expires_at, payload.client.strip())
    user = db.update_staff(user["id"], failed_attempts=0, locked_until=None, last_login_at=now_s)
    db.audit(user["username"], "login", f"from {address} client={payload.client.strip()[:40]}")
    return LoginOut(token=token, expires_at=expires_at, user=staff_out(user),
                    permissions=_permissions(user["role"], user))


@router.post("/console-login", response_model=LoginOut)
def console_login(
    request: Request,
    identity: Identity = Depends(get_identity),
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
) -> LoginOut:
    """Password-less session for the server edition of ShopAdmin.

    The server edition runs on the shop server itself, which is reachable only
    through Remote Desktop, so it shows no login screen. It proves it is on the
    server by presenting the service key (which exists only there) from the
    loopback address; the session is the first active super admin's. Clients
    and the LAN can never use this: other addresses are refused even with the
    right key.
    """
    if identity.kind != "service" or not is_local_request(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    admin = next((u for u in db.list_staff()
                  if u["role"] == ROLE_SUPER_ADMIN and u["active"]), None)
    if admin is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No super admin exists yet")
    now = now_utc()
    expires_at = (now + timedelta(hours=settings.staff_session_hours)).isoformat(
        timespec="seconds")
    token = new_session_token()
    db.purge_expired_sessions()
    db.create_session(hash_token(token), admin["id"], expires_at, "server-console")
    admin = db.update_staff(admin["id"], last_login_at=now.isoformat(timespec="seconds"))
    db.audit(admin["username"], "console_login", "server edition, loopback")
    return LoginOut(token=token, expires_at=expires_at, user=staff_out(admin),
                    permissions=_permissions(admin["role"], admin))


@router.post("/logout")
def logout(identity: Identity = Depends(get_staff_identity),
           db: OwnDB = Depends(deps.get_db)) -> dict:
    db.delete_session(identity.token_hash)
    db.audit(identity.actor, "logout", "")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(identity: Identity = Depends(get_staff_identity),
       db: OwnDB = Depends(deps.get_db)) -> MeOut:
    user = db.get_staff(identity.user_id)
    return MeOut(user=staff_out(user), permissions=_permissions(user["role"], user))


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    identity: Identity = Depends(get_staff_identity),
    db: OwnDB = Depends(deps.get_db),
) -> dict:
    user = db.get_staff(identity.user_id)
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is wrong")
    problem = validate_password(payload.new_password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "New password must differ from the current one")
    db.update_staff(user["id"], password_hash=hash_password(payload.new_password),
                    must_change_password=0)
    # Every other device signed in as this account is signed out.
    db.delete_sessions_for_user(user["id"], keep_token_hash=identity.token_hash)
    db.audit(identity.actor, "password_change", "")
    return {"ok": True}


# ---- forgot password ------------------------------------------------------
# 1. The login window asks (POST /auth/forgot) and keeps the returned secret.
# 2. An admin approves or rejects it inside ShopAdmin.
# 3. After approval the same window sends the secret plus a new password of the
#    person's choosing (POST /auth/forgot/complete); the old password and every
#    open session of the account are gone.
# The secret is stored hashed; the answer never reveals whether a username exists.
def _request_if_valid(db: OwnDB, payload: ForgotStatusIn) -> dict | None:
    row = db.get_password_request(payload.request_id)
    if row is None or not hmac.compare_digest(row["token_hash"], hash_token(payload.token)):
        return None
    if row["status"] in ("pending", "approved") and row["expires_at"] <= now_utc().isoformat(
            timespec="seconds"):
        db.set_password_request_status(row["id"], "expired")
        row["status"] = "expired"
    return row


@router.post("/forgot", response_model=ForgotOut)
def forgot_password(payload: ForgotIn, request: Request,
                    db: OwnDB = Depends(deps.get_db)) -> ForgotOut:
    address = request.client.host if request.client else "?"
    if not forgot_limiter.check(address):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    token = new_session_token()
    user = db.get_staff_by_username(payload.username.strip())
    if user is None or not user["active"]:
        db.audit("anonymous", "password_request_unknown", f"from {address}")
        # Looks like a real request; status checks on it stay "pending".
        return ForgotOut(request_id=10 ** 9 + secrets.randbelow(10 ** 9), token=token)
    expires = (now_utc() + timedelta(hours=FORGOT_PENDING_HOURS)).isoformat(timespec="seconds")
    row = db.create_password_request(user["id"], hash_token(token), expires)
    db.add_event("password_request", row["id"], user["username"])
    db.audit(user["username"], "password_request", f"from {address}")
    return ForgotOut(request_id=row["id"], token=token)


@router.post("/forgot/status")
def forgot_status(payload: ForgotStatusIn, request: Request,
                  db: OwnDB = Depends(deps.get_db)) -> dict:
    address = request.client.host if request.client else "?"
    if not forgot_limiter.check(address):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    row = _request_if_valid(db, payload)
    # Unknown / wrong secret is indistinguishable from "still waiting".
    return {"status": row["status"] if row else "pending"}


@router.post("/forgot/complete")
def forgot_complete(payload: ForgotCompleteIn, request: Request,
                    db: OwnDB = Depends(deps.get_db)) -> dict:
    address = request.client.host if request.client else "?"
    if not forgot_limiter.check(address):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    row = _request_if_valid(db, payload)
    if row is None or row["status"] != "approved":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request is not approved")
    problem = validate_password(payload.new_password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    user = db.get_staff(row["staff_id"])
    if user is None or not user["active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request is not approved")
    if verify_password(payload.new_password, user["password_hash"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "New password must differ from the old one")
    db.update_staff(user["id"], password_hash=hash_password(payload.new_password),
                    must_change_password=0, failed_attempts=0, locked_until=None)
    db.delete_sessions_for_user(user["id"])
    db.set_password_request_status(row["id"], "used", user["username"])
    db.audit(user["username"], "password_forgot_completed", f"from {address}")
    return {"ok": True}
