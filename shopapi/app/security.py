"""API-key authentication, text normalization and masking."""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import Settings, get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Arabic yeh/kaf and Arabic-Indic + Persian digits -> Persian yeh/kaf + ASCII digits.
_FA_TRANS = str.maketrans(
    {
        "ي": "ی",
        "ك": "ک",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)


def normalize_fa(text: str | None) -> str:
    """Normalize Persian/Arabic text for search and phone comparison only."""
    if text is None:
        return ""
    return str(text).translate(_FA_TRANS).strip()


def mask_phone(phone: str | None) -> str:
    p = normalize_fa(phone or "")
    if not p:
        return "****"
    if len(p) < 4:
        return "*" * len(p)
    return p[:2] + "*" * (len(p) - 4) + p[-2:]


def mask_name(name: str | None) -> str:
    if not name:
        return ""
    return name[0] + "*" * (len(name) - 1)


def _role_for_key(settings: Settings, api_key: str) -> str | None:
    """Resolve an API key to a role using constant-time comparison.

    Every configured key is compared on every request (no early exit) so that
    timing does not reveal which key matched or how many keys are configured.
    """
    candidates = (
        ("bot", settings.bot_api_key),
        ("site", settings.site_api_key),
        ("admin", settings.admin_api_key),
    )
    supplied = api_key.encode("utf-8")
    matched: str | None = None
    for role, key in candidates:
        if not key:
            continue
        if hmac.compare_digest(supplied, key.encode("utf-8")):
            matched = role
    return matched


def get_api_identity(
    api_key: str | None = Security(API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> str:
    """Resolve the X-API-Key header to a role: bot, site or admin."""
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    role = _role_for_key(settings, api_key)
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return role


def require_admin(role: str = Depends(get_api_identity)) -> str:
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin key required")
    return role
