"""v2.15.0: ShopAdmin's buttons next to the live site's («مشخصات» / «ثبت سفارش»),
in every look, at rest / hovered / pressed - real widgets with the real theme
(and the «جلوه‌ها» glow), drawn on a card like the site's product card.

    python scripts/button_gallery.py <output_dir> <site_light.png> <site_dark.png>

Writes ``gallery_<palette>_<mode>_<effects>.png`` per look and ``gallery_all.png``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_screens as screens  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,  # noqa: E402
                               QLabel, QVBoxLayout, QWidget)

from app.ui import theme, widgets  # noqa: E402

STATES = (("rest", "عادی"), ("hover", "زیر نشانگر (درخشش)"), ("pressed", "فشرده"))


def card(state: str) -> QFrame:
    panel = QFrame()
    panel.setObjectName("Card")
    row = QHBoxLayout(panel)
    row.setContentsMargins(18, 22, 18, 26)
    row.setSpacing(10)
    primary = widgets.button("ثبت سفارش", variant="primary")
    normal = widgets.button("مشخصات")
    for b in (primary, normal):
        b.setMinimumWidth(128)
        row.addWidget(b)
    panel._buttons = (primary, normal)  # noqa: SLF001
    panel._state = state  # noqa: SLF001
    return panel


def set_state(app: QApplication, panel: QFrame) -> None:
    for b in panel._buttons:  # noqa: SLF001
        if panel._state in ("hover", "pressed"):  # noqa: SLF001
            b.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
            app.sendEvent(b, QEvent(QEvent.Type.Enter))
        if panel._state == "pressed":  # noqa: SLF001
            b.setDown(True)
        b.style().unpolish(b)
        b.style().polish(b)
        b.update()


def look_sheet(app, look, site: dict[str, QPixmap]) -> QWidget:
    tag = screens.apply_look(app, look)
    root = QWidget()
    root.setObjectName("WindowRoot")
    root.setStyleSheet(f"QWidget#WindowRoot {{ background: {theme.BACKGROUND}; }}")
    root.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    grid = QGridLayout(root)
    grid.setContentsMargins(18, 14, 18, 14)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(6)
    grid.addWidget(widgets.label(f"ظاهر {tag}", bold=True), 0, 0, 1, 4)
    site_label = QLabel()
    site_label.setPixmap(site["dark" if theme.MODE == "dark" else "light"])
    grid.addWidget(widgets.label("سایت زنده (asrertebatat2.ir)", name="Muted"), 1, 0)
    grid.addWidget(site_label, 2, 0, Qt.AlignmentFlag.AlignTop)
    panels = []
    for column, (state, caption) in enumerate(STATES, start=1):
        grid.addWidget(widgets.label("ShopAdmin — " + caption, name="Muted"), 1, column)
        panel = card(state)
        panels.append(panel)
        grid.addWidget(panel, 2, column, Qt.AlignmentFlag.AlignTop)
    root.show()
    for _ in range(5):
        app.processEvents()
    for panel in panels:
        set_state(app, panel)
    for _ in range(40):
        app.processEvents()
    import time

    time.sleep(0.3)               # the glow animation (≤ 160 ms) finishes
    for _ in range(20):
        app.processEvents()
    return root


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    site = {"light": QPixmap(sys.argv[2]), "dark": QPixmap(sys.argv[3])}
    shots = []
    for look in screens.LOOKS:
        root = look_sheet(app, look, site)
        palette, mode, effects = look
        path = out / f"gallery_{palette}_{mode}_{effects}.png"
        root.grab().save(str(path))
        shots.append(path)
        print("wrote", path.name, flush=True)
        root.close()
        root.deleteLater()
        app.processEvents()
    from PIL import Image

    images = [Image.open(p).convert("RGB") for p in shots]
    width = max(i.width for i in images)
    sheet = Image.new("RGB", (width, sum(i.height for i in images)), "white")
    y = 0
    for image in images:
        sheet.paste(image, (width - image.width, y))
        y += image.height
    sheet.save(out / "gallery_all.png")
    print("wrote gallery_all.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
