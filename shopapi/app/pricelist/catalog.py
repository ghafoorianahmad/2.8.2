"""Phones in the catalogue: products priced per color from the active list.

Which products are phones is decided by their group (``app/groups.py``, v2.6.0);
this module only knows the list side: a product's colors are the mapped rows
present in the *active* list — unmapped or ignored rows never reach a customer.
Phones are sold on the distributor's availability (a price in the current
valid list), not on the accounting stock; a phone without one is hidden.
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
        """[{id, color, part, unit_price (Rial or None), available}] for a product.
        v2.6.2: one entry per color AND part (ZAA / CHA …), each with its price."""
        out = []
        rows = self.variants.get(int(code), [])
        # The type (شرکتی / ویتنام …) is a choice only when the product has several.
        several_kinds = len({v.get("kind") or "" for v in rows}) > 1
        for v in rows:
            price = v["price_rial"] if self.fresh else None
            part = v.get("part_code") or (v.get("kind") or "" if several_kinds else "")
            out.append({
                "id": v["id"], "color": v["color"], "part": part,
                "unit_price": float(price) if price else None,
                "available": bool(price),
            })
        return out

    def variant(self, code: int, variant_id: int) -> dict | None:
        for v in self.colors(code):
            if v["id"] == int(variant_id):
                return v
        return None

    def sellable(self, code: int) -> bool:
        """In the current valid list with at least one available color."""
        return self.has(code) and any(v["available"] for v in self.colors(code))

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
