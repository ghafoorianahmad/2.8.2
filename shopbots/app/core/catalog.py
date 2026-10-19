"""Catalog: groups and product pages from shopapi (prices never come from a user)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..shopapi import ShopApiClient
from ..utils import normalize_digits

# Arabic yeh/kaf -> Persian; the accounting data mixes both (reference §9.7).
_LETTER_TRANS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})


def normalize_search(text: str | None) -> str:
    """Search text with Persian letters, ASCII digits and single spaces."""
    return " ".join(normalize_digits(text).translate(_LETTER_TRANS).split())


@dataclass(frozen=True)
class Color:
    """One color of a phone priced from the distributor list (shopapi variant)."""
    id: int
    name: str
    price: float | None      # Rial; None = no price -> inquiry only
    available: bool
    #: v2.6.2: part / region code (ZAA, CHA …) picked after the color; "" = none
    part: str = ""


@dataclass(frozen=True)
class Product:
    code: int
    name: str
    price: float
    available: float
    #: Phones: the colors (price after the customer picks one). Empty = none.
    colors: tuple[Color, ...] = ()
    #: v2.6.1: «قیمت با استعلام» - no price, no cart, only «استعلام قیمت».
    on_inquiry: bool = False
    #: v2.8.0 (phones): stock in «سازه حساب»; 0 = «درخواست خرید» only, None = not used
    stock: float | None = None

    @property
    def in_stock(self) -> bool:
        return self.available > 0

    @property
    def has_colors(self) -> bool:
        return bool(self.colors)

    def color(self, color_id: int) -> Color | None:
        return next((c for c in self.colors if c.id == int(color_id)), None)

    def as_cache(self) -> dict:
        """The shape kept in the conversation between screens."""
        cache = {"name": self.name, "price": self.price, "qty": self.available}
        if self.on_inquiry:
            cache["inquiry"] = True
        if self.stock is not None:
            cache["stock"] = self.stock
        if self.colors:
            cache["colors"] = [
                {"id": c.id, "name": c.name, "price": c.price, "available": c.available,
                 "part": c.part}
                for c in self.colors
            ]
        return cache


def _colors(raw) -> tuple[Color, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for v in raw:
        if not isinstance(v, dict) or v.get("id") is None:
            continue
        price = v.get("unit_price")
        out.append(Color(
            id=int(v["id"]), name=str(v.get("color") or ""),
            price=float(price) if price else None,
            available=bool(v.get("available")) and bool(price),
            part=str(v.get("part") or "").strip(),
        ))
    return tuple(out)


def _product(it: dict, code=None) -> Product:
    return Product(
        code=int(it.get("code") or code),
        name=str(it.get("name") or ""),
        price=float(it.get("unit_price") or 0),
        available=float(it.get("available_qty") or 0),
        colors=_colors(it.get("variants")),
        on_inquiry=bool(it.get("price_on_inquiry")) or it.get("priced_by") == "inquiry",
        stock=float(it["stock_qty"]) if it.get("stock_qty") is not None else None,
    )


@dataclass
class ProductPage:
    items: list[Product] = field(default_factory=list)
    page: int = 1
    pages: int = 1
    total: int = 0


class CatalogService:
    def __init__(self, api: ShopApiClient, *, page_size: int):
        self.api = api
        self.page_size = max(1, int(page_size))

    async def groups(self) -> list[dict]:
        return [g for g in (await self.api.get_groups() or []) if isinstance(g, dict)]

    async def products(
        self, *, q: str | None = None, group: int | None = None, page: int = 1
    ) -> ProductPage:
        page = max(1, int(page or 1))
        query = (normalize_search(q) or None) if q is not None else None
        # v2.6.0: lists show only what can be ordered now (phones: in the current
        # valid price list; everything else: in stock). Out-of-stock items are
        # reached through «درخواست کالای ناموجود».
        result = await self.api.get_products(
            q=query, group=group, page=page, page_size=self.page_size, in_stock=True,
        )
        items = [
            _product(it)
            for it in (result.get("items") or [])
            if isinstance(it, dict) and it.get("code") is not None
        ]
        total = int(result.get("total") or 0)
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        return ProductPage(items=items, page=page, pages=pages, total=total)

    async def product(self, code: int) -> Product | None:
        """One product by code (deep link / typed code), also when out of stock."""
        found = await self.api.get_product(int(code))
        if not isinstance(found, dict):
            return None
        return _product(found, code)


#: Deep-link payload from the site: ``/start kala_289`` (REQUIREMENTS §7).
DEEP_LINK_PREFIX = "kala_"
MAX_PRODUCT_CODE = 10_000_000
#: What a customer may type in front of the code shown on the site:
#: "kala_289", "kala289", "kala-289", "کد 289", "کد کالا: 289", "#289".
_CODE_PREFIX = re.compile(r"^(?:kala[\s_\-]*|کد(?:\s*کالا)?\s*[:：]?\s*|#)", re.IGNORECASE)


#: Site model references (REQUIREMENTS §9a): ``m_<slug>`` (deep link), the
#: copied «name + کد مدل: slug» text, or a bare slug with a hyphen. Only the
#: shape is checked here; shopapi resolves the model.
_MODEL_DEEP = re.compile(r"^m_[A-Za-z0-9-]{1,62}$")
_MODEL_LABEL = re.compile(r"[کك]د\s*مدل")
_MODEL_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
MAX_MODEL_TEXT = 400


def looks_like_model_ref(text: str | None) -> bool:
    value = normalize_digits(text).strip()
    if not value or len(value) > MAX_MODEL_TEXT:
        return False
    return bool(_MODEL_DEEP.match(value) or _MODEL_LABEL.search(value)
                or (len(value) <= 62 and _MODEL_SLUG.match(value.lower())))


def parse_product_ref(text: str | None, *, allow_bare_code: bool = False) -> int | None:
    """``kala_289`` (also as a /start parameter) -> 289; with ``allow_bare_code``
    a message that is only a number counts too (the fallback when the start
    parameter is lost)."""
    value = normalize_digits(text).strip()
    prefixed = _CODE_PREFIX.match(value)
    if prefixed:
        value = value[prefixed.end():].strip()
    elif not allow_bare_code:
        return None
    if not value.isdigit() or len(value) > 8:
        return None
    code = int(value)
    return code if 0 < code <= MAX_PRODUCT_CODE else None
