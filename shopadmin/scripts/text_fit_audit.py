"""v2.8.2: find text that does not fit (cut badges, buttons, labels, headers).

Renders every page (as «مدیر» and as «کاربر فروش», at two window widths) and
the main dialogs against a fake shopapi, then checks every visible widget that
shows one line of text: its width must be at least what its text needs.
Exits with 1 and a list when something is cut.

    python scripts/text_fit_audit.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QHeaderView,  # noqa: E402
                               QLabel, QPushButton, QRadioButton, QTableWidget, QWidget)

import render_screens as rs  # noqa: E402
from app import permissions as perms  # noqa: E402
from app.statuses import ROLE_OPERATOR  # noqa: E402
from app.ui import theme  # noqa: E402

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


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_theme(app)
    from app.ui.main_window import NAV_ITEMS, MainWindow

    found: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        opened: list = []
        context, store, fake = rs.build_context(Path(tmp))
        sales_perms = perms.client_permissions(sorted(perms.SALES_SERVER_PERMISSIONS))
        for role in ("manager", "sales"):
            if role == "sales":
                context.principal = replace(context.principal, role=ROLE_OPERATOR,
                                            permissions=sales_perms)
            for width, height in ((1360, 840), (1000, 700)):
                window = MainWindow(context)
                window.resize(width, height)
                window.show()
                rs.settle(app, 10)
                found += problems_in(window, f"{role} {width} top/sidebar")
                for key, _text, _icon, _perm in NAV_ITEMS:
                    if key not in window._pages:
                        continue
                    window.navigate(key)
                    rs.settle(app, 10)
                    found += problems_in(window._pages[key], f"{role} {width} {key}")
                window.close()
        # ---- dialogs -------------------------------------------------------------
        context.principal = replace(context.principal, role="super_admin", permissions=None)
        from app.ui.pages.item_requests import ItemRequestDialog
        from app.ui.pages.orders import OrderDetailDialog, PaymentInfoDialog, ShipDialog
        from app.ui.pages.users import UserFormDialog

        dialogs = []
        orders = [o for o in getattr(fake, "orders", []) if isinstance(o, dict)]
        for order in orders[:3]:
            dialogs.append((f"order {order.get('id')}", OrderDetailDialog(context, order)))
        if orders:
            dialogs.append(("payment", PaymentInfoDialog(None, context, orders[0])))
        dialogs.append(("ship", ShipDialog(None, "۱۲")))
        dialogs.append(("user form", UserFormDialog(context, None)))
        for request in list(getattr(fake, "item_requests", []))[:2]:
            dialogs.append((f"request {request.get('id')}", ItemRequestDialog(context, request)))
        for name, dialog in dialogs:
            from app.ui import widgets

            widgets.make_responsive(dialog)
            dialog.show()
            rs.settle(app, 10)
            found += problems_in(dialog, f"dialog {name}")
            dialog.close()
        for item in opened:
            item.close()
        store.close()
    unique = sorted(set(found))
    for line in unique:
        print(line)
    print(f"{len(unique)} cut texts")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
