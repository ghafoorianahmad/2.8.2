"""Product groups chosen in ShopAdmin (v2.6.0, «گروه‌های کالا»).

Three checkboxes per accounting group (``Gkala``):

* ``show_in_bot`` - only these groups reach customers (lists, search, a product
  opened by code, orders). A group without a row is hidden: a fresh install
  shows nothing until staff choose, so nothing is ever sold by accident.
* ``is_phone`` - a phone is an item of a phone group. Phones are shown, priced
  and sold ONLY from the current valid distributor price list (see
  ``pricelist/catalog.py``) and only while phone sales are open (``sales.py``).
  Before v2.6.0 a phone was "an item mapped in the price list"; with no list
  (or no mapping) a phone was sold at the accounting price even while sales
  were closed. The group decides now, never the mapping.
* ``price_on_inquiry`` (v2.6.1) - customers see the item without a price and
  cannot order it; the bot offers «استعلام قیمت» (an item request of kind
  ``inquiry``). Wins over the phone rules: nothing of such a group is sold.

v2.6.1: the groups form a tree in «سازه حساب» (``Gkala.g_kala`` = parent; e.g.
گوشی with one subgroup per brand). Every flag is inherited: a subgroup is shown /
a phone group / on inquiry when it or any ancestor is. A product of a brand
subgroup of گوشی is therefore a phone even when only گوشی is ticked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db_own import OwnDB

#: Gkala's root («کلیه کالاها»); never a real group.
ROOT_CODE = 0


def _code(group) -> int | None:
    try:
        return int(group)
    except (TypeError, ValueError):
        return None


def parent_map(groups) -> dict[int, int]:
    """{group: parent} from reader rows (``code`` + ``parent``); the root is left out."""
    out: dict[int, int] = {}
    for g in groups or ():
        code = _code(g.get("code")) if isinstance(g, dict) else None
        parent = _code(g.get("parent")) if isinstance(g, dict) else None
        if code is None or code == ROOT_CODE:
            continue
        if parent is not None and parent != ROOT_CODE and parent != code:
            out[code] = parent
    return out


@dataclass
class GroupConfig:
    shown: set[int] = field(default_factory=set)
    phone: set[int] = field(default_factory=set)
    inquiry: set[int] = field(default_factory=set)
    #: child -> parent (empty when the tree was not read: own flags only).
    parents: dict[int, int] = field(default_factory=dict)

    def chain(self, group) -> list[int]:
        """The group and its ancestors, nearest first (cycles are cut)."""
        code = _code(group)
        out: list[int] = []
        while code is not None and code not in out:
            out.append(code)
            code = self.parents.get(code)
        return out

    def _inherits(self, group, flags: set[int]) -> bool:
        return any(c in flags for c in self.chain(group))

    def visible(self, group) -> bool:
        return self._inherits(group, self.shown)

    def is_phone(self, group) -> bool:
        return self._inherits(group, self.phone)

    def on_inquiry(self, group) -> bool:
        return self._inherits(group, self.inquiry)

    def inquiry_groups(self) -> set[int]:
        """Every known group code that is on inquiry (own or inherited)."""
        known = set(self.parents) | set(self.parents.values()) | self.inquiry
        return {c for c in known if self.on_inquiry(c)}

    @property
    def configured(self) -> bool:
        return bool(self.shown)

    @property
    def phone_configured(self) -> bool:
        return bool(self.phone)


def load(db: OwnDB, reader=None) -> GroupConfig:
    """The stored flags; with ``reader`` also the accounting group tree, so
    subgroups inherit. Reader errors propagate (the API answers 503): checks
    never fall back to "no inheritance", which would sell a brand subgroup of
    گوشی as an accessory."""
    cfg = GroupConfig()
    for code, row in db.list_group_settings().items():
        if row["show_in_bot"]:
            cfg.shown.add(code)
        if row["is_phone"]:
            cfg.phone.add(code)
        if row.get("price_on_inquiry"):
            cfg.inquiry.add(code)
    if reader is not None:
        cfg.parents = parent_map(reader.list_groups())
    return cfg
