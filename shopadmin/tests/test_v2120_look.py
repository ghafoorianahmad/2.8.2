"""v2.12.0 «ظاهر و چیدمان»: the site's look and layout on this computer
(presets and plain text only), in the preview, published with the catalogue to a
FAKE GitHub (never the real repository), undone by the 48-hour rollback, kept by
backup / restore, and shown in the local browser preview."""
from __future__ import annotations

import json
import urllib.request

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QImage  # noqa: E402

from app.site import look as lk  # noqa: E402
from app.site import photos as ph  # noqa: E402
from app.site import preview as pv  # noqa: E402
from app.site import publish as pub  # noqa: E402
from app.site.github import GitHubPublisher  # noqa: E402
from app.site.store import SiteStore  # noqa: E402

from .fake_github import TOKEN, FakeGitHub  # noqa: E402
from .test_v2110_site import image_bytes, site_folder  # noqa: E402,F401


@pytest.fixture
def store(tmp_path, admin_qapp):
    return SiteStore(tmp_path / "data" / "site")


def publisher(fake: FakeGitHub) -> GitHubPublisher:
    return GitHubPublisher(TOKEN, fake.repo, transport=fake.transport())


# ---- the look as data ----------------------------------------------------------------------
def test_defaults_are_the_site_texts_and_invalid_parts_fall_back():
    look = lk.clean_look(None)
    assert look == lk.default_look() and look["palette"] == "violet"
    assert [s["key"] for s in look["sections"]] == list(lk.SECTION_KEYS)
    bad = lk.clean_look({"palette": "neon", "logo": "../x.png",
                         "hero": {"title": "<script>alert(1)</script>عنوان", "images": ["a.jpg"]},
                         "sections": [{"key": "faq", "show": False}, {"key": "evil"}],
                         "featured": ["Bad Code", "galaxy-a57", "galaxy-a57"],
                         "store": {"phone": "۰۹۱۵ ۵۰۰ ۰۴۳۲", "map": "javascript:alert(1)",
                                   "bale": "@my_shop_bot", "hours": [["", ""], ["جمعه", "تعطیل"]]}})
    assert bad["palette"] == "violet" and bad["logo"] == "" and bad["hero"]["images"] == []
    assert "<" not in bad["hero"]["title"] and "عنوان" in bad["hero"]["title"]
    assert bad["sections"][0] == {"key": "faq", "show": False} and len(bad["sections"]) == 6
    assert bad["featured"] == ["galaxy-a57"]
    assert bad["store"]["phone"] == "09155000432" and bad["store"]["map"] == ""
    assert bad["store"]["bale"] == "https://ble.ir/my_shop_bot"
    assert bad["store"]["hours"] == [["جمعه", "تعطیل"]]


@pytest.mark.parametrize("kind,value,expected", [
    ("telegram", "@asrertebatat2_bot", "https://t.me/asrertebatat2_bot"),
    ("telegram", "t.me/asrertebatat2_bot", "https://t.me/asrertebatat2_bot"),
    ("telegram_channel", "https://telegram.me/asr_channel", "https://t.me/asr_channel"),
    ("bale", "https://ble.ir/asr_bot", "https://ble.ir/asr_bot"),
    ("map", "https://nshn.ir/abc_XYZ", "https://nshn.ir/abc_XYZ"),
    ("map", "https://www.google.com/maps/place/x", "https://www.google.com/maps/place/x"),
])
def test_links_are_normalized(kind, value, expected):
    assert lk.normalize_link(kind, value) == (expected, "")


@pytest.mark.parametrize("kind,value", [
    ("telegram", "https://evil.com/x"), ("bale", "a b"), ("map", "http://nshn.ir/x"),
    ("map", "https://evil.com/maps"), ("map", "https://www.google.com/search?q=x"),
    ("telegram", "@ab"),
])
def test_bad_links_are_refused_with_a_reason(kind, value):
    link, problem = lk.normalize_link(kind, value)
    assert link == "" and problem


def test_site_json_has_only_existing_pictures_and_visible_featured():
    look = lk.default_look()
    look["logo"] = "logo-0123456789ab.png"
    look["hero"]["images"] = ["banner-0123456789ab.jpg", "banner-ffffffffffff.jpg"]
    look["featured"] = ["galaxy-a57", "hidden-one"]
    site = lk.build_site_json(look, ["xiaomi", "apple"], ["galaxy-a57"],
                              {"logo-0123456789ab.png": "aa", "banner-0123456789ab.jpg": "bb"},
                              generated_at="t")
    assert site["format"] == lk.FORMAT and site["version"] == lk.VERSION
    assert site["logo"] == "look/logo-0123456789ab.png"
    assert site["hero"]["images"] == ["look/banner-0123456789ab.jpg"]
    assert site["featured"] == ["galaxy-a57"] and site["brand_order"] == ["xiaomi", "apple"]
    assert set(site["images"]) == {"look/logo-0123456789ab.png", "look/banner-0123456789ab.jpg"}
    text = lk.site_json_bytes(site).decode("utf-8")
    assert "<" not in text and "kala" not in text


def test_logo_and_banner_pictures_are_made_standard(admin_qapp):
    logo = QImage.fromData(ph.normalize_logo(image_bytes(600, 200)))
    assert (logo.width(), logo.height()) == (ph.LOGO_SIZE, ph.LOGO_SIZE) and logo.hasAlphaChannel()
    banner, notes = ph.normalize_banner(image_bytes(300, 300, "JPG"))
    image = QImage.fromData(banner)
    assert (image.width(), image.height()) == (1200, 600) and notes


# ---- arranging on this computer -----------------------------------------------------------
def test_order_brands_phones_and_auto_sort(store, site_folder):
    store.seed_from_folder(site_folder)
    store.upsert({"code": "galaxy-s26", "category": "phone", "brand": "samsung",
                  "name": "Galaxy S26", "release_year": 2026, "colors": [{"name": "سیاه"}]})
    store.set_brand_order(["samsung", "apple"])
    assert [b["key"] for b in store.brands()] == ["samsung", "apple"]
    store.reorder(["galaxy-s26", "galaxy-a56"])
    store.update_look(lambda look: look.update(phone_order=lk.PHONE_ORDER_MANUAL))
    codes = [i["code"] for i in store.items("phone")]
    assert codes.index("galaxy-s26") < codes.index("galaxy-a56")
    store.reorder(["galaxy-a56", "galaxy-s26"])
    codes = [i["code"] for i in store.items("phone")]
    assert codes.index("galaxy-a56") < codes.index("galaxy-s26")
    store.sort_phones_newest()
    assert [i["code"] for i in store.items("phone")][0] == "galaxy-s26"
    assert store.look()["phone_order"] == lk.PHONE_ORDER_AUTO
    # a later «خواندن از سایت» keeps the arranged brand order
    store.set_brand_order(["samsung", "apple"])
    store.seed_from_folder(site_folder)
    assert [b["key"] for b in store.brands()] == ["samsung", "apple"]


def test_look_changes_show_in_the_preview(store, site_folder):
    store.seed_from_folder(site_folder)
    assert not store.preview()["has_changes"]
    logo, _ = store.add_look_photo("logo", image_bytes(300, 300))

    def change(look):
        look["palette"] = "emerald"
        look["logo"] = logo
        look["hero"]["title"] = "گوشی تازه"
        look["sections"][5]["show"] = False
        look["featured"] = ["galaxy-a56"]
        look["store"]["phone"] = "05131234567"

    store.update_look(change)
    preview = store.preview()
    text = "\n".join(preview["lines"])
    assert preview["has_changes"] and preview["look_lines"]
    for word in ("سبز زمردی", "لوگو", "عنوان", "پنهان: سؤالات پرتکرار", "Galaxy A56", "تلفن"):
        assert word in text, word


def test_publish_sends_the_look_and_rollback_undoes_it(store, site_folder):
    store.seed_from_folder(site_folder)
    fake = FakeGitHub(files={"index.html": b"<html>", "assets/site.js": b"/* asr-site-look */"})
    with publisher(fake) as gh:
        pub.publish(store, gh, generator="test")
    first = json.loads(fake.files()["assets/catalog/site.json"])
    assert first["palette"] == "violet"
    banner, _ = store.add_look_photo("banner", image_bytes(1400, 700))
    store.update_look(lambda look: (look.update(palette="ruby"),
                                    look["hero"].update(images=[banner])))
    store.set_brand_order(["samsung", "apple"])
    with publisher(fake) as gh:
        out = pub.publish(store, gh, generator="test")
    files = fake.files()
    site = json.loads(files["assets/catalog/site.json"])
    assert site["palette"] == "ruby" and site["brand_order"] == ["samsung", "apple"]
    assert f"assets/catalog/look/{banner}" in files and pub.OLD_SITE_NOTE not in out["note"]
    assert not store.preview()["has_changes"]
    with publisher(fake) as gh:
        pub.rollback(store, gh)
    files = fake.files()
    assert json.loads(files["assets/catalog/site.json"])["palette"] == "violet"
    assert f"assets/catalog/look/{banner}" not in files
    assert store.preview()["has_changes"]            # the local look is still «ruby»


def test_publish_warns_when_the_site_code_is_older(store, site_folder):
    store.seed_from_folder(site_folder)
    fake = FakeGitHub(files={"index.html": b"<html>", "assets/site.js": b"var old = 1;"})
    with publisher(fake) as gh:
        out = pub.publish(store, gh, generator="test")
    assert pub.OLD_SITE_NOTE in out["note"]


def test_read_from_site_brings_its_look(store, site_folder, tmp_path, admin_qapp):
    store.seed_from_folder(site_folder)
    logo, _ = store.add_look_photo("logo", image_bytes(300, 300))
    store.update_look(lambda look: (look.update(palette="ocean", logo=logo),
                                    look["store"].update(address="آدرس تازه")))
    store.set_brand_order(["samsung", "apple"])
    fake = FakeGitHub(files={"assets/products.js": b"x"})
    with publisher(fake) as gh:
        pub.publish(store, gh, generator="test")
    other = SiteStore(tmp_path / "other" / "site")      # another computer
    with publisher(fake) as gh:
        pub.seed_from_github(other, gh)
    look = other.look()
    assert look["palette"] == "ocean" and look["logo"] == logo
    assert look["store"]["address"] == "آدرس تازه"
    assert other.look_photo_path(logo).is_file()
    assert [b["key"] for b in other.brands()] == ["samsung", "apple"]
    assert not other.preview()["has_changes"]
    # an arranged look here is never replaced by a later «خواندن از سایت»
    other.update_look(lambda look: look.update(palette="sunset"))
    with publisher(fake) as gh:
        pub.seed_from_github(other, gh)
    assert other.look()["palette"] == "sunset"


def test_backup_and_restore_keep_the_look(store, site_folder, tmp_path):
    store.seed_from_folder(site_folder)
    logo, _ = store.add_look_photo("logo", image_bytes(300, 300))
    store.update_look(lambda look: look.update(palette="graphite", logo=logo))
    zip_path = tmp_path / "backup.zip"
    store.backup(zip_path)
    store.update_look(lambda look: look.update(palette="violet", logo=""))
    store.look_photo_path(logo).unlink()
    store.restore(zip_path)
    assert store.look()["palette"] == "graphite" and store.look_photo_path(logo).is_file()


# ---- the browser preview ---------------------------------------------------------------------
def test_preview_folder_and_local_server(store, site_folder, tmp_path):
    store.seed_from_folder(site_folder)
    (site_folder / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (site_folder / "assets" / "site.js").write_text("/* asr-site-look */", encoding="utf-8")
    (site_folder / "assets" / "catalog").mkdir()
    (site_folder / "assets" / "catalog" / "catalog.json").write_text("old", encoding="utf-8")
    store.update_look(lambda look: look.update(palette="sunset"))
    out = pv.build(store, pv.base_from_folder(site_folder), tmp_path / "preview")
    assert out["look_supported"]
    root = out["dir"]
    assert json.loads((root / "assets/catalog/site.json").read_text("utf-8"))["palette"] == "sunset"
    assert json.loads((root / "assets/catalog/catalog.json").read_text("utf-8"))["format"]
    assert not (root / "assets" / "products").exists()      # product photos come from here
    url = pv.PreviewServer.url(root)
    try:
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url + "assets/catalog/site.json", timeout=5) as answer:
            assert json.loads(answer.read())["palette"] == "sunset"
    finally:
        pv.PreviewServer.stop()


def test_preview_base_from_github_reads_only_changed_files(store, tmp_path):
    fake = FakeGitHub(files={"index.html": b"<html>", "assets/site.js": b"/* asr-site-look */",
                             "assets/products/x.jpg": b"photo", "assets/fonts/a.woff2": b"f",
                             "assets/catalog/catalog.json": b"{}"})
    cache = tmp_path / "base"
    with publisher(fake) as gh:
        pv.base_from_github(gh, cache)
    assert (cache / "index.html").is_file() and (cache / "assets/fonts/a.woff2").is_file()
    assert not (cache / "assets/products/x.jpg").exists()
    assert not (cache / "assets/catalog/catalog.json").exists()
    before = len(fake.requests)
    with publisher(fake) as gh:
        pv.base_from_github(gh, cache)
    reads = [r for r in fake.requests[before:] if "/contents/" in r[1]]
    assert reads == []
