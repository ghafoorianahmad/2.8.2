"""v2.10.0 «خروجی کاتالوگ برای سایت»: preview, export (zip / server folder),
schedule, the site data of one model, seeding from a copy of the site and the
accessory PDF dialog."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.statuses import ROLE_OPERATOR  # noqa: E402
from app.ui import site_export_dialog as sx  # noqa: E402
from app.ui.pages.catalog_models import CatalogModelsPage  # noqa: E402

from .test_ui import _render_page, make_context_with_role, ui_context  # noqa: E402,F401

NL = chr(10)
JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"fake"


# ---- pure helpers -------------------------------------------------------------------
def test_colors_and_specs_round_trip():
    colors = [{"name": "مشکی", "image": "iphone-17-black.jpg", "hex": "#1b1d22"},
              {"name": "یاسی", "image": "", "hex": ""}]
    text = sx.colors_to_text(colors)
    assert text == "مشکی | iphone-17-black.jpg | #1b1d22" + NL + "یاسی"
    assert sx.parse_colors_text(text) == colors
    assert sx.parse_colors_text("  | x.jpg" + NL + "سبز | X.JPG") == [
        {"name": "سبز", "image": "x.jpg", "hex": ""}]
    specs = [["نمایشگر", "6.3 اینچ OLED، 120Hz"], ["وزن", "177 گرم"]]
    assert sx.parse_specs_text(sx.specs_to_text(specs)) == specs
    assert sx.parse_specs_text("بدون دونقطه" + NL + "باتری： 5000") == [["باتری", "5000"]]


def test_change_lines_in_persian():
    preview = {"counts": {"phones": 66, "accessories": 2, "images": 296, "skipped": 1},
               "changes": {"first": False, "added": [{"code": "a", "name": "Galaxy A57"}],
                           "changed": [], "removed": [{"code": "b", "name": "iPhone 13"}],
                           "images_new": ["images/a.jpg"], "images_changed": []},
               "has_changes": True}
    lines = sx.change_lines(preview)
    assert lines[0].startswith("در خروجی: ۶۶ گوشی، ۲ لوازم جانبی، ۲۹۶ عکس")
    assert any(line.startswith("تازه (۱): Galaxy A57") for line in lines)
    assert any(line.startswith("حذف از سایت (۱): iPhone 13") for line in lines)
    assert "نسبت به خروجی قبلی تغییری نیست." in sx.change_lines(
        {"counts": {}, "changes": {}, "has_changes": False})
    assert sx.last_export_fa(None) == "هنوز خروجی‌ای ساخته نشده است."
    assert "ناموفق" in sx.last_export_fa({"ok": False, "error": "x", "at": "2026-10-27T08:00:00"})


def test_site_folder_sources(tmp_path):
    with pytest.raises(ValueError):
        sx.site_folder_sources(tmp_path)
    (tmp_path / "assets" / "products").mkdir(parents=True)
    (tmp_path / "assets" / "products.js").write_text("const CATALOG = {};", encoding="utf-8")
    (tmp_path / "assets" / "products" / "a.jpg").write_bytes(JPEG)
    products, site, photos = sx.site_folder_sources(tmp_path)
    assert products.startswith("const CATALOG") and site == ""
    assert sx.photos_to_send(["a.jpg", "missing.jpg"], photos) == [("a.jpg", photos / "a.jpg")]


# ---- dialogs ----------------------------------------------------------------------------
def test_export_dialog_preview_and_zip(ui_context, fake_api, tmp_path, monkeypatch):
    model = fake_api.add_catalog_model("iphone-17", "iPhone 17", "Apple")
    fake_api.site_data[model["id"]] = {"colors": [{"name": "مشکی"}]}
    dialog = sx.SiteExportDialog(ui_context)
    assert "آمادهٔ خروجی" in dialog.summary.text()
    assert "۱ گوشی" in dialog.changes.toPlainText()
    assert "iPhone 17" in dialog.warnings.toPlainText()            # no photo
    assert dialog.export_button.isEnabled()
    target = tmp_path / "out.zip"
    monkeypatch.setattr(sx.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(sx.widgets, "success", lambda *a, **k: None)
    dialog._export_zip()
    assert target.read_bytes()[:2] == b"PK" and fake_api.site_exports == ["zip"]
    assert "آخرین خروجی" in dialog.last_label.text()


def test_export_dialog_without_site_data_cannot_export(ui_context, fake_api):
    fake_api.add_catalog_model("iphone-17", "iPhone 17", "Apple")
    dialog = sx.SiteExportDialog(ui_context)
    assert not dialog.export_button.isEnabled()
    assert "هیچ گوشی" in dialog.summary.text()


def test_schedule_and_folder(ui_context, fake_api, monkeypatch):
    model = fake_api.add_catalog_model("iphone-17", "iPhone 17", "Apple")
    fake_api.site_data[model["id"]] = {"colors": [{"name": "مشکی"}]}
    monkeypatch.setattr(sx.widgets, "success", lambda *a, **k: None)
    dialog = sx.SiteExportDialog(ui_context)
    dialog.schedule_check.setChecked(True)
    dialog.hour_input.setValue(7)
    dialog.folder_input.setText("D:\\SiteCatalog")
    dialog._save_schedule()
    assert fake_api.site_schedule == {"enabled": True, "hour": 7, "folder": "D:\\SiteCatalog"}
    dialog._export_folder()
    assert fake_api.site_exports == ["D:\\SiteCatalog"]
    dialog.folder_input.setText("relative")
    dialog._export_folder()
    assert "نشانی کامل" in dialog.error_label.text()


def test_seed_from_site_folder_uploads_needed_photos(ui_context, fake_api, tmp_path, monkeypatch):
    fake_api.site_models = [{"slug": "iphone-17", "name": "iPhone 17", "brand": "Apple"}]
    fake_api.site_seed_needs = ["iphone-17.jpg", "iphone-17-black.jpg", "gone.jpg"]
    (tmp_path / "assets" / "products").mkdir(parents=True)
    (tmp_path / "assets" / "products.js").write_text("const CATALOG = {};", encoding="utf-8")
    (tmp_path / "assets" / "site.js").write_text("var SWATCH = {};", encoding="utf-8")
    for name in ("iphone-17.jpg", "iphone-17-black.jpg"):
        (tmp_path / "assets" / "products" / name).write_bytes(JPEG)
    messages = []
    monkeypatch.setattr(sx.widgets, "success", lambda _p, _t, text: messages.append(text))
    dialog = sx.SiteExportDialog(ui_context)
    dialog.seed_from(str(tmp_path))
    assert fake_api.site_seeds[0]["site_js"] == "var SWATCH = {};"
    assert set(fake_api.site_images) == {"iphone-17.jpg", "iphone-17-black.jpg"}
    assert "۲ عکس فرستاده شد" in messages[0] and "۱ عکس فرستاده نشد" in messages[0]


def test_operator_sees_but_cannot_export(ui_context, fake_api):
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    dialog = sx.SiteExportDialog(context, load=False)
    assert not dialog.export_button.isEnabled() and not dialog.seed_button.isEnabled()
    assert not dialog.save_schedule_button.isEnabled()


def test_site_model_dialog_edits_and_saves(ui_context, fake_api):
    model = fake_api.add_catalog_model("iphone-17", "iPhone 17", "Apple")
    fake_api.site_images["iphone-17.jpg"] = JPEG
    fake_api.site_data[model["id"]] = {"published": True, "tier": "پرچمدار", "release_year": 2025,
                                      "image": "iphone-17.jpg",
                                      "colors": [{"name": "مشکی", "image": "", "hex": ""}],
                                      "specs": [["وزن", "177 گرم"]], "group": "",
                                      "brand_key": "apple", "brand_name": ""}
    dialog = sx.SiteModelDialog(ui_context, model["id"])
    assert dialog.card_image.currentText() == "iphone-17.jpg"
    assert dialog.specs.toPlainText() == "وزن: 177 گرم"
    dialog.colors.setPlainText("مشکی" + NL + "یاسی | iphone-17-lavender.jpg")
    dialog.published.setChecked(False)
    dialog._save()
    saved = fake_api.site_data[model["id"]]
    assert saved["published"] is False and saved["brand_key"] == "apple"
    assert saved["colors"][1] == {"name": "یاسی", "image": "iphone-17-lavender.jpg", "hex": ""}


def test_accessory_pdf_dialog_adds_checked(ui_context, fake_api, monkeypatch):
    fake_api.accessory_items = [
        {"code": "anker-737", "name": "Anker 737 Power Bank", "group": "powerbank", "page": 1,
         "specs": [["Capacity", "24000 mAh"]], "image_count": 1},
        {"code": "clear-case", "name": "Clear Case", "group": "case", "page": 2, "specs": [],
         "image_count": 0}]
    monkeypatch.setattr(sx.widgets, "success", lambda *a, **k: None)
    dialog = sx.AccessoryPdfDialog(ui_context, b"%PDF-1.4 placeholder")
    assert dialog.list.count() == 2 and "پاوربانک" in dialog.list.item(0).text()
    dialog.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog._add()
    assert fake_api.accessory_adds == [["anker-737"]]


def test_page_has_the_site_buttons(admin_qapp, ui_context, fake_api):
    fake_api.add_catalog_model("iphone-17", "iPhone 17", "Apple")
    page = CatalogModelsPage(ui_context)
    _render_page(admin_qapp, page)
    assert page.site_export_button.text() == "خروجی کاتالوگ برای سایت…"
    assert page.site_data_button in page._detail_buttons
