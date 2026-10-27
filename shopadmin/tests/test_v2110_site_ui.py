"""v2.11.0 «سایت» page and dialogs: local data, show / hide, add a phone with a
photo per colour, accessories, preview, publish + roll back to a FAKE GitHub."""
from __future__ import annotations

import json
import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog  # noqa: E402

from app.site import catalog as cat  # noqa: E402
from app.site import token as tk  # noqa: E402
from app.statuses import ROLE_OPERATOR  # noqa: E402
from app.ui import site_dialogs as sd  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.main_window import NAV_ITEMS  # noqa: E402
from app.ui.pages import site as site_page  # noqa: E402
from app.ui.pages.site import SitePage  # noqa: E402

from .fake_github import TOKEN, FakeGitHub  # noqa: E402
from .test_catalog_models import _select  # noqa: E402
from .test_ui import _render_page, make_context_with_role, ui_context  # noqa: E402,F401
from .test_v2110_site import image_bytes, site_folder  # noqa: E402,F401

NL = chr(10)


@pytest.fixture
def page(admin_qapp, ui_context, site_folder, monkeypatch):
    monkeypatch.setattr(widgets, "success", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "info", lambda *a, **k: None)
    page = SitePage(ui_context)
    page.store.seed_from_folder(site_folder)
    _render_page(admin_qapp, page)
    return page


def test_nav_has_the_site_section_for_managers_only(ui_context):
    assert ("site", "سایت", "globe") == next(i[:3] for i in NAV_ITEMS if i[0] == "site")
    assert ui_context.can(site_page.CATALOG_MANAGE)
    assert not make_context_with_role(ui_context, ROLE_OPERATOR).can(site_page.CATALOG_MANAGE)


def test_data_lives_in_the_local_data_folder(page, ui_context):
    assert page.store.root.parent == __import__("pathlib").Path(ui_context.store.path).parent
    assert page.phones_table.rowCount() == 2
    assert "با سایت یکی است" in page.banner.text()


def test_show_hide_one_button(page):
    _select(page.phones_table, 1)
    item = page._phones[1]
    page._toggle(page.phones_table, cat.KIND_PHONE)
    assert page.store.get(item["code"])["hidden"]
    assert "از سایت برداشته می‌شود" in page.preview_box.toPlainText()
    _select(page.phones_table, 1)
    page._toggle(page.phones_table, cat.KIND_PHONE)
    assert not page.store.get(item["code"])["hidden"]


def test_add_phone_with_a_photo_per_colour(page, monkeypatch):
    dialog = sd.PhoneDialog(page.store, parent=page)
    dialog.brand.setCurrentIndex(dialog.brand.findData("samsung"))
    dialog.name.setText("Galaxy A57")
    assert dialog.code.text() == "galaxy-a57"
    dialog._new_color()
    dialog.colors.item(0, 0).setText("سرمه‌ای")
    monkeypatch.setattr(sd, "read_photo", lambda _p: image_bytes(500, 400))
    dialog.colors.setCurrentCell(0, 0)
    dialog._color_photo()
    dialog.specs.setPlainText("باتری: 5000 میلی‌آمپر ساعت" + NL + "بی دونقطه")
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = page.store.get("galaxy-a57")
    assert saved["specs"] == [["باتری", "5000 میلی‌آمپر ساعت"]]
    photo = saved["colors"][0]["image"]
    assert photo.startswith("galaxy-a57-c") and page.store.has_photo(photo)
    page.render()
    assert "➕ گوشی تازه در سایت: Galaxy A57" in page.preview_box.toPlainText()


def test_phone_form_says_what_is_missing(page):
    dialog = sd.PhoneDialog(page.store, parent=page)
    dialog._save()
    assert "نام" in dialog.error_label.text() and "رنگ" in dialog.error_label.text()


def test_accessory_form(page, monkeypatch):
    dialog = sd.AccessoryDialog(page.store, parent=page)
    dialog.name.setText("پاوربانک Anker 20000")
    dialog.group.setCurrentIndex(dialog.group.findData("powerbank"))
    monkeypatch.setattr(sd, "read_photo", lambda _p: image_bytes(300, 300))
    dialog._pick_photo()
    dialog.description.setPlainText("  شارژ سریع  ")
    dialog._save()
    item = page.store.items(cat.KIND_ACCESSORY)[0]
    assert item["group"] == "powerbank" and item["description"] == "شارژ سریع"
    assert page.store.has_photo(item["image"])


def test_publish_and_rollback_to_fake_github(page, ui_context, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("the token is stored with Windows DPAPI")
    fake = FakeGitHub()
    monkeypatch.setattr(SitePage, "github_transport", fake.transport())
    monkeypatch.setattr(site_page.widgets, "confirm", lambda *a, **k: True)
    errors = []
    monkeypatch.setattr(site_page.widgets, "error", lambda _p, _t, text: errors.append(text))
    page.token_input.setText(TOKEN)
    page._save_token()
    assert tk.has_token(ui_context.store) and page.token_input.text() == ""
    assert TOKEN not in page.token_state.text()

    def run_now(task, on_success, on_error=None, on_done=None, **_k):
        on_success(task())
        if on_done:
            on_done()

    monkeypatch.setattr(site_page, "run_async", run_now)
    page._test_connection()
    page._publish()
    assert not errors
    catalog = json.loads(fake.files()["assets/catalog/catalog.json"])
    assert len(catalog["items"]) == 2 and fake.dispatches == ["main"]
    _select(page.phones_table, 0)
    page._toggle(page.phones_table, cat.KIND_PHONE)
    page._publish()
    assert len(json.loads(fake.files()["assets/catalog/catalog.json"])["items"]) == 1
    assert page.rollback_button.isEnabled()
    page._rollback()
    assert len(json.loads(fake.files()["assets/catalog/catalog.json"])["items"]) == 2
    assert all(TOKEN not in e for e in errors)


def test_publish_without_token_says_so(page, monkeypatch):
    messages = []
    monkeypatch.setattr(site_page.widgets, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(site_page.widgets, "error", lambda _p, _t, text: messages.append(text))

    def run_now(task, on_success, on_error=None, on_done=None, **_k):
        on_success(task())

    monkeypatch.setattr(site_page, "run_async", run_now)
    page._publish()
    assert messages and "توکن" in messages[0]


def test_backup_restore_from_the_page(page, tmp_path, monkeypatch):
    target = tmp_path / "b.zip"
    monkeypatch.setattr(site_page.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    page._backup()
    assert target.is_file()
    page.store.set_hidden("iphone-17", True)
    monkeypatch.setattr(site_page.QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(site_page.widgets, "confirm", lambda *a, **k: True)
    page._restore()
    assert not page.store.get("iphone-17")["hidden"]


def test_operator_cannot_change(admin_qapp, ui_context):
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    page = SitePage(context)
    assert not page.add_phone_button.isEnabled() and not page.publish_button.isEnabled()
