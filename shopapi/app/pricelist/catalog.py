"""Phones in the catalogue: products priced per color from the active list.

A product is "priced from the list" as soon as one PDF row is mapped to it.
Its colors are the mapped rows present in the *active* list — unmapped or
ignored rows never reach a customer. Phones are sold on the distributor's
availability (a price in the list), not on the accounting stock.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..db_own import OwnDB
from .importer import active_list_fresh
from .repo import PriceListRepo


@dataclass
class PhoneCatalog:
    codes: set[int] = field(default_factory=set)
    variants: dict[int, list[dict]] = field(default_factory=dict)
    fresh: bool = False
    list_date: str = ""

    def has(self, code: int) -> bool:
        return int(code) in self.codes

    def colors(self, code: int) -> list[dict]:
        """[{id, color, unit_price (Rial or None), available}] for a product."""
        out = []
        for v in self.variants.get(int(code), []):
            price = v["price_rial"] if self.fresh else None
            out.append({
                "id": v["id"], "color": v["color"],
                "unit_price": float(price) if price else None,
                "available": bool(price),
            })
        return out

    def variant(self, code: int, variant_id: int) -> dict | None:
        for v in self.colors(code):
            if v["id"] == int(variant_id):
                return v
        return None

    def overlay(self, product: dict) -> dict:
        """A product dict from the reader, priced from the list when mapped."""
        code = int(product["code"])
        if code not in self.codes:
            return {**product, "priced_by": "accounting", "variants": None}
        colors = self.colors(code)
        prices = [v["unit_price"] for v in colors if v["available"]]
        return {
            **product,
            "priced_by": "pricelist",
            "variants": colors,
            # "from" price for lists; the real price is shown after a color pick.
            "unit_price": min(prices) if prices else 0.0,
            "available_qty": 1.0 if prices else 0.0,
        }


def load(db: OwnDB, settings: Settings) -> PhoneCatalog:
    repo = PriceListRepo(db)
    codes = repo.priced_codes()
    if not codes:
        return PhoneCatalog()
    active = repo.active_list()
    return PhoneCatalog(
        codes=codes,
        variants=repo.variants(active["id"] if active else None, codes),
        fresh=active_list_fresh(active, settings),
        list_date=(active or {}).get("list_date") or "",
    )
