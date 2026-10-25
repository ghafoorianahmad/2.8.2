"""v2.8.2: find text that does not fit (cut badges, buttons, labels, headers).

Renders every page (as «مدیر» and as «کاربر فروش», at two window widths) and
the main dialogs against a fake shopapi, then checks every visible widget that
shows one line of text: its width must be at least what its text needs.
v2.9.0: in every look (3 palettes × light / dark / follow Windows).
v2.9.3: every screen of ``audit_screens`` (all dialogs, sign-in, wizards).
Exits with 1 and a list when something is cut.

    python scripts/text_fit_audit.py            (every look)
    python scripts/text_fit_audit.py --quick    (the default look only)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtWidgets import (QCheckBox, QLabel, QPushButton, QRadioButton,  # noqa: E402
                               QTableWidget, QWidget)

import audit_screens as screens  # noqa: E402

SLACK = 2


def _single_line_text(widget) -> str:
    text = widget.text() if hasattr(widget, "text") else ""
    return str(text or "").replace("&", "")


def _drawn_width(label: QLabel) -> int:
    """Text width as drawn (bold when the style sheet says so) + padding + margins:
    a pill's sizeHint does not always include its style-sheet padding."""
    import re

    from PySide6.QtGui import QFont, QFontMetrics

    font = QFont(label.font())
    sheet = label.styleSheet() or ""
    if re.search(r"font-weight:\s*(600|700|bold)", sheet):
        font.setBold(True)
    pad = 0
    match = re.search(r"padding:\s*(\d+)px(?:\s+(\d+)px)?", sheet)
    if match:
        pad = 2 * int(match.group(2) or match.group(1))
    margins = label.contentsMargins()
    # Qt reports a style-sheet padding as contents margins as well: count it once
    extra = pad if pad else margins.left() + margins.right()
    return QFontMetrics(font).horizontalAdvance(label.text()) + extra


def problems_in(root: QWidget, where: str) -> list[str]:
    out: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisibleTo(root) or widget.width() <= 0:
            continue
        name = f"{where} › {type(widget).__name__}"
        if type(widget).__name__ == "_FitScrollArea" and widget.horizontalScrollBar().isVisible():
            # v2.9.3: a dialog whose content is wider than the dialog (a side scroll
            # bar hides the left part: the order dialog's quantity / price columns)
            out.append(f"{where}: content {widget.widget().minimumSizeHint().width()}px wider "
                       f"than the dialog ({widget.viewport().width()}px)")
            continue
        if isinstance(widget, QLabel):
            if widget.wordWrap() or not widget.text() or widget.pixmap() is not None and \
                    not widget.pixmap().isNull():
                continue
            if "<" in widget.text():          # rich text
                continue
            need = max(widget.sizeHint().width(), _drawn_width(widget))
            if need > widget.width() + SLACK:
                out.append(f"{name} «{widget.text()}» {widget.width()} < {need}")
        elif isinstance(widget, (QPushButton, QCheckBox, QRadioButton)):
            text = _single_line_text(widget)
            if not text.strip():
                continue
            need = widget.sizeHint().width()
            if need > widget.width() + SLACK:
                out.append(f"{name} «{text.strip()}» {widget.width()} < {need}")
        elif isinstance(widget, QTableWidget):
            header = widget.horizontalHeader()
            metrics = header.fontMetrics()
            for column in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(column)
                text = item.text() if item is not None else ""
                need = metrics.horizontalAdvance(text) + 24
                if not header.isSectionHidden(column) and header.sectionSize(column) < need:
                    out.append(f"{where} › header «{text}» {header.sectionSize(column)} < {need}")
    return out


def audit_look(app, tmp: Path, look: tuple[str, str, str]) -> list[str]:
    """v2.9.3: every screen of ``audit_screens`` (every page for both roles and
    widths, every dialog, the sign-in window and the setup wizards)."""
    tag = screens.apply_look(app, look)
    found: list[str] = []
    for where, widget in screens.iter_screens(app, tmp, tag=tag):
        found += problems_in(widget, where)
    found += screens.BUILD_PROBLEMS
    screens.BUILD_PROBLEMS.clear()
    return found


def main() -> int:
    """``--all`` (default): every look; ``--quick``: the default look only."""
    app = screens.app_instance()
    looks = screens.looks_from_argv(sys.argv)
    found: list[str] = []
    for look in looks:
        with tempfile.TemporaryDirectory() as tmp:
            problems = audit_look(app, Path(tmp), look)
        print(f"{look[0]:8} {look[1]:6} {look[2]:6}: {len(set(problems))} cut texts", flush=True)
        found += problems
    unique = sorted(set(found))
    for line in unique:
        print(line)
    print(f"{len(unique)} cut texts in {len(looks)} looks")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
