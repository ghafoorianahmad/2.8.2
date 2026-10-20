"""Authentication: API keys (service/channels) and staff sessions."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from . import deps
from .config import Settings, get_settings
from .db_own import OwnDB
from .text import mask_name, mask_phone, normalize_fa  # noqa: F401 (re-export)
from .staff import ROLE_SERVICE, effective_permissions, has_permission, hash_token
from .util import now_utc

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
BEARER = HTTPBearer(auto_error=False)

LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
#: last_seen_at is refreshed at most this often (avoids a write per request).
_TOUCH_INTERVAL = timedelta(seconds=60)

def _role_for_key(settings: Settings, api_key: str) -> str | None:
    """Resolve an API key to a role using constant-time comparison.

    Every configured key is compared on every request (no early exit) so that
    timing does not reveal which key matched or how many keys are configured.
    """
    candidates = (
        ("bot", settings.bot_api_key),
        ("site", settings.site_api_key),
        ("admin", settings.admin_api_key),
        ("worker", settings.worker_api_key),
    )
    supplied = api_key.encode("utf-8")
    matched: str | None = None
    for role, key in candidates:
        if not key:
            continue
        if hmac.compare_digest(supplied, key.encode("utf-8")):
            matched = role
    return matched


def is_local_request(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in LOCAL_HOSTS


def _resolve_key(request: Request, settings: Settings, api_key: str) -> str:
    role = _role_for_key(settings, api_key)
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if role in ("bot", "admin", "worker") and settings.service_keys_local_only and not is_local_request(request):
        # The bot/admin keys live only on the server; from the LAN they are as
        # good as a leaked secret, so they are refused even when correct.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key not accepted from this address")
    return role


def get_api_identity(
    request: Request,
    api_key: str | None = Security(API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> str:
    """Resolve the X-API-Key header to a channel role: bot, site or admin."""
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    role = _resolve_key(request, settings, api_key)
    if role == ROLE_WORKER:
        # The Telegram worker is not a sales channel: /worker/* only.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this key")
    return role


ROLE_WORKER = "worker"


def require_worker(
    request: Request,
    api_key: str | None = Security(API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> str:
    """The Telegram price/proxy worker (WORKER_API_KEY, loopback only)."""
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    if _resolve_key(request, settings, api_key) != ROLE_WORKER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this key")
    return ROLE_WORKER


@dataclass(frozen=True)
class Identity:
    """Who is calling: a staff member (bearer session) or the server service key."""

    kind: str          # "staff" | "service" | "channel"
    role: str          # staff role, "service", or the channel ("bot"/"site")
    username: str
    user_id: int | None = None
    token_hash: str | None = None
    must_change_password: bool = False
    #: v2.7.0: a staff member's role permissions plus their own ticks.
    permissions: frozenset | None = None

    def can(self, permission: str) -> bool:
        if self.permissions is not None:
            return permission in self.permissions
        return has_permission(self.role, permission)

    @property
    def actor(self) -> str:
        return self.username


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _staff_identity(db: OwnDB, token: str) -> Identity:
    token_hash = hash_token(token)
    session = db.get_session(token_hash)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    if session is None:
        raise unauthorized
    now = now_utc()
    expires = _parse_ts(session["expires_at"])
    if expires is None or expires <= now:
        db.delete_session(token_hash)
        raise unauthorized
    user = db.get_staff(session["user_id"])
    if user is None or not user["active"]:
        db.delete_session(token_hash)
        raise unauthorized
    last_seen = _parse_ts(session["last_seen_at"])
    if last_seen is None or now - last_seen > _TOUCH_INTERVAL:
        db.touch_session(token_hash)
    return Identity(
        kind="staff", role=user["role"], username=user["username"], user_id=user["id"],
        token_hash=token_hash, must_change_password=bool(user["must_change_password"]),
        permissions=effective_permissions(user["role"], user.get("perm_grant"),
                                          user.get("perm_revoke")),
    )


def get_identity(
    request: Request,
    api_key: str | None = Security(API_KEY_HEADER),
    bearer: HTTPAuthorizationCredentials | None = Security(BEARER),
    settings: Settings = Depends(get_settings),
    db: OwnDB = Depends(deps.get_db),
) -> Identity:
    """Staff bearer session, or an API key (service / channel)."""
    if bearer is not None and bearer.credentials:
        return _staff_identity(db, bearer.credentials)
    if api_key:
        role = _resolve_key(request, settings, api_key)
        if role == "admin":
            return Identity(kind="service", role=ROLE_SERVICE, username="service")
        if role == ROLE_WORKER:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this key")
        return Identity(kind="channel", role=role, username=role)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in required")


def get_staff_identity(identity: Identity = Depends(get_identity)) -> Identity:
    if identity.kind != "staff":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in required")
    return identity


def require_permission(permission: str):
    """Dependency factory: the caller must hold ``permission`` (server-side check)."""

    def _check(identity: Identity = Depends(get_identity)) -> Identity:
        if identity.must_change_password:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
        if not identity.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
        return identity

    return _check


def require_any(*permissions: str):
    """v2.8.2: the caller holds at least one of ``permissions``."""

    def _check(identity: Identity = Depends(get_identity)) -> Identity:
        if identity.must_change_password:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
        if not any(identity.can(p) for p in permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
        return identity

    return _check


def require_signed_in(identity: Identity = Depends(get_identity)) -> Identity:
    """Any staff member (whatever their permissions) or the service key."""
    if identity.kind not in ("staff", "service"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this key")
    return identity


def get_catalog_channel(identity: Identity = Depends(get_identity)) -> str:
    """Product/group reads: any channel key, the service key, or a staff member allowed
    to see products (v2.7.0: not a sales user)."""
    if identity.kind == "staff":
        from .staff import CATALOG_READERS

        if not any(identity.can(p) for p in CATALOG_READERS):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
        return "staff"
    if identity.kind == "service":
        return "admin"
    return identity.role
