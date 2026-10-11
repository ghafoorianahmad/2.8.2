"""Catalog: groups and product pages from shopapi (prices never come from a user)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..shopapi import ShopApiClient
from ..utils import normalize_digits

# Arabic yeh/kaf -> Persian; the accounting data mixes both (reference §9.7).
_LETTER_TRANS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})


def normalize_search(text: str | None) -> str:
    """Search text with Persian letters, ASCII digits and single spaces."""
    return " ".join(normalize_digits(text).translate(_LETTER_TRANS).split())


@dataclass(frozen=True)
class Product:
    code: int
    name: str
    price: float
    available: float

    @property
    def in_stock(self) -> bool:
        return self.available > 0

    def as_cache(self) -> dict:
        """The shape kept in the conversation between screens."""
        return {"name": self.name, "price": self.price, "qty": self.available}


@dataclass
class ProductPage:
    items: list[Product] = field(default_factory=list)
    page: int = 1
    pages: int = 1
    total: int = 0


class CatalogService:
    def __init__(self, api: ShopApiClient, *, page_size: int, show_out_of_stock: bool):
        self.api = api
        self.page_size = max(1, int(page_size))
        self.show_out_of_stock = show_out_of_stock

    async def groups(self) -> list[dict]:
        return [g for g in (await self.api.get_groups() or []) if isinstance(g, dict)]

    async def products(
        self, *, q: str | None = None, group: int | None = None, page: int = 1
    ) -> ProductPage:
        page = max(1, int(page or 1))
        query = (normalize_search(q) or None) if q is not None else None
        result = await self.api.get_products(
            q=query, group=group, page=page, page_size=self.page_size,
            in_stock=not self.show_out_of_stock,
        )
        items = [
            Product(
                code=it.get("code"),
                name=str(it.get("name") or ""),
                price=float(it.get("unit_price") or 0),
                available=float(it.get("available_qty") or 0),
            )
            for it in (result.get("items") or [])
            if isinstance(it, dict)
        ]
        total = int(result.get("total") or 0)
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        return ProductPage(items=items, page=page, pages=pages, total=total)
