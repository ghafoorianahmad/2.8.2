"""v2.11.0 «سایت»: local site data on this computer, photos in the site standard,
preview, backup / restore, «انتشار در سایت» to a FAKE GitHub (never the real
repository), 48-hour rollback, the token (DPAPI), the accessory PDF reader."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from app.site import accessory_pdf, catalog as cat, photos as ph  # noqa: E402
from app.site import publish as pub  # noqa: E402
from app.site.github import GitHubError, GitHubPublisher, blob_sha  # noqa: E402
from app.site.store import SiteDataError, SiteStore  # noqa: E402

from .fake_github import TOKEN, FakeGitHub  # noqa: E402
from .placeholder_pdf import PLACEHOLDER_PDF_PAGES, _pdf  # noqa: E402

PRODUCTS_JS = """const CATALOG = {
  apple: {
    name: "Apple", mark: "apple", tagline: "چند سال راحت استفاده کن.",
    items: [
      { id: "iphone-17", name: "iPhone 17", tier: "پرچمدار", priceState: "استعلام قیمت", releaseYear: 2025,
        colors: ["مشکی", "یاسی"], aliases: ["آیفون ۱۷"],
        spec: { "نمایشگر": "6.3 اینچ OLED، 120Hz", 'وزن': "177 گرم" } }
    ]
  },
  samsung: {
    name: "Samsung", mark: "samsung", tagline: "",
    items: [
      { id: "galaxy-a56", name: "Galaxy A56", tier: "میان‌رده", priceState: "استعلام قیمت", releaseYear: 2025,
        colors: ["گرافیتی آوسام"], aliases: [], spec: { "باتری": "5000 میلی‌آمپر ساعت" } }
    ]
  }
};"""
SITE_JS = """(function () {
  var SWATCH = { 'مشکی': '#1b1d22', 'یاسی': '#c4b5f0' };
  var PRODUCTS_WITH_COLOR_PHOTOS = { 'iphone-17': ['black', 'lavender'] };
})();"""


def image_bytes(width: int, height: int, fmt: str = "PNG", color: str = "#cc2222") -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, fmt)
    return bytes(raw.data())


@pytest.fixture
def site_folder(tmp_path, admin_qapp):
    root = tmp_path / "site"
    (root / "assets" / "products").mkdir(parents=True)
    (root / "assets" / "products.js").write_text(PRODUCTS_JS, encoding="utf-8")
    (root / "assets" / "site.js").write_text(SITE_JS, encoding="utf-8")
    for name in ("iphone-17.jpg", "iphone-17-black.jpg", "iphone-17-lavender.jpg"):
        (root / "assets" / "products" / name).write_bytes(image_bytes(1280, 1024, "JPG"))
    return root


@pytest.fixture
def store(tmp_path, admin_qapp):
    return SiteStore(tmp_path / "data" / "site")


# ---- reading the site's files ------------------------------------------------------------
def test_js_reader_reads_data_and_refuses_code():
    value, _ = cat.read_js_value("{ a: 1, 'b': [\"x\", 2.5, true, null], c: { d: 'e\\u0041' }, }")
    assert value == {"a": 1, "b": ["x", 2.5, True, None], "c": {"d": "eA"}}
    for bad in ("{ a: alert(1) }", "{ a: 1 + 2 }", "{ a: `x` }", "[1, 2"):
        with pytest.raises(cat.JsLiteralError):
            cat.read_js_value(bad)


def test_parse_site_files():
    parsed = cat.parse_site_files(PRODUCTS_JS, SITE_JS)
    assert [b["key"] for b in parsed["brands"]] == ["apple", "samsung"]
    i17 = parsed["items"][0]
    assert i17["code"] == "iphone-17" and i17["brand"] == "apple" and i17["image"] == "iphone-17.jpg"
    assert i17["colors"][1] == {"name": "یاسی", "image": "iphone-17-lavender.jpg", "hex": "#c4b5f0"}
    assert parsed["items"][1]["colors"][0]["image"] == ""


def test_clean_item_never_keeps_a_price():
    item = cat.clean_item({"code": "x-1", "name": "X", "price_state": "۵۲ میلیون",
                           "colors": [{"name": "سبز", "image": "A B.jpg"}], "image": "../x.jpg"})
    assert item["price_state"] == "استعلام قیمت" and item["image"] == ""
    assert item["colors"] == [{"name": "سبز", "image": "", "hex": ""}]


# ---- photos ------------------------------------------------------------------------------
def test_photo_is_made_1280_by_1024_on_the_light_background(admin_qapp):
    jpeg, notes = ph.normalize(image_bytes(300, 200))
    image = QImage.fromData(jpeg)
    assert (image.width(), image.height()) == (1280, 1024) and jpeg[:2] == b"\xff\xd8"
    corner = QColor(image.pixel(3, 3))
    assert abs(corner.red() - 0xFB) < 6 and abs(corner.blue() - 0xFF) < 6
    assert notes and "کوچک" in notes[0]
    standard = image_bytes(1280, 1024, "JPG")
    assert ph.normalize(standard)[0] == standard            # kept byte for byte
    with pytest.raises(ph.PhotoError):
        ph.normalize(b"not an image")


# ---- the local data ----------------------------------------------------------------------
def test_seed_then_no_change_in_the_preview(store, site_folder):
    out = store.seed_from_folder(site_folder)
    # galaxy-a56.jpg is not in the folder: the site draws that phone
    assert out == {"models": 2, "added": 2, "photos": 3, "missing_photos": 1}
    preview = store.preview()
    assert not preview["has_changes"] and preview["problems"] == []
    assert preview["lines"] == ["نسبت به آنچه اکنون در سایت است تغییری نیست."]
    assert store.seed_from_folder(site_folder)["added"] == 0      # items kept


def test_hide_add_and_edit_show_in_the_preview(store, site_folder):
    store.seed_from_folder(site_folder)
    store.set_hidden("galaxy-a56", True)
    store.upsert({"code": "galaxy-a57", "category": "phone", "brand": "samsung",
                  "name": "Galaxy A57", "colors": [{"name": "سرمه‌ای"}], "specs": [["باتری", "5000"]]})
    i17 = store.get("iphone-17")
    i17["specs"].append(["پردازنده", "Apple A19"])
    store.upsert(i17)
    lines = store.preview()["lines"]
    assert "➕ گوشی تازه در سایت: Galaxy A57" in lines
    assert "➖ از سایت برداشته می‌شود: Galaxy A56" in lines
    assert "✎ iPhone 17: مشخصات" in lines
    catalog, files = store.build()
    assert {i["code"] for i in catalog["items"]} == {"iphone-17", "galaxy-a57"}
    assert "assets/catalog/images/iphone-17.jpg" in files


def test_upsert_explains_what_is_missing(store):
    with pytest.raises(SiteDataError) as err:
        store.upsert({"code": "Bad Code", "category": "phone", "name": ""})
    assert "نام" in str(err.value) and "کد مدل" in str(err.value) and "رنگ" in str(err.value)
    store.upsert({"code": "anker-737", "category": "accessory", "name": "Anker 737",
                  "group": "powerbank", "description": "۲۴ هزار میلی‌آمپر"})
    assert store.get("anker-737")["group"] == "powerbank"      # an accessory needs no colour


def test_backup_and_restore(store, site_folder, tmp_path):
    store.seed_from_folder(site_folder)
    target = tmp_path / "backup.zip"
    assert store.backup(target) == 3
    store.set_hidden("iphone-17", True)
    out = store.restore(target)
    assert out == {"items": 2, "photos": 3}
    assert store.get("iphone-17")["hidden"] is False
    assert any(p.name.startswith("site_before_restore_") for p in store.root.parent.iterdir())
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK\x05\x06" + bytes(18))
    with pytest.raises(SiteDataError):
        store.restore(bad)


# ---- publishing (fake GitHub only) -----------------------------------------------------
def publisher(fake: FakeGitHub, token: str = TOKEN) -> GitHubPublisher:
    return GitHubPublisher(token, fake.repo, fake.branch, transport=fake.transport())


def test_publish_commits_catalog_and_photos_then_only_changes(store, site_folder, monkeypatch):
    monkeypatch.setattr(pub, "miniapp_files", dict)     # v2.18.0: test_v2180_miniapp covers it
    store.seed_from_folder(site_folder)
    fake = FakeGitHub(files={"index.html": b"<html>"})
    with publisher(fake) as gh:
        assert gh.test_connection()["can_write"]
        out = pub.publish(store, gh, generator="test")
    files = fake.files()
    catalog = json.loads(files["assets/catalog/catalog.json"])
    assert catalog["format"] == "asr-catalog" and len(catalog["items"]) == 2
    assert "assets/catalog/images/iphone-17-black.jpg" in files and files["index.html"] == b"<html>"
    # v2.12.0: + assets/catalog/site.json (the look) in the same commit
    assert out["written"] == 5 and out["deploy_started"] and fake.dispatches == ["main"]
    assert json.loads(files["assets/catalog/site.json"])["format"] == "asr-site-look"
    assert fake.messages()[0] == pub.COMMIT_MESSAGE
    text = files["assets/catalog/catalog.json"].decode("utf-8")
    assert TOKEN not in text and "kala_code" not in text
    # nothing changed: nothing is sent, no commit
    commits = len(fake.commits)
    with publisher(fake) as gh:
        again = pub.publish(store, gh, generator="test")
    assert again["commit"] is None and len(fake.commits) == commits
    # one photo changed: that photo + catalog.json (its photo list has the hash)
    store.add_photo("iphone-17.jpg", image_bytes(500, 400))
    with publisher(fake) as gh:
        third = pub.publish(store, gh, generator="test")
    assert third["written"] == 2


def test_rollback_within_48_hours(store, site_folder, tmp_path):
    now = [datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)]
    store = SiteStore(tmp_path / "data2" / "site", clock=lambda: now[0])
    store.seed_from_folder(site_folder)
    fake = FakeGitHub()
    with publisher(fake) as gh:
        pub.publish(store, gh, generator="test")
        store.set_hidden("galaxy-a56", True)
        pub.publish(store, gh, generator="test")
    assert len(json.loads(fake.files()["assets/catalog/catalog.json"])["items"]) == 1
    with publisher(fake) as gh:
        pub.rollback(store, gh)
    assert len(json.loads(fake.files()["assets/catalog/catalog.json"])["items"]) == 2
    assert fake.messages()[0] == pub.ROLLBACK_MESSAGE
    # the first publish can still be undone (removes the files it added) ...
    assert store.last_rollback() is not None
    now[0] += timedelta(hours=49)
    # ... but not after 48 hours: the record is deleted
    assert store.last_rollback() is None
    assert not list((store.root / "history").glob("*.json"))
    with publisher(fake) as gh, pytest.raises(SiteDataError):
        pub.rollback(store, gh)


def test_publish_errors_are_persian_and_never_show_the_token(store, site_folder):
    store.seed_from_folder(site_folder)
    with publisher(FakeGitHub(), token="github_pat_WRONG") as gh, \
            pytest.raises(GitHubError) as err:
        gh.test_connection()
    assert "توکن" in str(err.value) and "WRONG" not in str(err.value)
    with publisher(FakeGitHub(can_write=False)) as gh, pytest.raises(GitHubError) as err:
        gh.test_connection()
    assert "Read and write" in str(err.value)
    fake = FakeGitHub()
    fake.race = True
    with publisher(fake) as gh, pytest.raises(GitHubError) as err:
        pub.publish(store, gh, generator="test")
    assert "دوباره" in str(err.value)
    assert store.last_rollback() is None                  # nothing recorded on failure


def test_publish_without_actions_permission_explains(store, site_folder):
    store.seed_from_folder(site_folder)
    fake = FakeGitHub(can_dispatch=False)
    with publisher(fake) as gh:
        out = pub.publish(store, gh, generator="test")
    assert out["commit"] and not out["deploy_started"] and "Actions" in out["note"]


def test_blob_sha_matches_git():
    assert blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_token_is_stored_with_dpapi(tmp_path):
    from app.site import token as tk
    from app.store import Store

    local = Store(tmp_path / "s.db")
    tk.save(local, "  github_pat_ABC123  ")
    raw = local.get_setting(tk.SETTING)
    assert raw.startswith("dpapi:") and "ABC123" not in raw
    assert tk.load(local) == "github_pat_ABC123" and tk.has_token(local)
    tk.forget(local)
    assert not tk.has_token(local)
    with pytest.raises(tk.TokenError):
        tk.save(local, "two words")
    local.close()


# ---- accessory PDFs (optional helper, on this computer) -----------------------------------
def test_read_placeholder_accessory_pdf():
    items = accessory_pdf.read_pdf(_pdf(PLACEHOLDER_PDF_PAGES), taken_codes={"anker-737-power-bank"})
    by_name = {i.name: i for i in items}
    anker = by_name["Anker 737 Power Bank"]
    assert anker.specs == [["Capacity", "24000 mAh"], ["Output", "140W"]]
    assert anker.group == "powerbank" and anker.code == "anker-737-power-bank-2"
    assert len(anker.images) == 1 and anker.images[0][:2] == b"\xff\xd8"
    assert by_name["Baseus Bowie Earbuds"].group == "headphones"
    assert by_name["Clear Case iPhone 17"].group == "case"
    item = accessory_pdf.item_for(anker, "anker-737-power-bank-2.jpg")
    assert cat.clean_item(item)["category"] == "accessory"
    with pytest.raises(ValueError):
        accessory_pdf.read_pdf(b"hello")
