"""v2.13.0: glass buttons with a light glow on hover, captions and values in
clean columns, short groups that never break, dialogs inside the main window,
«دریافت لیست اکنون» / «خواندن دوباره» and the server page's archive row."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QRect  # noqa: E402
from PySide6.QtGui import QEnterEvent  # noqa: E402
from PySide6.QtWidgets import QDialog, QMainWindow, QVBoxLayout  # noqa: E402

from app.ui import theme, widgets  # noqa: E402
from app.ui.pages import pricelist as pl  # noqa: E402
from app.ui.pages import server as server_page  # noqa: E402


@pytest.mark.parametrize("palette", theme.PALETTE_NAMES)
@pytest.mark.parametrize("mode", ("light", "dark"))
@pytest.mark.parametrize("effects", ("full", "simple"))
def test_every_look_has_glass_buttons(admin_qapp, palette, mode, effects):
    theme.apply_theme(admin_qapp, mode, palette=palette, effects=effects)
    try:
        sheet = theme.stylesheet()
        rule = sheet.split("QPushButton {", 1)[1].split("}", 1)[0]
        assert "rgba(" in rule                              # see-through fill
        assert "QPushButton:hover" in sheet and "QPushButton:pressed" in sheet
        pressed = sheet.split("QPushButton:pressed {", 1)[1].split("}", 1)[0]
        assert "border-top: 2px" in pressed and "border-bottom: 1px" in pressed
        primary = sheet.split("QPushButton#Primary {", 1)[1].split("}", 1)[0]
        assert "rgba(" not in primary                       # prominent stays coloured
    finally:
        theme.apply_theme(admin_qapp, "light", palette="ocean", effects="full")


def test_glow_on_hover_only(admin_qapp):
    theme.apply_theme(admin_qapp, "light", palette="ocean", effects="full")
    button = widgets.button("بستن")
    button.show()
    admin_qapp.processEvents()
    # (a window shown under the pointer may get an «enter» at once)
    theme._EFFECTS_FILTER.eventFilter(button, QEvent(QEvent.Type.Leave))
    assert button.graphicsEffect() is None
    theme._EFFECTS_FILTER.eventFilter(button, QEvent(QEvent.Type.Enter))
    glow = button.graphicsEffect()
    assert glow is not None and glow.offset().y() == 0
    assert glow.color().name().upper() == theme.ACCENT.upper()
    theme._EFFECTS_FILTER.eventFilter(button, QEvent(QEvent.Type.Leave))
    assert button.graphicsEffect() is None
    # a coloured button: its shadow becomes a glow, and back
    primary = widgets.button("ذخیره", variant="primary")
    primary.show()
    admin_qapp.processEvents()
    effect = primary.graphicsEffect()
    assert effect is not None
    theme._EFFECTS_FILTER.eventFilter(primary, QEvent(QEvent.Type.Enter))
    assert effect.color().name().upper() == theme.ACCENT.upper()
    theme._EFFECTS_FILTER.eventFilter(primary, QEvent(QEvent.Type.Leave))
    assert effect.color().name().upper() == theme.SHADOW.upper()
    button.close()
    primary.close()


def test_keep_together():
    text = widgets.keep_together("مریم حسینی (کد شخص ۴) در «hesab5 t» — ۳۶ دقیقه")
    assert "(کد\u00a0شخص\u00a0۴)" in text
    assert "«hesab5\u00a0t»" in text
    assert "۳۶\u00a0دقیقه" in text
    assert "مریم حسینی" in text                          # ordinary words still wrap
    label = widgets.label("مشتری (کد شخص ۴)", wrap=True)
    assert "\u00a0" in label.text()
    assert "\u00a0" not in widgets.label("مشتری (کد شخص ۴)").text()


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
