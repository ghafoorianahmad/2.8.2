"""v2.10.0 «خروجی کاتالوگ برای سایت»: the site's catalogue from ShopSystem
(catalog.json + images/), seeded from the site's own files, previewed, exported
as a zip or into a server folder (daily schedule), and accessory PDFs."""
from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from app import accessory_pdf, site_export
from app.catalog_models import CatalogModelRepo

from .test_phase3 import staff

PRODUCTS_JS = """/* sample of the site's assets/products.js */
const CATALOG = {
  apple: {
    name: "Apple", mark: "apple", tagline: "چند سال راحت استفاده کن.",
    items: [
      { id: "iphone-17", name: "iPhone 17", tier: "پرچمدار", priceState: "استعلام قیمت", releaseYear: 2025,
        colors: ["مشکی", "یاسی"],
        aliases: ["آیفون ۱۷", "iphone17"],
        spec: { "نمایشگر": "6.3 اینچ OLED، 120Hz", "پردازنده": "Apple A19", 'وزن': "177 گرم" } },
      { id: "iphone-16e", name: "iPhone 16e", tier: "میان‌رده", priceState: "استعلام قیمت", releaseYear: 2025,
        colors: ["مشکی"], aliases: [], spec: { "پردازنده": "Apple A18" } }
    ]
  },
  samsung: {
    name: "Samsung", mark: "samsung", tagline: "",
    items: [
      { id: "galaxy-a56", name: "Galaxy A56", tier: "میان‌رده", priceState: "استعلام قیمت", releaseYear: 2025,
        colors: ["گرافیتی آوسام"], aliases: ["a56"], spec: { "باتری": "5000 میلی‌آمپر ساعت" } }
    ]
  }
};
function allProducts() { return []; }
"""

SITE_JS = """(function () {
  var SWATCH = {
    'مشکی': '#1b1d22', 'یاسی': '#c4b5f0',
    'گرافیتی آوسام': '#55585e'
  };
  var PRODUCTS_WITH_COLOR_PHOTOS = {
    'iphone-17': ['black', 'lavender'],
    'galaxy-a56': ['graphite']
  };
})();
"""


def jpeg(color=(200, 30, 30), size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def site_settings(settings, tmp_path):
    settings.site_images_dir = str(tmp_path / "site_images")
    return settings


@pytest.fixture
def boss(db):
    return staff(db, "super_admin", "boss")


def seed(client, headers, *, site_js=SITE_JS, overwrite=False) -> dict:
    r = client.post("/admin/site-catalog/seed", headers=headers,
                    json={"products_js": PRODUCTS_JS, "site_js": site_js, "overwrite": overwrite})
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, headers, name, data=None):
    return client.put(f"/admin/site-catalog/images/{name}", headers=headers,
                      json={"data_b64": base64.b64encode(data or jpeg()).decode()})


# ---- reading the site's files as data ------------------------------------------------------
def test_js_literal_reader_reads_data_and_refuses_code():
    value, _ = site_export.read_js_value("{ a: 1, 'b': [\"x\", 2.5, true, null], c: { d: 'e\\u0041' }, }")
    assert value == {"a": 1, "b": ["x", 2.5, True, None], "c": {"d": "eA"}}
    for bad in ("{ a: alert(1) }", "{ a: 1 + 2 }", "{ a: `x` }", "[1, 2"):
        with pytest.raises(site_export.JsLiteralError):
            site_export.read_js_value(bad)
    assert site_export.extract_assignment("var X = [1, /* c */ 2];", "X") == [1, 2]
    assert site_export.extract_assignment("var Y = 1;", "X") is None


def test_parse_site_files_builds_site_data():
    parsed = site_export.parse_site_files(PRODUCTS_JS, SITE_JS)
    assert [b["key"] for b in parsed["brands"]] == ["apple", "samsung"]
    by_slug = {m["slug"]: m for m in parsed["models"]}
    i17 = by_slug["iphone-17"]
    assert i17["brand"] == "Apple" and i17["kind"] == "phone"
    assert i17["site"]["image"] == "iphone-17.jpg"
    assert i17["site"]["colors"] == [
        {"name": "مشکی", "image": "iphone-17-black.jpg", "hex": "#1b1d22"},
        {"name": "یاسی", "image": "iphone-17-lavender.jpg", "hex": "#c4b5f0"}]
    assert i17["site"]["specs"][0] == ["نمایشگر", "6.3 اینچ OLED، 120Hz"]
    assert i17["site"]["release_year"] == 2025 and i17["site"]["brand_key"] == "apple"
    # a model without a colour photo map keeps only its card
    assert by_slug["iphone-16e"]["site"]["colors"][0]["image"] == ""
    with pytest.raises(site_export.JsLiteralError):
        site_export.parse_site_files("const OTHER = {};")


def test_clean_site_data_never_keeps_a_price():
    clean = site_export.clean_site_data({"price_state": "۵۲ میلیون", "image": "../x.jpg",
                                          "colors": [{"name": "سبز", "image": "A B.jpg", "hex": "red"}],
                                          "specs": [["k", "v"], ["only one"]], "group": "weapon",
                                          "release_year": 1990})
    assert clean["price_state"] == "استعلام قیمت"
    assert clean["image"] == "" and clean["colors"] == [{"name": "سبز", "image": "", "hex": ""}]
    assert clean["specs"] == [["k", "v"]] and clean["group"] == "" and clean["release_year"] is None


# ---- seed, photos, preview, export ---------------------------------------------------------
def test_seed_lists_the_photos_the_server_still_needs(client, db, site_settings, boss):
    out = seed(client, boss)
    assert out["models"] == 3 and out["added"] == 3 and out["filled"] == 3
    assert "iphone-17-black.jpg" in out["images_needed"] and "galaxy-a56.jpg" in out["images_needed"]
    model = CatalogModelRepo(db).get_by_slug("iphone-17")
    assert model["kind"] == "phone" and model["source"] == "site"
    # staff edits are kept on a second seed (unless overwrite)
    r = client.put(f"/admin/site-catalog/models/{model['id']}", headers=boss,
                   json={"tier": "پرفروش", "colors": [{"name": "مشکی"}], "specs": [["a", "b"]]})
    assert r.status_code == 200, r.text
    assert seed(client, boss)["kept"] == 3
    assert site_export.get_site_data(db, model["id"])["tier"] == "پرفروش"
    assert seed(client, boss, overwrite=True)["filled"] == 3
    assert site_export.get_site_data(db, model["id"])["tier"] == "پرچمدار"


def test_image_upload_is_checked(client, site_settings, boss):
    assert upload(client, boss, "iphone-17.jpg").status_code == 200
    assert upload(client, boss, "../evil.jpg").status_code in (404, 422)
    assert upload(client, boss, "Bad Name.jpg").status_code == 422
    assert upload(client, boss, "fake.jpg", b"not an image").status_code == 422
    png = io.BytesIO()
    Image.new("RGB", (40, 40)).save(png, "PNG")
    assert upload(client, boss, "wrong-type.jpg", png.getvalue()).status_code == 422
    assert upload(client, boss, "right-type.png", png.getvalue()).status_code == 200
    images = client.get("/admin/site-catalog/images", headers=boss).json()["images"]
    assert set(images) == {"iphone-17.jpg", "right-type.png"}


def test_operator_cannot_change_the_site(client, db, site_settings):
    mina = staff(db, "operator", "mina")
    assert client.post("/admin/site-catalog/export", headers=mina).status_code == 403
    assert upload(client, mina, "x.jpg").status_code == 403


def test_preview_and_zip_export(client, db, site_settings, boss):
    seed(client, boss)
    for name in ("iphone-17.jpg", "iphone-17-black.jpg", "iphone-17-lavender.jpg",
                 "galaxy-a56-graphite.jpg"):
        assert upload(client, boss, name).status_code == 200
    preview = client.get("/admin/site-catalog/preview", headers=boss).json()
    assert preview["counts"]["phones"] == 3 and preview["counts"]["images"] == 4
    assert preview["changes"]["first"] and len(preview["changes"]["added"]) == 3
    assert preview["problems"] == []
    codes = {(w["code"], w["slug"]) for w in preview["warnings"]}
    assert ("missing_image", "iphone-16e") in codes and ("missing_image", "galaxy-a56") in codes

    r = client.post("/admin/site-catalog/export", headers=boss)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(archive.namelist()) == ["catalog.json", "images/galaxy-a56-graphite.jpg",
                                          "images/iphone-17-black.jpg",
                                          "images/iphone-17-lavender.jpg", "images/iphone-17.jpg"]
    catalog = json.loads(archive.read("catalog.json"))
    assert catalog["format"] == "asr-catalog" and catalog["version"] == 1
    assert catalog["generator"].startswith("ShopSystem ")
    i17 = next(i for i in catalog["items"] if i["code"] == "iphone-17")
    assert i17["image"] == "images/iphone-17.jpg" and i17["brand"] == "apple"
    assert i17["colors"][1] == {"name": "یاسی", "image": "images/iphone-17-lavender.jpg",
                                "hex": "#c4b5f0"}
    # nothing private in the file
    text = archive.read("catalog.json").decode("utf-8")
    for secret in ("kala_code", "price_rial", "bot-key", "admin-key", "hesab5", "SQLEXPRESS"):
        assert secret not in text
    assert site_export.validate_catalog(catalog) == []
    # the next preview compares with this export
    after = client.get("/admin/site-catalog/preview", headers=boss).json()
    assert not after["has_changes"] and after["last"]["where"] == "zip"


def test_preview_shows_what_changed(client, db, site_settings, boss):
    seed(client, boss)
    assert client.post("/admin/site-catalog/export", headers=boss).status_code == 200
    a56 = CatalogModelRepo(db).get_by_slug("galaxy-a56")
    site = site_export.get_site_data(db, a56["id"])
    site["specs"].append(["وزن", "198 گرم"])
    client.put(f"/admin/site-catalog/models/{a56['id']}", headers=boss, json=site)
    i16e = CatalogModelRepo(db).get_by_slug("iphone-16e")
    client.put(f"/admin/site-catalog/models/{i16e['id']}", headers=boss,
               json={**site_export.get_site_data(db, i16e["id"]), "published": False})
    upload(client, boss, "galaxy-a56.jpg")
    change = client.get("/admin/site-catalog/preview", headers=boss).json()["changes"]
    assert [c["code"] for c in change["changed"]] == ["galaxy-a56"]   # spec + new card photo
    assert [c["code"] for c in change["removed"]] == ["iphone-16e"]    # unpublished
    assert change["images_new"] == ["images/galaxy-a56.jpg"] and not change["first"]


def test_accessory_needs_no_brand_page_but_a_phone_does(client, db, site_settings, boss):
    seed(client, boss)
    repo = CatalogModelRepo(db)
    repo.import_models([{"slug": "nothing-phone-3", "name": "Nothing Phone 3", "brand": "Nothing"}],
                       "t")
    model = repo.get_by_slug("nothing-phone-3")
    site_export.set_site_data(db, model["id"], {"colors": [{"name": "سفید"}], "specs": [["a", "b"]]},
                              "t")
    warnings = client.get("/admin/site-catalog/preview", headers=boss).json()["warnings"]
    assert any(w["code"] == "no_brand_page" and w["slug"] == "nothing-phone-3" for w in warnings)


def test_export_without_phones_is_refused(client, db, site_settings, boss):
    r = client.post("/admin/site-catalog/export", headers=boss)
    assert r.status_code == 422 and "هیچ گوشی" in r.json()["detail"]


# ---- folder export + schedule --------------------------------------------------------------
def test_folder_export_writes_photos_then_catalog(client, db, site_settings, boss, tmp_path):
    seed(client, boss)
    upload(client, boss, "iphone-17.jpg")
    target = tmp_path / "out"
    target.mkdir()
    (target / "keep-me.txt").write_text("x", encoding="utf-8")
    r = client.post("/admin/site-catalog/export-folder", headers=boss, json={"folder": str(target)})
    assert r.status_code == 200, r.text
    assert r.json()["images_written"] == 1
    assert (target / "images" / "iphone-17.jpg").is_file()
    assert json.loads((target / "catalog.json").read_text(encoding="utf-8"))["version"] == 1
    assert (target / "keep-me.txt").is_file()                  # nothing else touched
    again = client.post("/admin/site-catalog/export-folder", headers=boss,
                        json={"folder": str(target)}).json()
    assert again["images_written"] == 0 and again["images_unchanged"] == 1
    assert client.post("/admin/site-catalog/export-folder", headers=boss,
                       json={"folder": str(tmp_path / "missing")}).status_code == 422
    root = Path(str(tmp_path)).anchor
    assert client.post("/admin/site-catalog/export-folder", headers=boss,
                       json={"folder": root}).status_code == 422
    mina = staff(db, "operator", "mina")
    assert client.post("/admin/site-catalog/export-folder", headers=mina,
                       json={"folder": str(target)}).status_code == 403


def test_daily_schedule_exports_once_and_only_changes(client, db, site_settings, boss, tmp_path):
    seed(client, boss)
    target = tmp_path / "daily"
    target.mkdir()
    r = client.put("/admin/site-catalog/schedule", headers=boss,
                   json={"enabled": True, "hour": 6, "folder": str(target)})
    assert r.status_code == 200, r.text
    assert client.put("/admin/site-catalog/schedule", headers=boss,
                      json={"enabled": True, "hour": 6,
                            "folder": str(tmp_path / "nope")}).status_code == 422
    early = datetime(2026, 10, 27, 5, 0)
    assert site_export.run_scheduled(db, site_settings, early) is None
    first = site_export.run_scheduled(db, site_settings, datetime(2026, 10, 27, 6, 5))
    assert first["ok"] and first["where"] == "folder" and (target / "catalog.json").is_file()
    assert site_export.run_scheduled(db, site_settings, datetime(2026, 10, 27, 9, 0)) is None
    # next day, nothing changed: no rewrite
    (target / "catalog.json").unlink()
    nothing = site_export.run_scheduled(db, site_settings, datetime(2026, 10, 28, 6, 5))
    assert nothing == {"ok": True, "unchanged": True}
    assert not (target / "catalog.json").exists()


# ---- accessory PDFs ------------------------------------------------------------------------
def _pdf(pages: list[list[tuple]]) -> bytes:
    """A small PDF: per page ("text", y, str) lines and ("image", x, y, w, h, jpeg)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objects) + 1 + 0
    objects.append(b"")          # placeholder for the page tree
    kids = []
    for page in pages:
        content, xobjects = [], []
        for part in page:
            if part[0] == "text":
                _kind, y, text = part
                safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                content.append(f"BT /F1 12 Tf 50 {y} Td ({safe}) Tj ET")
            else:
                _kind, x, y, w, hgt, data = part
                image = Image.open(io.BytesIO(data))
                ref = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                          b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                          b"/Length %d >>\nstream\n" % (image.width, image.height, len(data))
                          + data + b"\nendstream")
                name = f"Im{len(xobjects) + 1}"
                xobjects.append(f"/{name} {ref} 0 R")
                content.append(f"q {w} 0 0 {hgt} {x} {y} cm /{name} Do Q")
        stream = "\n".join(content).encode("latin-1")
        contents = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        resources = f"<< /Font << /F1 {font} 0 R >> /XObject << {' '.join(xobjects)} >> >>"
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                        f"/Resources {resources} /Contents {contents} 0 R >>".encode()))
    objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                             f"/Count {len(kids)} >>").encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objects) + 1, catalog, xref))
    return out.getvalue()


PLACEHOLDER_PDF_PAGES = [
    [("text", 760, "Accessories 2026"),          # a header is an item without specs
     ("text", 720, "Anker 737 Power Bank"),
     ("text", 700, "Capacity: 24000 mAh"),
     ("text", 684, "Output: 140W"),
     ("image", 50, 520, 200, 150, jpeg((20, 20, 200), (200, 150))),
     ("text", 480, "Baseus Bowie Earbuds"),
     ("text", 460, "Bluetooth: 5.3"),
     ("image", 50, 300, 160, 140, jpeg((20, 200, 20), (160, 140))),
     ("image", 400, 760, 20, 20, jpeg((0, 0, 0), (20, 20))),       # a logo: ignored
     ("text", 40, "Page 1")],
    [("text", 740, "Clear Case iPhone 17"),
     ("text", 720, "Material: TPU")],
]


def test_read_placeholder_accessory_pdf():
    items = accessory_pdf.read_pdf(_pdf(PLACEHOLDER_PDF_PAGES), taken_codes={"anker-737-power-bank"})
    by_name = {i.name: i for i in items}
    anker = by_name["Anker 737 Power Bank"]
    assert anker.specs == [["Capacity", "24000 mAh"], ["Output", "140W"]]
    assert anker.group == "powerbank" and anker.brand_name == "Anker"
    assert anker.code == "anker-737-power-bank-2"              # the taken code is not reused
    assert len(anker.images) == 1 and anker.images[0][:2] == b"\xff\xd8"
    buds = by_name["Baseus Bowie Earbuds"]
    assert buds.group == "headphones" and len(buds.images) == 1
    case = by_name["Clear Case iPhone 17"]
    assert case.group == "case" and case.page == 2 and case.specs == [["Material", "TPU"]]
    assert "Page 1" not in by_name
    with pytest.raises(ValueError):
        accessory_pdf.read_pdf(b"hello")


def test_accessory_pdf_endpoint_reads_then_adds(client, db, site_settings, boss):
    data = base64.b64encode(_pdf(PLACEHOLDER_PDF_PAGES)).decode()
    shown = client.post("/admin/site-catalog/accessory-pdf", headers=boss,
                        json={"data_b64": data}).json()
    codes = {i["name"]: i["code"] for i in shown["items"]}
    assert "result" not in shown and CatalogModelRepo(db).get_by_slug(codes["Anker 737 Power Bank"]) is None
    r = client.post("/admin/site-catalog/accessory-pdf", headers=boss,
                    json={"data_b64": data, "codes": [codes["Anker 737 Power Bank"]]})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == {"added": 1, "updated": 0, "images": 1}
    model = CatalogModelRepo(db).get_by_slug(codes["Anker 737 Power Bank"])
    assert model["kind"] == "accessory" and model["source"] == "pdf"
    site = site_export.get_site_data(db, model["id"])
    assert site["group"] == "powerbank" and site["image"] == f"{model['slug']}.jpg"
    assert os.path.isfile(Path(site_settings.site_images_dir) / site["image"])
    assert client.post("/admin/site-catalog/accessory-pdf", headers=boss,
                       json={"data_b64": base64.b64encode(b"%PDF-broken").decode()}).status_code == 422


# ---- the real site (optional: SITE_REPO_DIR = a clone of the site) --------------------------
@pytest.mark.skipif(not os.environ.get("SITE_REPO_DIR"), reason="SITE_REPO_DIR not set")
def test_real_site_files_parse_completely():
    folder = Path(os.environ["SITE_REPO_DIR"])
    parsed = site_export.parse_site_files(
        (folder / "assets" / "products.js").read_text(encoding="utf-8"),
        (folder / "assets" / "site.js").read_text(encoding="utf-8"))
    assert len(parsed["models"]) == 66
    files = {p.name for p in (folder / "assets" / "products").iterdir()}
    refs = {n for m in parsed["models"] for n in site_export._image_refs(m["site"])}
    assert refs <= files
    assert all(m["site"]["colors"] and m["site"]["specs"] for m in parsed["models"])
