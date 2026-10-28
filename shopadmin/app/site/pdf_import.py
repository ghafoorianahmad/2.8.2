"""v2.14.0: «افزودن از PDF» into one branch (accessory category) — no Qt here.

``prepare`` reads the rows (``pdf_table``), gives each one a site code and
classifies it against the branch (``dedup``); the preview edits ``title`` /
``specs`` / ``removed`` / ``decision`` of each ``Prepared`` row; ``apply``
saves. Prices never reach the data: only their numbers go to the publish check.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import catalog as cat
from . import dedup
from . import pdf_table as pt
from .store import SiteStore

SAME, SEPARATE = "same", "separate"


@dataclass
class Prepared:
    row: pt.TableRow
    item: dict
    match: dedup.Match
    removed: bool = False
    #: for a «near» row: SAME («یکی است») or SEPARATE («جداست»); None = not decided
    decision: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.match.status == dedup.NEAR:
            if self.decision == SAME:
                return dedup.UPDATED
            if self.decision == SEPARATE:
                return dedup.NEW
        return self.match.status


def _image_name(code: str) -> str:
    return cat.photo_name(code)


def prepare(store: SiteStore, group: str, rows: list[pt.TableRow]) -> list[Prepared]:
    existing = [i for i in store.items(cat.KIND_ACCESSORY) if i["group"] == group]
    taken = {i["code"] for i in store.items()}
    out: list[Prepared] = []
    earlier: list[dict] = []
    for row in rows:
        code = cat.code_from_name(row.name or row.product_code or "item", taken)
        item = row.item(group, code, _image_name(code) if row.image else "")
        match = dedup.classify(item, existing, earlier)
        prepared = Prepared(row=row, item=item, match=match, notes=list(row.notes))
        if match.status in (dedup.NEW, dedup.NEAR):
            taken.add(code)
            earlier.append(item)
        out.append(prepared)
    return out


def summary(rows: list[Prepared]) -> dict[str, int]:
    out = {dedup.NEW: 0, dedup.UPDATED: 0, dedup.DUPLICATE: 0, dedup.NEAR: 0, "removed": 0,
           "no_image": 0}
    for row in rows:
        if row.removed:
            out["removed"] += 1
            continue
        out[row.status] += 1
        if row.row.image is None:
            out["no_image"] += 1
    return out


def undecided(rows: list[Prepared]) -> int:
    return sum(1 for r in rows if not r.removed and r.match.status == dedup.NEAR
               and r.decision is None)


def apply(store: SiteStore, group: str, rows: list[Prepared]) -> dict[str, int]:
    """Save the preview. A «near» row with no decision is skipped (never merged).
    Returns the counts: new / updated / duplicate / skipped."""
    counts = {"new": 0, "updated": 0, "duplicate": 0, "skipped": 0}
    data = store.load()
    by_code = {i["code"]: n for n, i in enumerate(data["items"])}
    store.add_price_marks(p for r in rows for p in r.row.prices)
    data = store.load()
    added_codes: dict[int, str] = {}       # id(earlier item) -> saved code
    for prepared in rows:
        if prepared.removed:
            counts["skipped"] += 1
            continue
        status = prepared.status
        if status == dedup.NEAR:           # not decided: never merged automatically
            counts["skipped"] += 1
            continue
        item = dict(prepared.item, group=group)
        target = prepared.match.other
        if status in (dedup.UPDATED, dedup.DUPLICATE) and target is not None:
            code = target.get("code") if prepared.match.row_index < 0 else \
                added_codes.get(id(target), target.get("code"))
            index = next((n for n, i in enumerate(data["items"]) if i["code"] == code), None)
            if index is None:
                status = dedup.NEW
            else:
                old = data["items"][index]
                if prepared.row.image is not None:
                    name = old.get("image") or _image_name(old["code"])
                    store.add_photo(name, prepared.row.image)
                    item["image"] = name
                merged = dedup.merge(old, {**item, "image": item.get("image") or ""})
                merged["code"], merged["group"] = old["code"], group
                data["items"][index] = cat.clean_item(merged)
                counts["updated" if status == dedup.UPDATED else "duplicate"] += 1
                continue
        # a new item
        taken = {i["code"] for i in data["items"]}
        code = item["code"] if item["code"] not in taken else cat.code_from_name(item["name"], taken)
        item["code"] = code
        if prepared.row.image is not None:
            item["image"] = _image_name(code)
            store.add_photo(item["image"], prepared.row.image)
        else:
            item["image"] = ""
        data["items"].append(cat.clean_item(item))
        added_codes[id(prepared.item)] = code
        by_code[code] = len(data["items"]) - 1
        counts["new"] += 1
    store.save(data)
    return counts
