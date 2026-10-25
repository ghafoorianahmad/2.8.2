"""Phase 6b: the «مدل‌های سایت» page (REQUIREMENTS §9a) - import from the site's
products.js, fuzzy suggestions, mapping, drift / hidden models, confirm."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from app.notifications import SERVER_WARNINGS, TARGETS  # noqa: E402
from app.permissions import CATALOG_MANAGE, CATALOG_VIEW, has_permission  # noqa: E402
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER  # noqa: E402
from app.ui.pages import catalog_models as cm  # noqa: E402
from app.ui.pages.catalog_models import CatalogModelsPage, PickProductDialog, TextDialog  # noqa: E402

from .test_ui import PERSIAN_RE, _render_page, make_context_with_role, ui_context  # noqa: E402,F401

NL = chr(10)
SITE_JS = Path(__file__).resolve().parents[3] / "projects" / "asr-ertebatat-2-redesign" / \
    "assets" / "products.js"

SAMPLE_JS = NL.join([
    "const CATALOG = {",
    "  apple: {",
    '    name: "Apple", mark: "apple", tagline: "x",',
    "    items: [",
    '      { id: "iphone-17-pro", name: "iPhone 17 Pro", tier: "پرچمدار",',
    '        aliases: ["آیفون ۱۷ پرو", "iphone17pro"],',
    '        spec: { "وزن": "199 گرم" } },',
    '      { id: "iphone-17", name: "iPhone 17", tier: "پرچمدار",',
    '        spec: { "وزن": "177 گرم" } }',
    "    ]",
    "  },",
    "  samsung: {",
    '    name: "Samsung", mark: "samsung", tagline: "y",',
    "    items: [",
    '      { id: "galaxy-s26-plus", name: "Galaxy S26+", aliases: ["گلکسی اس ۲۶ پلاس"] }',
    "    ]",
    "  }",
    "};",
])


# ---- pure helpers -------------------------------------------------------------------
def test_parse_products_js_sample():
    models = cm.parse_products_js(SAMPLE_JS)
    assert [m["slug"] for m in models] == ["iphone-17-pro", "iphone-17", "galaxy-s26-plus"]
    assert [m["brand"] for m in models] == ["Apple", "Apple", "Samsung"]
    assert models[0]["aliases"] == ["آیفون ۱۷ پرو", "iphone17pro"]
    assert models[1]["aliases"] == []
    assert models[2]["name"] == "Galaxy S26+"
    assert cm.parse_products_js("var x = 1;") == []


@pytest.mark.skipif(not SITE_JS.exists(), reason="live site repo not on this PC")
def test_parse_the_live_site_catalog():
    models = cm.parse_products_js(SITE_JS.read_text(encoding="utf-8"))
    slugs = [m["slug"] for m in models]
    assert len(slugs) >= 60 and len(set(slugs)) == len(slugs)
    assert {m["brand"] for m in models} >= {"Apple", "Samsung"}
    assert all(m["name"] and m["brand"] for m in models)


def test_filters_labels_and_scores():
    ok = {"status": "ok", "name": "iPhone 17", "slug": "iphone-17", "drifted_count": 1}
    hidden = {"status": "review", "name": "Galaxy S25", "slug": "galaxy-s25", "brand": "Samsung"}
    assert cm.model_matches(ok, "drifted") and not cm.model_matches(hidden, "drifted")
    assert cm.model_matches(hidden, "review") and not cm.model_matches(ok, "review")
    assert cm.model_matches(hidden, "all", "samsung") and not cm.model_matches(ok, "all", "samsung")
    assert cm.filter_label("review", {"review": 2}) == "پنهان (منتظر تأیید) (۲)"
    assert cm.score_fa(0.874) == "۸۷٪" and cm.score_fa(None) == "—"
    assert "هنوز" in cm.check_summary_fa(None)
    assert "۱ مدل پنهان شد" in cm.check_summary_fa(
        {"at": "2026-10-12T02:00:00+00:00", "checked": 3, "drifted": 1, "missing": 1,
         "newly_hidden": ["x"]})


def test_permissions_and_notification():
    # v2.7.0: site models are for «مدیر» only («کاربر فروش» = operator / old viewer)
    for role in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        assert has_permission(role, CATALOG_VIEW)
    assert not has_permission(ROLE_OPERATOR, CATALOG_VIEW)
    assert not has_permission(ROLE_OPERATOR, CATALOG_MANAGE)
    assert not has_permission(ROLE_VIEWER, CATALOG_MANAGE)
    assert has_permission(ROLE_ADMIN, CATALOG_MANAGE)
    assert has_permission(ROLE_SUPER_ADMIN, CATALOG_MANAGE)
    assert PERSIAN_RE.search(SERVER_WARNINGS["model_review"])
    assert TARGETS["model_review"] == ("catalog", "review")


# ---- page ---------------------------------------------------------------------------------
def _seed(fake_api):
    fake_api.products = {
        289: {"code": 289, "name": "آیفون 17 پرو 256 گیگ"},
        290: {"code": 290, "name": "آیفون 17 پرو 512 گیگ"},
        301: {"code": 301, "name": "گلکسی S25 اولترا 512"},
        302: {"code": 302, "name": "گلکسی S25 اولترا 256"},
    }
    pro = fake_api.add_catalog_model("iphone-17-pro", "iPhone 17 Pro")
    fake_api.add_catalog_item(pro["id"], 289, "آیفون 17 پرو 256 گیگ", label="256 گیگ",
                              state="drifted", current_name="آیفون 17 پرو 256 گیگ آبی", score=0.92)
    s25 = fake_api.add_catalog_model("galaxy-s25-ultra", "Galaxy S25 Ultra", "Samsung",
                                     hidden=True)
    fake_api.add_catalog_item(s25["id"], 300, "گلکسی S25 اولترا 512", state="missing",
                              current_name="", candidates=[
                                  {"code": 301, "name": "گلکسی S25 اولترا 512", "score": 1.0}])
    fake_api.add_catalog_model("iphone-17", "iPhone 17")
    return pro, s25


def _page(ui_context, admin_qapp, role=ROLE_SUPER_ADMIN):
    page = CatalogModelsPage(make_context_with_role(ui_context, role))
    _render_page(admin_qapp, page)
    return page


def _pump(admin_qapp, page):
    _render_page(admin_qapp, page, load=False)


def _select(table, row):
    model = table.selectionModel()
    model.clearSelection()
    model.select(table.model().index(row, 0),
                 QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def _open(page, admin_qapp, slug):
    rows = [m["slug"] for m in page._visible_models()]
    _select(page.models_table, rows.index(slug))
    _pump(admin_qapp, page)
    assert page._detail and page._detail["slug"] == slug


def test_page_title_is_persian(ui_context):
    page = CatalogModelsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert PERSIAN_RE.search(page.title) and PERSIAN_RE.search(page.subtitle)
    page.close()


def test_sidebar_has_the_page(ui_context, admin_qapp):
    from app.ui.main_window import MainWindow

    window = MainWindow(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    assert "catalog" in window._nav_buttons
    window.close()


def test_models_load_with_status_counts_and_banner(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)
    assert page.models_table.rowCount() == 3
    assert page.filter_combo.itemText(0) == "پنهان (منتظر تأیید) (۱)"
    assert "۱ مدل از دید مشتری پنهان" in page.banner.text()
    assert "نگاشت" in page.banner.text()            # one unmapped model
    page.set_filter("review")
    assert [m["slug"] for m in page._visible_models()] == ["galaxy-s25-ultra"]
    page.set_filter("drifted")
    assert [m["slug"] for m in page._visible_models()] == ["iphone-17-pro"]
    page.set_filter("all")
    page.search.setText("سامسونگ")                   # brand search is not translated
    assert page.models_table.rowCount() == 0
    page.search.setText("samsung")
    assert page.models_table.rowCount() == 1
    page.close()


def test_detail_shows_drift_and_accept(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _open(page, admin_qapp, "iphone-17-pro")
    assert page.items_table.rowCount() == 1
    assert page.items_table.item(0, 4).text() == "نام تغییرکرده"
    assert page.items_table.item(0, 3).text().endswith("آبی")
    assert page.items_table.item(0, 5).text() == "۹۲٪"
    assert "پذیرش نام فعلی" in page.detail_hint.text()
    assert not page.confirm_button.isEnabled()        # visible model: nothing to confirm
    _select(page.items_table, 0)
    page._accept_item()
    _pump(admin_qapp, page)
    assert fake_api.catalog_items[0]["state"] == "ok"
    assert ("POST", "/admin/catalog-models/items/1/accept") in fake_api.requests
    page.close()


def test_hidden_model_replace_with_candidate_then_confirm(ui_context, fake_api, admin_qapp,
                                                          monkeypatch):
    _seed(fake_api)
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _open(page, admin_qapp, "galaxy-s25-ultra")
    assert page.confirm_button.isEnabled()
    # confirm is refused locally while an item is missing
    page._confirm_model()
    assert not any(p.endswith("/confirm") for _, p in fake_api.requests)

    def fake_exec(dialog):
        # the nightly candidates are listed first (heading + one row)
        assert dialog.results.count() == 2 and "۱۰۰٪" in dialog.results.item(1).text()
        dialog.results.setCurrentRow(1)
        assert dialog.code_input.value() == 301
        dialog.label_input.setText("512 گیگ")
        dialog._accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PickProductDialog, "exec", fake_exec)
    _select(page.items_table, 0)
    page._replace_item()
    _pump(admin_qapp, page)
    item = fake_api.catalog_items[1]
    assert (item["kala_code"], item["state"], item["label"]) == (301, "ok", "512 گیگ")
    page._confirm_model()
    _pump(admin_qapp, page)
    assert fake_api.catalog_models[1]["hidden"] is False
    assert page._detail["status"] == "ok"
    page.close()


def test_add_item_from_suggestions(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    page = _page(ui_context, admin_qapp)
    _open(page, admin_qapp, "iphone-17-pro")

    def fake_exec(dialog):
        texts = [dialog.results.item(i).text() for i in range(dialog.results.count())]
        assert any("۲۹۰" in t for t in texts)
        assert any("نگاشته به iphone-17-pro" in t for t in texts)     # 289 is taken
        dialog.code_input.setValue(290)
        dialog.label_input.setText("512 گیگ")
        dialog._accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PickProductDialog, "exec", fake_exec)
    page._add_item()
    _pump(admin_qapp, page)
    assert [i["kala_code"] for i in fake_api.catalog_items if i["model_id"] == 1] == [289, 290]
    assert page.items_table.rowCount() == 2
    page.close()


def test_pick_dialog_needs_a_code(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    dialog = PickProductDialog(ui_context, {"id": 3, "name": "iPhone 17", "slug": "iphone-17"})
    dialog._accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error_label.text()
    dialog.search.setText("هیچ‌چیز")
    dialog.load_suggestions()
    assert dialog.results.count() == 0 and "پیدا نشد" in dialog.error_label.text()
    dialog.close()


def test_label_aliases_and_delete(ui_context, fake_api, admin_qapp, monkeypatch):
    _seed(fake_api)
    monkeypatch.setattr("app.ui.widgets.confirm", lambda *a, **k: True)
    page = _page(ui_context, admin_qapp)
    _open(page, admin_qapp, "iphone-17-pro")

    def label_exec(dialog):
        dialog.input.setText("۲۵۶ گیگ")
        dialog._accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TextDialog, "exec", label_exec)
    _select(page.items_table, 0)
    page._edit_label()
    _pump(admin_qapp, page)
    assert fake_api.catalog_items[0]["label"] == "۲۵۶ گیگ"

    def aliases_exec(dialog):
        dialog.input.setPlainText("آیفون ۱۷ پرو" + NL + "هفده پرو")
        dialog._accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TextDialog, "exec", aliases_exec)
    page._edit_aliases()
    _pump(admin_qapp, page)
    assert fake_api.catalog_models[0]["aliases"].splitlines() == ["آیفون ۱۷ پرو", "هفده پرو"]
    assert "هفده پرو" in page.detail_hint.text()
    _select(page.items_table, 0)
    page._delete_item()
    _pump(admin_qapp, page)
    assert not [i for i in fake_api.catalog_items if i["model_id"] == 1]
    page.close()


def test_read_from_site_now_and_check_now(ui_context, fake_api, admin_qapp, monkeypatch):
    """v2.9.3: no products.js file: «خواندن از سایت اکنون» asks the server."""
    fake_api.site_models = cm.parse_products_js(SAMPLE_JS)
    page = _page(ui_context, admin_qapp)
    assert page.read_site_button.text() == "خواندن از سایت اکنون"
    page._read_site()
    _pump(admin_qapp, page)
    assert fake_api.site_reads == 1
    assert page.models_table.rowCount() == 3
    assert "آخرین خواندن سایت" in page.banner.text()
    shown = []
    monkeypatch.setattr("app.ui.widgets.info", lambda *a, **k: shown.append(a))
    page._check_now()
    _pump(admin_qapp, page)
    assert fake_api.catalog_checks == 1 and "آخرین بررسی" in page.banner.text()
    page.close()


def test_viewer_and_operator_are_read_only(ui_context, fake_api, admin_qapp):
    _seed(fake_api)
    for role in (ROLE_VIEWER, ROLE_OPERATOR):
        page = _page(ui_context, admin_qapp, role)
        assert not page.import_button.isEnabled() and not page.check_button.isEnabled()
        _open(page, admin_qapp, "iphone-17-pro")
        assert not any(b.isEnabled() for b in page._detail_buttons)
        page.close()


def test_load_error_leaves_an_error_state(ui_context, fake_api, admin_qapp):
    fake_api.force_status = 503
    fake_api.force_detail = "Accounting database unavailable"
    page = _page(ui_context, admin_qapp)
    assert page.models_table.rowCount() == 0
    page.close()
