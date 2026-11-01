"""v2.16.0: «فارسی‌سازی توضیحات» — cleaning codes / noise and the offline dictionary."""
from __future__ import annotations

import pytest

from app.site import catalog as cat
from app.site import farsi
from app.site import pdf_import as imp
from app.site import pdf_table as pt
from app.site.store import SiteStore

WORDS = farsi.Dictionary()


def test_codes_and_noise_out_of_the_description():
    raw = ("GNMPB20KTCDBL | GNMPB20KTCTGD • | GNMPB20KTCBL | GNMPB20KTCOG • 6935100182599 | "
           "6935100182612 | • 9904907091974 | 9904907091806 • Integrated Type-C Cable • "
           "15W Wireless Charging • Magnetic Attraction • PD 20W Charging • LCD Display")
    assert farsi.clean_description(raw) == ("Integrated Type-C Cable • 15W Wireless Charging • "
                                            "Magnetic Attraction • PD 20W Charging • LCD Display")
    # repeated parts once, a trailing «|» gone, Persian kept as it is
    assert farsi.clean_description("12V=1.5A • 12V=1.5A • گریپ بهتر | • لکه") == \
        "12V=1.5A • گریپ بهتر • لکه"


@pytest.mark.parametrize("token", ["20000mAh", "20000MAH", "PD20W", "T10000", "22.5W", "QC3.0",
                                   "USB-A2/A3/A4", "Type-C", "100000"])
def test_capacities_and_models_are_not_codes(token):
    assert not farsi.is_code(token)


@pytest.mark.parametrize("token", ["GNMPB20KTCDBL", "6935100182599", "15100052", "SKU123456789"])
def test_codes(token):
    assert farsi.is_code(token)


def test_code_rows_out_of_the_specs_and_numbers_kept():
    specs = [["نوع", "پاوربانک"], ["SKU", "GNMPB20KTCBK |"], ["EAN", "6935100182605 |"],
             ["Bluetooth Version", "5.4"], ["Material", "ABS + PC |"], ["Type•C Port Output", "5V/3A"]]
    assert farsi.clean_specs(specs) == [["نوع", "پاوربانک"], ["Bluetooth Version", "5.4"],
                                        ["Material", "ABS + PC"], ["Type-C Port Output", "5V/3A"]]


@pytest.mark.parametrize("english, persian", [
    ("Battery Capacity", "ظرفیت باتری"),
    ("Input", "ورودی"),
    ("Output", "خروجی"),
    ("Wireless Charging", "شارژ بی‌سیم"),
    ("Digital Display", "نمایشگر دیجیتال"),
    ("Magnetic Attraction", "اتصال مغناطیسی"),
    ("Fast Charging", "شارژ سریع"),
    ("LED Flashlight", "چراغ قوه LED"),
    ("PD 20W Fast Charging", "شارژ سریع PD 20W"),
    ("15W Wireless Charging", "شارژ بی‌سیم 15W"),
    ("QC 3.0 22.5W Output", "خروجی QC 3.0 22.5W"),
    ("USB-C Input", "ورودی USB-C"),
    ("Type-C Port Input", "ورودی درگاه Type-C"),
    ("USB-A Ports3", "3 درگاه USB-A"),
    ("Magsafe compatible", "سازگار با MagSafe"),
    ("in 35 Minutes65%-0%", "شارژ 0% تا 65% در 35 دقیقه"),
    ("15W MagSafe", "15W MagSafe"),                 # nothing to translate: unchanged
    ("Micro/Type", "Micro/Type"),                   # a name, not «نوع»
    ("10000 میلیآمپر ساعت", "10000 میلی‌آمپر ساعت"),
])
def test_dictionary(english, persian):
    assert WORDS.translate(english) == persian


def test_a_persian_sentence_keeps_its_order():
    assert WORDS.translate("طراحی Ultra Slim با ضخامت کم") == "طراحی بسیار باریک با ضخامت کم"


def test_manager_words_win_and_running_twice_changes_nothing():
    words = farsi.Dictionary([["Fast Charging", "فست‌شارژ"], ["Hyper Core", "هایپرکور"]])
    assert words.translate("Fast Charging") == "فست‌شارژ"
    item = {"description": "Fast Charging • Hyper Core • SKU123456789",
            "specs": [["Battery Capacity", "20000mAh"], ["EAN", "6935100182605"]]}
    once = farsi.farsi_item(item, words)
    assert once["description"] == "فست‌شارژ • هایپرکور"
    assert once["specs"] == [["ظرفیت باتری", "20000mAh"]]
    assert not farsi.changed(once, farsi.farsi_item(once, words))


def test_store_words_farsi_many_and_undo(tmp_path):
    store = SiteStore(tmp_path / "site")
    store.upsert({"code": "pb-1", "category": "accessory", "name": "PB 1", "group": "powerbank",
                  "description": "GNMPB20KTCDBL • LED Flashlight",
                  "specs": [["Input", "5V/2A"], ["SKU", "GNMPB20KTCBK"]]})
    store.set_fa_words([["Hyper Core", "هایپرکور"], ["", "x"], ["Hyper Core", "دوباره"]])
    assert store.fa_words() == [["Hyper Core", "هایپرکور"]]
    assert len(store.farsi_changes(["pb-1"])) == 1
    assert store.farsi_many(["pb-1"]) == 1
    item = store.get("pb-1")
    assert item["description"] == "چراغ قوه LED"
    assert item["specs"] == [["ورودی", "5V/2A"]]
    assert store.farsi_many(["pb-1"]) == 0           # nothing more to do
    assert store.farsi_undo_count() == 1
    assert store.farsi_undo() == 1
    assert store.get("pb-1")["description"] == "GNMPB20KTCDBL • LED Flashlight"


def test_every_pdf_import_is_translated(tmp_path):
    store = SiteStore(tmp_path / "site")
    row = pt.TableRow(page=1, number="1", name="POWER BANK 20000 TEST", brand_name="X",
                      specs=[["Battery Capacity", "20000mAh"], ["SKU", "ABCDEF123456"]],
                      description="Fast Charging • 6935100182599")
    prepared = imp.prepare(store, "powerbank", [row])
    assert prepared[0].item["description"] == "شارژ سریع"
    assert prepared[0].item["specs"] == [["ظرفیت باتری", "20000mAh"]]
    imp.apply(store, "powerbank", prepared)
    saved = store.items(cat.KIND_ACCESSORY)[0]
    assert saved["description"] == "شارژ سریع"
