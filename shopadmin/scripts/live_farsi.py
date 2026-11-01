"""v2.16.0: «فارسی‌سازی توضیحات» once on THIS computer's accessories, in the REAL
ShopAdmin (this source tree, the saved session of this Windows user, as live_shot.py).

Usage:
    python scripts/live_farsi.py <output_dir> [--group powerbank] [--dry]

1. a backup of the site data (``site_before_farsi.zip`` next to the site data folder;
   the texts are also kept 48 hours inside the data for «برگرداندن فارسی‌سازی»);
2. «سایت» › «کالاها» › the group is chosen and grabbed (``farsi_1_before.png``);
3. the «فارسی‌سازی توضیحات» button's own handler runs with every item of that
   branch (its question is answered «فارسی‌سازی» and printed);
4. the page and the «واژه‌نامه…» window are grabbed (``farsi_2_after.png``,
   ``farsi_3_words.png``).
``--dry`` stops after step 2 (nothing is changed).
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
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    group = argv[argv.index("--group") + 1] if "--group" in argv else "powerbank"
    from app import main as shop_main
    from app.ui import theme, widgets
    from app.ui.pages import site as site_page
    from app.ui.site_dialogs import WordsDialog

    app = QApplication(argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    shop_main.prefer_fusion_style(app)
    theme.apply_theme(app)
    controller = shop_main.ShopAdminApp(app)
    controller.start()
    state = {"tries": 0}

    def step1() -> None:
        window = controller.main_window
        if window is None or not window.isVisible():
            state["tries"] += 1
            if state["tries"] > 60:
                print("main window did not open (signed out?)")
                app.exit(2)
                return
            QTimer.singleShot(1000, step1)
            return
        window.showNormal()
        window.resize(1360, 860)
        window.navigate("site")
        QTimer.singleShot(4000, lambda: step2(window))

    def step2(window) -> None:
        page = window._pages["site"]
        node = next((n for n in page._tree_items()
                     if tuple(n.data(0, Qt.ItemDataRole.UserRole) or ()) == (site_page.NODE_GROUP, group)),
                    None)
        if node is None:
            print(f"no «{group}» branch")
            app.exit(3)
            return
        page.tree.setCurrentItem(node)
        app.processEvents()
        window.grab().save(str(out / "farsi_1_before.png"))
        print(f"before: {page.accessories_table.rowCount()} rows")
        if "--dry" in argv:
            app.exit(0)
            return
        # the backup holds this computer's data: next to it, never in the output folder
        backup = page.store.root.parent / "site_before_farsi.zip"
        count = page.store.backup(backup)
        print(f"backup: {count} files -> {backup}")
        asked = []

        def answer(_parent, title, text, **_kw):
            asked.append(f"{title}: {text}")
            return True
        widgets.confirm = answer
        page._farsi()
        print("question:", asked[0] if asked else "(none)")
        app.processEvents()
        QTimer.singleShot(1500, lambda: step3(window, page))

    def step3(window, page) -> None:
        window.grab().save(str(out / "farsi_2_after.png"))
        dialog = WordsDialog(page.store, parent=window)
        dialog.trial.setText("PD 20W Fast Charging")
        dialog.show()
        app.processEvents()

        def grab_words() -> None:
            dialog.grab().save(str(out / "farsi_3_words.png"))
            dialog.reject()
            print(f"undo kept for {page.store.farsi_undo_count()} items")
            app.exit(0)
        QTimer.singleShot(1200, grab_words)

    QTimer.singleShot(3000, step1)
    code = app.exec()
    controller.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
