"""v2.13.0: glass buttons with a light glow on hover, captions and values in
clean columns, short groups that never break, dialogs inside the main window,
«دریافت لیست اکنون» / «خواندن دوباره» and the server page's archive row."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QRect  # noqa: E402
from PySide6.QtGui import QEnterEvent  # noqa: E402
from PySide6.QtWidgets import QDialog, QLabel, QMainWindow, QVBoxLayout  # noqa: E402

from app.ui import theme, widgets  # noqa: E402
from app.ui.pages import pricelist as pl  # noqa: E402
from app.ui.pages import server as server_page  # noqa: E402


@pytest.mark.parametrize("palette", theme.PALETTE_NAMES)
@pytest.mark.parametrize("mode", ("light", "dark"))
@pytest.mark.parametrize("effects", ("full", "simple"))
def test_every_look_has_glass_buttons(admin_qapp, palette, mode, effects, monkeypatch):
    # only the style sheet text (applying it to the test app's many widgets is slow)
    old_mode, old_palette = theme.MODE, theme.PALETTE
    theme.set_mode(mode, palette)
    monkeypatch.setattr(theme, "EFFECTS", effects)
    try:
        sheet = theme.stylesheet()
        rule = sheet.split("QPushButton {", 1)[1].split("}", 1)[0]
        # v2.18.0: a soft tint of the look, never dark
        assert theme.soft_border() in rule and theme.BUTTON_BORDER not in rule
        assert "QPushButton:hover" in sheet and "QPushButton:pressed" in sheet
        pressed = sheet.split("QPushButton:pressed {", 1)[1].split("}", 1)[0]
        # v2.18.0: no dark bottom line in any state; the text moves 1px down instead
        assert "padding-top: 9px" in pressed and "2px solid" not in rule
        primary = sheet.split("QPushButton#Primary {", 1)[1].split("}", 1)[0]
        background = primary.split("background:", 1)[1].split(";", 1)[0]
        assert "rgba(" not in background                    # prominent stays coloured
        assert "border-top: 1px solid rgba(255, 255, 255" in primary   # the site's top highlight
        assert "transparent" in primary                     # no dark frame
        # v2.15.0: the live site's «ثبت سفارش» gradient in every look
        assert all(stop in primary for stop in theme.SITE_GRAD)
    finally:
        theme.set_mode(old_mode, old_palette)


def test_glow_on_hover_only(admin_qapp, monkeypatch):
    # the effects filter on its own (applying the theme to the test app is slow)
    monkeypatch.setattr(theme, "EFFECTS", "full")
    fx = theme._Effects()
    button = widgets.button("بستن")
    fx.eventFilter(button, QEvent(QEvent.Type.Polish))
    assert button.graphicsEffect() is None                 # idle: nothing drawn
    fx.eventFilter(button, QEvent(QEvent.Type.Enter))
    glow = button.graphicsEffect()
    assert glow is not None and glow.offset().y() == 0
    assert glow.color().name().upper() == theme.SITE_CYAN.upper()   # v2.15.0: the site's hover
    fx.eventFilter(button, QEvent(QEvent.Type.Leave))
    assert button.graphicsEffect() is None
    # a coloured button: its shadow becomes a glow, and back
    primary = widgets.button("ذخیره", variant="primary")
    fx.eventFilter(primary, QEvent(QEvent.Type.Polish))
    effect = primary.graphicsEffect()
    assert effect is not None
    fx.eventFilter(primary, QEvent(QEvent.Type.Enter))
    assert effect.color().name().upper() == theme.SITE_GLOW.upper()
    fx.eventFilter(primary, QEvent(QEvent.Type.Leave))
    # v2.14.0: at rest a soft glow of the gradient's colour (the site's «ثبت سفارش»)
    assert effect.color().name().upper() == theme.rest_glow().name().upper()
    button.deleteLater()
    primary.deleteLater()


def test_keep_together():
    text = widgets.keep_together("مریم حسینی (کد شخص ۴) در «hesab5 t» — ۳۶ دقیقه")
    assert "(کد\u00a0شخص\u00a0۴)" in text
    assert "«hesab5\u00a0t»" in text
    assert "۳۶\u00a0دقیقه" in text
    assert "مریم حسینی" in text                          # ordinary words still wrap
    label = widgets.label("مشتری (کد شخص ۴)", wrap=True)
    assert "\u00a0" in QLabel.text(label)      # drawn together
    assert label.text() == "مشتری (کد شخص ۴)"     # the text itself unchanged
    assert "\u00a0" not in QLabel.text(widgets.label("مشتری (کد شخص ۴)"))


def test_key_value_list_is_two_aligned_columns(admin_qapp):
    rows = widgets.KeyValueList()
    rows.add("مشتری", "مریم حسینی (کد شخص ۴)")
    rows.add("کد شخص در حسابداری", "۴")
    rows.resize(500, 200)
    rows.show()
    admin_qapp.processEvents()
    first, second = rows.captions
    assert rows.grid.itemAtPosition(0, 0).widget() is first
    assert rows.grid.itemAtPosition(1, 0).widget() is second
    # captions share one column: the same width, values start at one x
    assert first.width() == second.width()
    v1 = rows.grid.itemAtPosition(0, 1).widget()
    v2 = rows.grid.itemAtPosition(1, 1).widget()
    assert v1.geometry().x() == v2.geometry().x()
    rows.close()


def test_dialog_never_larger_than_its_main_window(admin_qapp):
    main = QMainWindow()
    main.setGeometry(200, 150, 900, 600)
    main.show()
    admin_qapp.processEvents()

    class Tall(widgets.ResponsiveDialog):
        def __init__(self, parent):
            super().__init__(parent)
            root = QVBoxLayout(self)
            self.setMinimumSize(1200, 1400)
            for i in range(40):
                root.addWidget(widgets.label(f"ردیف {i}"))
            root.addWidget(widgets.button("بستن", on_click=self.reject))

    dialog = Tall(main)
    dialog._prepare()
    widgets.fit_window_to_screen(dialog)
    area = widgets.dialog_area(dialog)
    inner = main.geometry().intersected(widgets.available_geometry(dialog))
    assert area == inner
    assert dialog.width() <= main.width() and dialog.height() <= main.height()
    assert main.geometry().contains(QRect(dialog.pos(), dialog.size()).center())
    assert dialog.x() >= area.left() and dialog.x() + dialog.width() <= area.right() + 1
    # centred on the main window (horizontally)
    assert abs((dialog.x() + dialog.width() // 2) - area.center().x()) <= 2
    dialog.close()
    main.close()


def test_dialog_without_main_window_uses_the_screen(admin_qapp):
    dialog = QDialog()
    assert widgets.dialog_area(dialog) == widgets.available_geometry(dialog)


def test_reason_fa_and_outcomes():
    assert "نقد/روال" in pl.reason_fa("parse failed: price headers are not on one line")
    assert pl.reason_fa("something else") == "something else"
    for outcome in ("read", "missing", "timeout"):
        assert pl.OUTCOME_FA[outcome]


def test_archive_and_backup_rows():
    key, text, _ = server_page.archive_text({"path": r"D:\ShopServerData\pricelists",
                                             "files": 3, "bytes": 3 * 1024 * 1024})
    assert key == "archive" and r"D:\ShopServerData\pricelists" in text and "۳ فایل" in text
    _, text, color = server_page.backup_text({
        "at": "2026-10-27T03:00:00+03:30", "ok": False, "local_ok": True,
        "offsite_reason_fa": "پوشهٔ پشتیبان روی رایانهٔ دیگری است",
        "last_success_at": "2026-10-25T03:00:00+03:30"})
    assert "روی رایانهٔ دیگری" in text and "روی خود سرور: سالم" in text
    assert color == theme.DANGER
    _, text, color = server_page.telegram_text({"at": "2026-10-27T10:00:00+00:00",
                                                "paused_until": "2026-10-27T12:00:00+00:00"})
    assert "صبر" in text and color == theme.WARNING_TEXT


# ---- v2.13.0: picking a database grants the service access by itself ------------------------
from .test_v294 import _pump, server_folder  # noqa: E402,F401
from app import server_setup as setup  # noqa: E402


def test_picking_a_database_grants_access_and_connects(server_folder, admin_qapp,  # noqa: F811
                                                      monkeypatch):
    from app.ui import server_setup_wizard as wiz

    monkeypatch.setattr(setup, "harden_data_dir", lambda *a, **k: None)
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: {"ok": True})
    granted = []

    def check():
        if not granted:
            raise setup.database_error({"ok": False, "kind": "no_access",
                                        "title_fa": "دسترسی نیست", "fix_fa": "دسترسی بدهید.",
                                        "error_code": "4060"})
        return {"ok": True, "groups": 3}

    def grant():
        granted.append(1)
        return {"ok": True, "login": "NT SERVICE\\ShopServer", "database": "hesab2",
                "steps": ["login_created", "user_ready", "role_granted"], "check_ok": True,
                "as_service": True}

    monkeypatch.setattr(setup, "check_database", check)
    monkeypatch.setattr(setup, "service_db_check", lambda *a: None)
    monkeypatch.setattr(setup, "grant_database_access", grant)
    confirms = []
    monkeypatch.setattr(wiz.widgets, "confirm", lambda *a, **k: confirms.append(1) or True)
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        wizard.auth_windows.setChecked(True)
        wizard.db_name.set_names(["hesab2", "hesab5", "hesab5 t"])
        wizard.db_name.setText("hesab2")
        wizard._db_picked()
        _pump(400, until=lambda: wizard._db_ok)
        assert granted == [1] and wizard._db_ok
        assert confirms == []                                # no question asked
        assert "داده شد" in wizard.db_result.text()
    finally:
        wizard.close()


def test_automatic_grant_failure_still_says_no_access(server_folder, admin_qapp,  # noqa: F811
                                                       monkeypatch):
    from app.ui import server_setup_wizard as wiz

    monkeypatch.setattr(setup, "harden_data_dir", lambda *a, **k: None)
    monkeypatch.setattr(setup, "write_config", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(setup, "check_database", lambda: (_ for _ in ()).throw(
        setup.database_error({"ok": False, "kind": "no_access", "title_fa": "دسترسی نیست",
                              "fix_fa": "x", "error_code": "4060"})))

    def refused():
        raise setup.SetupError("حساب ویندوز شما در SQL Server «sysadmin» نیست.")

    monkeypatch.setattr(setup, "grant_database_access", refused)
    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        wizard.auth_windows.setChecked(True)
        wizard.db_name.set_names(["hesab2"])
        wizard.db_name.setText("hesab2")
        wizard._db_picked()
        _pump(400, until=lambda: "sysadmin" in wizard.db_result.text())
        assert "دسترسی نیست" in wizard.db_result_title.text()
        assert "sysadmin" in wizard.db_result.text() and not wizard._db_ok
    finally:
        wizard.close()
