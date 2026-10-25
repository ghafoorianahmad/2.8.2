"""v2.9.3: a screenshot of every screen the audits check (``audit_screens``).

    python scripts/render_dialogs.py [output_dir] [--all-looks]

Default: the default look, every dialog, the sign-in window, the wizards and the
pages as «مدیر» (wide); ``--all-looks`` adds the dark look of every palette.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import audit_screens as screens
from PySide6.QtWidgets import QScrollArea

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else ROOT / "docs" / "screens_2.9.3"
    out.mkdir(parents=True, exist_ok=True)
    app = screens.app_instance()
    looks = [screens.DEFAULT_LOOK]
    if "--all-looks" in sys.argv:
        looks += [(palette, "dark", "full") for palette in screens.theme.PALETTE_NAMES]
    count = 0
    for look in looks:
        tag = screens.apply_look(app, look)
        with tempfile.TemporaryDirectory() as tmp:
            for where, widget in screens.iter_screens(app, Path(tmp), roles=("manager",),
                                                      sizes=((1360, 840),), tag=tag):
                name = re.sub(r"[^\w.-]+", "_", where.strip()).strip("_")
                if "dialog" in where:
                    # the whole dialog in one picture (no part hidden below the scroll)
                    body = widget.findChild(QScrollArea)
                    if body is not None and body.widget() is not None:
                        extra = body.widget().sizeHint().height() - body.viewport().height()
                        if extra > 0:
                            widget.resize(widget.width(), widget.height() + extra + 8)
                            screens.settle(app, 4)
                widget.grab().save(str(out / f"{name}.png"), "PNG")
                count += 1
        for line in screens.BUILD_PROBLEMS:
            print(line)
        screens.BUILD_PROBLEMS.clear()
    print(f"{count} screenshots in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
