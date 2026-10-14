"""Product groups chosen in ShopAdmin (v2.6.0, «گروه‌های کالا»).

Two checkboxes per accounting group (``Gkala``):

* ``show_in_bot`` - only these groups reach customers (lists, search, a product
  opened by code, orders). A group without a row is hidden: a fresh install
  shows nothing until staff choose, so nothing is ever sold by accident.
* ``is_phone`` - a phone is an item of a phone group. Phones are shown, priced
  and sold ONLY from the current valid distributor price list (see
  ``pricelist/catalog.py``) and only while phone sales are open (``sales.py``).
  Before v2.6.0 a phone was "an item mapped in the price list"; with no list
  (or no mapping) a phone was sold at the accounting price even while sales
  were closed. The group decides now, never the mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db_own import OwnDB


@dataclass
class GroupConfig:
    shown: set[int] = field(default_factory=set)
    phone: set[int] = field(default_factory=set)

    @staticmethod
    def _code(group) -> int | None:
        try:
            return int(group)
        except (TypeError, ValueError):
            return None

    def visible(self, group) -> bool:
        return self._code(group) in self.shown

    def is_phone(self, group) -> bool:
        return self._code(group) in self.phone

    @property
    def configured(self) -> bool:
        return bool(self.shown)


def load(db: OwnDB) -> GroupConfig:
    cfg = GroupConfig()
    for code, row in db.list_group_settings().items():
        if row["show_in_bot"]:
            cfg.shown.add(code)
        if row["is_phone"]:
            cfg.phone.add(code)
    return cfg
