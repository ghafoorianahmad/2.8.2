"""v2.12.0 «سایت» › «ظاهر و چیدمان»: arranging, featured phones, colour preset,
logo, banner, sections, store info, the browser preview, and publish + roll back
to a FAKE GitHub (never the real repository)."""
from __future__ import annotations

import json
import urllib.request

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.site import look as lk  # noqa: E402
from app.site import preview as pv  # noqa: E402
from app.site import token as tk  # noqa: E402
from app.ui import site_look as sl  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.pages import site as site_page  # noqa: E402
from app.ui.pages.site import SitePage  # noqa: E402

from .fake_github import TOKEN, FakeGitHub  # noqa: E402
from .test_ui import _render_page, ui_context  # noqa: E402,F401
from .test_v2110_site import image_bytes, site_folder  # noqa: E402,F401


@pytest.fixture
def page(admin_qapp, ui_context, site_folder, monkeypatch):
    monkeypatch.setattr(widgets, "success", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "info", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    errors = []
    monkeypatch.setattr(widgets, "error", lambda _p, _t, message, *a, **k: errors.append(message))
    page = SitePage(ui_context)
    page.errors = errors
    page.store.seed_from_folder(site_folder)
    _render_page(admin_qapp, page)
    page.look_tab.fill()
    return page


def settle(app) -> None:
    for _ in range(5):
        app.processEvents()


def test_the_tab_is_there_between_accessories_and_publish(page):
    titles = [page.tabs.tabText(n) for n in range(page.tabs.count())]
    assert titles == ["گوشی‌ها", "لوازم جانبی", "ظاهر و چیدمان", "انتشار و پشتیبان"]
    look = page.look_tab
    assert [look.tabs.tabText(n) for n in range(look.tabs.count())] == [
        "چیدمان کالاها", "تازه‌ترین گوشی‌ها", "رنگ و لوگو", "بنر صفحهٔ اصلی",
        "بخش‌های صفحهٔ اصلی", "اطلاعات فروشگاه"]
    assert look.store_inputs["phone"].text() == "09155000432"
    assert look.hero_inputs["title"].text() == lk.DEFAULT_LOOK["hero"]["title"]


def test_arrange_brands_and_phones(page, admin_qapp):
    look = page.look_tab
    assert look.brand_order.keys() == ["apple", "samsung"]
    look.brand_order.list.setCurrentRow(1)
    look.brand_order.step(-1)
    assert [b["key"] for b in page.store.brands()] == ["samsung", "apple"]
    page.store.upsert({"code": "galaxy-s26", "category": "phone", "brand": "samsung",
                       "name": "Galaxy S26", "release_year": 2026, "colors": [{"name": "سیاه"}]})
    look.fill_lists()
    look.phone_brand.setCurrentIndex(look.phone_brand.findData("samsung"))
    assert look.phone_order.keys() == ["galaxy-a56", "galaxy-s26"]
    look.phone_order.list.setCurrentRow(1)
    look.phone_order.step(-1)
    assert page.store.look()["phone_order"] == lk.PHONE_ORDER_MANUAL
    assert "دستی" in look.phone_mode.text()
    settle(admin_qapp)
    assert "ترتیب گوشی‌ها" in page.preview_box.toPlainText()
    look._auto_order()
    assert page.store.look()["phone_order"] == lk.PHONE_ORDER_AUTO


def test_featured_phones(page, monkeypatch):
    look = page.look_tab

    class Picker:
        def __init__(self, phones, room, parent):
            self.chosen = [phones[0]["code"]]
            assert room == lk.FEATURED_MAX

        def exec(self):
            return True

    monkeypatch.setattr(sl, "PickPhonesDialog", Picker)
    look._featured_add()
    assert page.store.look()["featured"] == ["iphone-17"]
    assert look.featured.keys() == ["iphone-17"]
    look.featured.list.setCurrentRow(0)
    look._featured_remove()
    assert page.store.look()["featured"] == []
    assert "خودکار" in look.featured_state.text()


def test_pick_phones_dialog_limits(admin_qapp):
    dialog = sl.PickPhonesDialog([{"code": "a-1", "name": "A1"}, {"code": "b-2", "name": "B2"}], 1)
    dialog._accept()
    assert "تیک" in dialog.error_label.text()
    for n in range(2):
        dialog.list.item(n).setCheckState(Qt.CheckState.Checked)
    dialog._accept()
    assert "جا دارد" in dialog.error_label.text()
    dialog.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog._accept()
    assert dialog.chosen == ["a-1"]


def test_palette_logo_and_banner_picture(page, monkeypatch):
    look = page.look_tab
    look.palette_cards["emerald"].click()
    assert page.store.look()["palette"] == "emerald"
    monkeypatch.setattr(sl, "read_picture", lambda _p: image_bytes(400, 300))
    look._pick_logo()
    assert page.store.look()["logo"].startswith("logo-") and look.logo_clear.isEnabled()
    look._add_banner()
    assert len(page.store.look()["hero"]["images"]) == 1
    assert look.banner_list.list.count() == 1
    look.banner_list.list.setCurrentRow(0)
    look._remove_banner()
    assert page.store.look()["hero"]["images"] == []
    look._clear_logo()
    assert page.store.look()["logo"] == ""


def test_banner_texts_saved_and_checked(page):
    look = page.look_tab
    look.hero_inputs["title"].setText("")
    look.hero_inputs["highlight"].setText("")
    look._dirty("banner")
    assert not look.save_banner() and page.errors
    look.hero_inputs["title"].setText("گوشی تازه، قیمت روز")
    look.badge_inputs[0][0].setText("ضمانت")
    assert look.save_banner()
    hero = page.store.look()["hero"]
    assert hero["title"] == "گوشی تازه، قیمت روز" and hero["badges"][0]["title"] == "ضمانت"
    look._reset_banner()
    assert page.store.look()["hero"]["title"] == lk.DEFAULT_LOOK["hero"]["title"]


def test_sections_order_and_hide_but_never_all(page):
    look = page.look_tab
    look.sections.list.item(5).setCheckState(Qt.CheckState.Unchecked)       # faq
    rows = page.store.look()["sections"]
    assert rows[5] == {"key": "faq", "show": False}
    look.sections.list.setCurrentRow(5)
    look.sections.step(-5)
    assert page.store.look()["sections"][0]["key"] == "faq"
    for n in range(6):
        look.sections.list.item(n).setCheckState(Qt.CheckState.Unchecked)
    assert any(s["show"] for s in page.store.look()["sections"])


def test_store_info_with_checks(page):
    look = page.look_tab
    look.store_inputs["phone"].setText("12")
    look.store_inputs["map"].setText("https://evil.com/x")
    assert not look.save_store()
    assert "تلفن" in look.store_error.text() and "نقشه" in look.store_error.text()
    look.store_inputs["phone"].setText("۰۵۱ ۳۱۲۳ ۴۵۶۷")
    look.store_inputs["map"].setText("https://nshn.ir/abc")
    look.store_inputs["telegram_channel"].setText("@asr_channel")
    look.hour_inputs[3][0].setText("جمعه")
    look.hour_inputs[3][1].setText("تعطیل")
    assert look.save_store()
    store = page.store.look()["store"]
    assert store["phone"] == "05131234567" and store["telegram_channel"] == "https://t.me/asr_channel"
    assert store["hours"][-1] == ["جمعه", "تعطیل"]
    assert look.store_inputs["telegram_channel"].text() == "https://t.me/asr_channel"


def test_unsaved_form_is_saved_before_publish_or_refused(page):
    look = page.look_tab
    look.store_inputs["phone"].setText("abc")
    look._dirty("store")
    assert not look.save_pending() and look.tabs.currentIndex() == 5
    look.store_inputs["phone"].setText("09150000000")
    assert look.save_pending() and not look.is_dirty()
    assert page.store.look()["store"]["phone"] == "09150000000"


def test_browser_preview_from_the_site_folder(page, site_folder, ui_context, monkeypatch):
    (site_folder / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (site_folder / "assets" / "site.js").write_text("/* asr-site-look */", encoding="utf-8")
    ui_context.store.set_setting(site_page.PREVIEW_FOLDER_SETTING, str(site_folder))
    opened = []
    monkeypatch.setattr(SitePage, "open_url", staticmethod(opened.append))
    page.store.update_look(lambda look: look.update(palette="ruby"))
    try:
        page._preview_browser()
        assert opened and opened[0].startswith("http://127.0.0.1:")
        with urllib.request.urlopen(opened[0] + "assets/catalog/site.json", timeout=5) as answer:
            assert json.loads(answer.read())["palette"] == "ruby"
    finally:
        pv.PreviewServer.stop()


def test_browser_preview_needs_folder_or_token(page, monkeypatch):
    opened = []
    monkeypatch.setattr(SitePage, "open_url", staticmethod(opened.append))
    page._preview_browser()
    assert not opened and "پوشهٔ سایت" in page.errors[-1]


def test_publish_and_roll_back_the_look(page, ui_context, monkeypatch):
    fake = FakeGitHub(files={"index.html": b"<html>", "assets/site.js": b"/* asr-site-look */"})
    monkeypatch.setattr(SitePage, "github_transport", fake.transport())
    monkeypatch.setattr(tk, "_dpapi", lambda data, protect: data)
    monkeypatch.setattr(site_page, "run_async", lambda task, on_success, on_error, on_done:
                        (on_success(task()), on_done()))
    tk.save(ui_context.store, TOKEN)
    page.look_tab.palette_cards["sunset"].click()
    page._publish()
    assert json.loads(fake.files()["assets/catalog/site.json"])["palette"] == "sunset"
    assert "یکی است" in page.banner.text()
    page._rollback()
    assert "assets/catalog/site.json" not in fake.files()
    assert TOKEN not in json.dumps({k: v.decode("utf-8", "replace") for k, v in fake.files().items()})
