"""v2.15.0: screenshots of the REAL running ShopAdmin (this source tree) against the
server running on this computer - the same start as ShopAdmin.exe (client edition:
the saved session of this Windows user, no password typed by this script).

Usage:
    python scripts/live_shot.py <output_dir> <page>[,<page>...] [--look <palette>:<mode>]

For each page the main window is shown, the page opened and the window grabbed
(``<page>.png``). Read-only: nothing is clicked or saved.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SHOPADMIN_EDITION", "client")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main(argv: list[str]) -> int:
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    pages = [p for p in argv[2].split(",") if p]
    from app import main as shop_main
    from app.ui import theme

    app = QApplication(argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    shop_main.prefer_fusion_style(app)
    theme.apply_theme(app)
    controller = shop_main.ShopAdminApp(app)
    controller.start()
    state = {"tries": 0, "index": 0}

    def shoot() -> None:
        window = controller.main_window
        if window is None or not window.isVisible():
            state["tries"] += 1
            if state["tries"] > 60:
                print("main window did not open (signed out?)")
                app.exit(2)
                return
            QTimer.singleShot(1000, shoot)
            return
        if state["index"] >= len(pages):
            app.exit(0)
            return
        page = pages[state["index"]]
        window.showNormal()
        window.resize(1360, 860)
        window.navigate(page)

        def grab() -> None:
            path = out / f"{page}.png"
            window.grab().save(str(path))
            print(f"saved {path} banner={window.banner.isVisible()} "
                  f"text={window.banner_label.text()!r}")
            state["index"] += 1
            QTimer.singleShot(200, shoot)
        QTimer.singleShot(6000, grab)

    QTimer.singleShot(3000, shoot)
    code = app.exec()
    controller.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
