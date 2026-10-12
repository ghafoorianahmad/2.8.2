"""Helpers for the two interactive scripts (login, read-only price check).

They run on the server before shopapi exists there, so they use only the local
settings (``TG_PROXY``) or a proxy typed into a hidden prompt.
"""
from __future__ import annotations

import getpass
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .config import BASE_DIR, Settings
from .proxies import ProxyLink, parse_proxy_link


def hidden(prompt: str, *, reader=getpass.getpass) -> str:
    return (reader(prompt) or "").strip()


def choose_proxies(settings: Settings, *, reader=getpass.getpass) -> list[ProxyLink | None]:
    """TG_PROXY links in order; else one typed (hidden) link; '' = direct."""
    links = [p for p in (parse_proxy_link(r) for r in settings.local_proxies) if p]
    if settings.local_proxies and not links:
        print("TG_PROXY is set but no link in it is a valid MTProto proxy link.")
    if links:
        print(f"Using {len(links)} proxy link(s) from TG_PROXY.")
        return list(links)
    while True:
        raw = hidden("MTProto proxy link (tg://proxy?... or https://t.me/proxy?..., hidden;"
                     " Enter = direct connection): ", reader=reader)
        if not raw:
            return [None]
        link = parse_proxy_link(raw)
        if link is not None:
            print("Proxy:", link.masked())
            return [link]
        print("That is not a valid proxy link. Try again.")


def require_admin() -> None:
    from . import secure_store
    if sys.platform == "win32" and not secure_store.is_admin():
        sys.exit("Run this from an elevated PowerShell (Run as administrator): the session "
                 "file is readable only by SYSTEM and Administrators.")


def require_api_credentials(settings: Settings) -> None:
    missing = [n for n in settings.missing() if n != "WORKER_API_KEY"]
    if missing:
        sys.exit(f"Set {' and '.join(missing)} in {BASE_DIR / '.env'} first "
                 "(from my.telegram.org, logged in as the shop's account).")


# ---- price-list parser (vendored into the server package) -------------------------
_PARSER_CANDIDATES = (
    BASE_DIR / "vendor" / "pricelist",                               # server package
    BASE_DIR.parent / "shopapi" / "app" / "pricelist",               # development tree
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_parser() -> tuple[ModuleType, ModuleType]:
    """(parser, pricing) modules: from ``vendor/`` or the sibling shopapi."""
    for folder in _PARSER_CANDIDATES:
        if (folder / "parser.py").is_file() and (folder / "pricing.py").is_file():
            return (_load("shoptg_pricelist_parser", folder / "parser.py"),
                    _load("shoptg_pricelist_pricing", folder / "pricing.py"))
    raise FileNotFoundError("price-list parser not found (vendor/pricelist or ../shopapi)")


def summarize(parsed, pricing: ModuleType, *, sample: int = 8) -> list[str]:
    """Human-readable report of a parsed list (no personal data in a price list)."""
    rows = parsed.rows
    priced = [r for r in rows if pricing.customer_price_rial(r.naghd, r.raval) is not None]
    lines = [
        f"List date      : {parsed.list_date}",
        f"Rows           : {len(rows)} ({len(priced)} with a price, "
        f"{len(rows) - len(priced)} unavailable)",
        f"Sections       : {', '.join(parsed.sections)}",
    ]
    if parsed.warnings:
        lines.append(f"Warnings       : {len(parsed.warnings)}")
        lines += [f"  - {w}" for w in parsed.warnings[:5]]
    lines.append("Sample rows (customer price in Rial):")
    for row in rows[:sample]:
        price = pricing.customer_price_rial(row.naghd, row.raval)
        shown = f"{price:,}" if price is not None else "unavailable"
        lines.append(f"  [{row.section}] {row.description} | {row.kind or '-'} | "
                     f"{row.color or '-'} -> {shown}")
    return lines
