"""v2.11.0: the GitHub token of «انتشار در سایت», encrypted with Windows DPAPI
for the signed-in Windows user (another account or a copied file cannot read
it). Stored in ShopAdmin's local settings; never logged or shown again — the
form only says whether a token is saved."""
from __future__ import annotations

import base64
from typing import Optional

from ..credentials import _dpapi

SETTING = "site_github_token"
REPO_SETTING = "site_github_repo"
BRANCH_SETTING = "site_github_branch"
PREFIX = "dpapi:"


class TokenError(ValueError):
    """Persian reason."""


def protect(token: str) -> str:
    token = (token or "").strip()
    if not token:
        raise TokenError("توکن خالی است.")
    if any(c.isspace() for c in token) or len(token) > 400:
        raise TokenError("توکن درست کپی نشده است (فاصله یا متن اضافه دارد).")
    protected = _dpapi(token.encode("utf-8"), protect=True)
    if protected is None:
        raise TokenError("رمزگذاری ویندوز (DPAPI) در دسترس نیست؛ توکن ذخیره نشد.")
    return PREFIX + base64.urlsafe_b64encode(protected).decode("ascii")


def unprotect(value: str) -> Optional[str]:
    if not value or not value.startswith(PREFIX):
        return None
    try:
        raw = base64.urlsafe_b64decode(value[len(PREFIX):].encode("ascii"))
    except (ValueError, TypeError):
        return None
    plain = _dpapi(raw, protect=False)
    try:
        return plain.decode("utf-8") if plain else None
    except UnicodeDecodeError:
        return None


def save(store, token: str) -> None:
    store.set_setting(SETTING, protect(token))


def load(store) -> Optional[str]:
    return unprotect(str(store.get_setting(SETTING, "") or ""))


def has_token(store) -> bool:
    return bool(store.get_setting(SETTING, ""))


def forget(store) -> None:
    store.set_setting(SETTING, "")
