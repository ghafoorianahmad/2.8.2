"""All user-facing Persian texts, loaded from one editable JSON file.

The defaults ship as `messages.fa.json` next to this module. An operator copy
(``BOT_MESSAGES_FILE``, on the server ``%ProgramData%\\ShopServer\\messages.fa.json``)
overrides them key by key, so a key missing from an older copy falls back to
the default. A broken file never stops the bots: the defaults are used and the
problem is logged. Changes take effect on restart.

Shop placeholders ({shop_name}, {shop_phone}, {currency}, ...) are filled in
at load time (v2.6.1: with no shop phone set, every line holding {shop_phone}
is left out instead of showing an empty or placeholder number); per-message placeholders ({order_id}, {total}, ...) stay for
`str.format` in the engine. Every text is available as a module constant
(`texts.WELCOME`, `texts.BTN_MENU`, ...).
"""
from __future__ import annotations

import json
import logging
import os
import string
from pathlib import Path

logger = logging.getLogger("shopbots.texts")

DEFAULT_FILE = Path(__file__).resolve().with_name("messages.fa.json")
ENV_VAR = "BOT_MESSAGES_FILE"

#: Where the current texts came from (for logs / status).
SOURCE = str(DEFAULT_FILE)
SHOP: dict[str, str] = {}
ORDER_STATUS_FA: dict[str, str] = {}


class _Keep(dict):
    """format_map helper: unknown placeholders are left untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _escape(value: str) -> str:
    # Shop values are substituted before the engine's str.format call.
    return str(value).replace("{", "{{").replace("}", "}}")


def fill_shop(text: str, shop: dict[str, str]) -> str:
    """Replace only the shop placeholders; leave {order_id} etc. in place."""
    fields = _Keep({k: _escape(v) for k, v in shop.items()})
    try:
        return string.Formatter().vformat(text, (), fields)
    except (ValueError, IndexError):
        # An unbalanced brace in an operator edit: show the text as written.
        return text


#: The shipped placeholder of ``shop_phone`` (older operator copies still hold
#: it): treated as "no phone set".
PHONE_PLACEHOLDER = "شماره تلفن فروشگاه"


def phone_missing(shop: dict[str, str]) -> bool:
    value = str(shop.get("shop_phone") or "").strip()
    return not value or value == PHONE_PLACEHOLDER


def drop_phone_lines(text: str) -> str:
    """Remove every line that shows the shop phone (no phone configured)."""
    if "{shop_phone}" not in text:
        return text
    return "\n".join(line for line in text.split("\n") if "{shop_phone}" not in line)


def _read(path: Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("top level must be a JSON object")
    return data


def _section(data: dict, name: str) -> dict[str, str]:
    raw = data.get(name)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, (str, int, float))}


def load(path: str | os.PathLike | None = None) -> str:
    """(Re)load the texts. Returns the source actually used."""
    global SOURCE, SHOP, ORDER_STATUS_FA

    defaults = _read(DEFAULT_FILE)
    merged = {name: _section(defaults, name) for name in ("shop", "buttons", "messages", "order_status")}
    source = str(DEFAULT_FILE)

    override = path or os.environ.get(ENV_VAR, "").strip()
    if override and Path(override).resolve() != DEFAULT_FILE:
        try:
            custom = _read(Path(override))
        except FileNotFoundError:
            logger.warning("texts: %s not found - using built-in texts", override)
        except (OSError, ValueError) as exc:
            logger.error(
                "texts: %s is invalid (%s) - using built-in texts / "
                "فایل متن‌ها خراب است؛ متن‌های پیش‌فرض استفاده شد",
                override, type(exc).__name__,
            )
        else:
            for name in merged:
                merged[name].update({k: v for k, v in _section(custom, name).items()})
            source = str(override)

    SHOP = dict(merged["shop"])
    no_phone = phone_missing(SHOP)
    if no_phone:
        SHOP["shop_phone"] = ""       # the invoice cards skip an empty entry too
    for key, value in {**merged["buttons"], **merged["messages"]}.items():
        globals()[key] = fill_shop(drop_phone_lines(value) if no_phone else value, SHOP)
    ORDER_STATUS_FA = dict(merged["order_status"])
    SOURCE = source
    return source


def status_fa(status: str | None) -> str:
    status = str(status or "")
    return ORDER_STATUS_FA.get(status, status)


load()
