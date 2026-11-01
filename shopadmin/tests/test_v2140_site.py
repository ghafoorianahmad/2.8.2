"""v2.14.0: table PDFs, Persian text fixes, duplicates, price check, branches, delete."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.site import catalog as cat
from app.site import dedup
from app.site import pdf_import as imp
from app.site import pdf_table as pt
from app.site import textfix as tf
from app.site.store import SiteDataError, SiteStore

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "13-پاوربانک.pdf"
if not SAMPLE.is_file():   # a worktree: the samples folder of the main checkout
    SAMPLE = Path(r"E:\DSH-Workspace\Software Asr\samples\13-پاوربانک.pdf")


# ---- text ------------------------------------------------------------------------------
def test_visual_order_is_turned_back():
    assert tf.clean_line("تاحيضوت") == "توضیحات"
    assert tf.clean_line("ﻻاك ناونع") == "عنوان کالا"
    assert tf.clean_line("MAGSAFE (داگراساپ ههام12 يتناراگ)(يجنران)(كنابرواپ)") == \
        "(پاوربانک)(نارنجی)(گارانتی 12 ماهه پاسارگاد) MAGSAFE"
    assert tf.clean_line("ژراش بسانم20000mAh يﻻاب تيفرظ") == "ظرفیت بالای 20000mAh مناسب شارژ"
    assert tf.clean_line("(12V/1.87A (22.5W") == "12V/1.87A (22.5W)"
    assert tf.clean_line("Battery Capacity: 20000mAh-") == "Battery Capacity: 20000mAh"


def test_match_key_ignores_letters_digits_order_and_brackets():
    assert tf.match_key("پاور بانك (مشكي) ۲۰۰۰۰") == tf.match_key("۲۰۰۰۰ پاور بانک مشکی")
    assert tf.match_key("Power Bank 20000mAh") == tf.match_key("power  bank 20000 MAH")
    assert tf.numbers("POWER BANK 20000 22.5W") == {"20000", "22.5"}


def test_price_like_numbers():
    blocked = tf.price_number_forms("٢,٢٠٠")
    assert blocked == {"2200", "2,200"}
    assert tf.price_problems("فقط ۲٬۲۰۰ تومان")
    assert tf.price_problems("قیمت: 5000")
    assert tf.price_problems("Powerbank 2,200", blocked)
    assert not tf.price_problems("Powerbank 2200mAh", blocked)
    assert not tf.price_problems("Anker Prime 12,000 / 20,000 / 27,650mAh")
    assert not tf.price_problems("POWER BANK 100000 SOLAR XTREME")


# ---- the real powerbank PDF ---------------------------------------------------------------
@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample PDF not on this computer")
def test_powerbank_sample_is_35_items_with_35_pictures():
    rows = pt.read_table_pdf(SAMPLE.read_bytes())
    assert len(rows) == 35
    assert sum(1 for r in rows if r.image) == 35
    first = rows[0]
    assert first.product_code == "15200005"
    assert first.brand_name == "ADATA"
    assert first.colors == ["سفید"]
    assert "ADATA" in first.name and "(" not in first.name
    assert first.prices                       # read, but never in the item
    for row in rows:
        item = row.item("powerbank", "x-1")
        assert "price" not in item and not any("٢,٢٠٠" in str(v) for v in item.values())
        assert "ك" not in str(item) and "ي" not in str(item)
        assert row.brand_name
    assert rows[13].colors == ["مشکی", "سبز"]
    assert rows[23].colors == ["سرمه‌ای"]


# ---- duplicates -----------------------------------------------------------------------------
def _item(name, code="", colors=("مشکی",)):
    return {"name": name, "product_code": code, "colors": [{"name": c} for c in colors]}


def test_same_code_merges_and_same_title_merges():
    old = _item("POWER BANK 20000 PD20W BOSTON", "15300101")
    assert dedup.classify(_item("other title", "15300101"), [old]).status == dedup.UPDATED
    assert dedup.classify(_item("POWER BANK 20000 PD20W BOSTON", "15300101"), [old]).status \
        == dedup.DUPLICATE
    assert dedup.classify(_item("boston pd20w 20000 power bank"), [old]).status == dedup.DUPLICATE


def test_near_titles_are_asked_and_guards_never_merge():
    old = _item("POWER BANK 20000 PD20W BOSTON")
    assert dedup.classify(_item("POWER BANK 20000 PD20W BOSTN"), [old]).status == dedup.NEAR
    # capacity, wattage, colour, model name differ -> a new item
    assert dedup.classify(_item("POWER BANK 10000 PD20W BOSTON"), [old]).status == dedup.NEW
    assert dedup.classify(_item("POWER BANK 20000 PD22W BOSTON"), [old]).status == dedup.NEW
    assert dedup.classify(_item("POWER BANK 20000 PD20W BOSTON", colors=("سفید",)),
                          [old]).status == dedup.NEW
    assert dedup.classify(_item("POWER BANK 20000 PD20W MILOS"), [old]).status == dedup.NEW
    # two different supplier codes are two items
    assert dedup.classify(_item("POWER BANK 20000 PD20W BOSTON", "2"),
                          [_item("POWER BANK 20000 PD20W BOSTON", "1")]).status == dedup.NEW


@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample PDF not on this computer")
def test_import_twice_into_a_branch(tmp_path):
    store = SiteStore(tmp_path / "site")
    rows = pt.read_table_pdf(SAMPLE.read_bytes())
    prepared = imp.prepare(store, "powerbank", rows)
    assert imp.summary(prepared)["new"] == 35
    counts = imp.apply(store, "powerbank", prepared)
    assert counts["new"] == 35
    items = store.items(cat.KIND_ACCESSORY)
    assert len(items) == 35 and all(i["group"] == "powerbank" for i in items)
    assert all(store.has_photo(i["image"]) for i in items)
    # the same PDF again: all duplicates, nothing new
    again = imp.prepare(store, "powerbank", pt.read_table_pdf(SAMPLE.read_bytes()))
    assert imp.summary(again)[dedup.DUPLICATE] == 35
    imp.apply(store, "powerbank", again)
    assert len(store.items(cat.KIND_ACCESSORY)) == 35
    # the dropped prices stop a publish if one comes back in a text
    assert "2,200" in store.blocked_prices()
    item = store.items(cat.KIND_ACCESSORY)[0]
    store.upsert({**item, "description": "فقط 2,200"}, old_code=item["code"])
    assert any("شبیه قیمت" in p for p in store.preview()["problems"])


def test_near_decisions(tmp_path):
    store = SiteStore(tmp_path / "site")
    store.upsert({"code": "boston", "category": "accessory", "name": "POWER BANK 20000 BOSTON",
                  "group": "powerbank", "colors": [{"name": "مشکی"}]})
    row = pt.TableRow(page=1, name="POWER BANK 20000 BOSTN", colors=["مشکی"], brand_name="X")
    prepared = imp.prepare(store, "powerbank", [row])
    assert prepared[0].match.status == dedup.NEAR
    assert imp.undecided(prepared) == 1
    assert imp.apply(store, "powerbank", prepared)["skipped"] == 1      # never auto-merged
    prepared[0].decision = imp.SAME
    assert imp.apply(store, "powerbank", prepared)["updated"] == 1
    assert len(store.items()) == 1 and store.items()[0]["brand_name"] == "X"
    prepared[0].decision = imp.SEPARATE
    assert imp.apply(store, "powerbank", prepared)["new"] == 1
    assert len(store.items()) == 2


# ---- branches, delete, counts ---------------------------------------------------------------
def test_groups_brands_and_catalog_groups(tmp_path):
    store = SiteStore(tmp_path / "site")
    key = store.add_group("Smart Watch")
    assert key == "smart_watch"
    persian = store.add_group("محافظ صفحه")
    assert persian.startswith("g")
    with pytest.raises(SiteDataError):
        store.add_group("محافظ صفحه")
    store.rename_group(key, "ساعت هوشمند")
    assert store.group_name(key) == "ساعت هوشمند"
    store.upsert({"code": "w-1", "category": "accessory", "name": "Watch", "group": key})
    catalog, _files = store.build()
    # v2.16.0: the manager's own categories go too (an empty one = a «به‌زودی» card)
    assert catalog["groups"] == [{"key": key, "name": "ساعت هوشمند"},
                                 {"key": persian, "name": "محافظ صفحه"}]
    assert "product_code" not in str(catalog)
    assert store.add_brand("Honor") == "honor"
    store.rename_brand("honor", "آنر")
    assert any(b["name"] == "آنر" for b in store.brands())


def test_delete_and_undo_in_48_hours(tmp_path):
    now = [datetime(2026, 10, 28, tzinfo=timezone.utc)]
    store = SiteStore(tmp_path / "site", clock=lambda: now[0])
    store.upsert({"code": "a-1", "category": "accessory", "name": "A", "group": "case"})
    store.upsert({"code": "a-2", "category": "accessory", "name": "B", "group": "case",
                  "hidden": True})
    assert store.counts("accessory") == {"total": 2, "shown": 1, "hidden": 1}
    store.delete("a-1")
    assert [i["code"] for i in store.items()] == ["a-2"]
    assert store.undelete("a-1")
    store.delete("a-1")
    now[0] += timedelta(hours=49)
    assert not store.recently_deleted() and not store.undelete("a-1")


def test_rollback_brings_a_deleted_item_back(tmp_path):
    store = SiteStore(tmp_path / "site")
    store.upsert({"code": "a-1", "category": "accessory", "name": "A", "group": "case"})
    catalog, _f = store.build()
    before = store.snapshot(catalog, None)
    store.delete("a-1")
    path = store.add_history({"commit": "c1", "previous": {}, "snapshot_before": before})
    store.finish_rollback(path, {"snapshot_before": before}, "c2")
    assert [i["code"] for i in store.items()] == ["a-1"]
