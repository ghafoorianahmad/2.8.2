"""v2.8.2: find text that does not fit (cut badges, buttons, labels, headers).

Renders every page (as «مدیر» and as «کاربر فروش», at two window widths) and
the main dialogs against a fake shopapi, then checks every visible widget that
shows one line of text: its width must be at least what its text needs.
v2.9.0: in every look (3 palettes × light / dark / follow Windows).
Exits with 1 and a list when something is cut.

    python scripts/text_fit_audit.py            (every look)
    python scripts/text_fit_audit.py --quick    (the default look only)
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


#: v2.9.0: every look (palette × light / dark / follow Windows); «جلوه‌ها» alternate
#: (shadows and gradients never change a widget's size, but both are exercised).
LOOKS = [(palette, mode, "full" if index % 2 == 0 else "simple")
         for index, (palette, mode) in enumerate(
             (p, m) for p in theme.PALETTE_NAMES for m in theme.THEME_MODES)]


def audit_look(app, tmp: Path, look: tuple[str, str, str]) -> list[str]:
    palette, mode, effects = look
    theme.apply_theme(app, mode, palette=palette, effects=effects)
    tag = f"[{palette}/{mode}/{effects}]"
    from app.ui.main_window import NAV_ITEMS, MainWindow

    found: list[str] = []
    context, store, fake = rs.build_context(tmp)
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
            found += problems_in(window, f"{tag} {role} {width} top/sidebar")
            for key, _text, _icon, _perm in NAV_ITEMS:
                if key not in window._pages:
                    continue
                window.navigate(key)
                rs.settle(app, 10)
                found += problems_in(window._pages[key], f"{tag} {role} {width} {key}")
            window.close()
            window.deleteLater()            # the next look restyles only live widgets
    # ---- dialogs -------------------------------------------------------------
    context.principal = replace(context.principal, role="super_admin", permissions=None)
    from app.ui import widgets
    from app.ui.main_window import NotificationDialog
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
    # v2.9.0: «اعلان‌ها و ظاهر» (option cards) and the Telegram login (server only)
    dialogs.append(("notifications and look", NotificationDialog(context)))
    try:
        from app.ui.telegram_login import TelegramLoginDialog
    except ImportError:
        TelegramLoginDialog = None
    if TelegramLoginDialog is not None:
        login = TelegramLoginDialog(None)
        dialogs.append(("telegram login", login))
        for step in (login.STEP_CODE, login.STEP_PASSWORD, login.STEP_DONE):
            other = TelegramLoginDialog(None)
            other._go(step)
            dialogs.append((f"telegram login step {step}", other))
    for request in list(getattr(fake, "item_requests", []))[:2]:
        dialogs.append((f"request {request.get('id')}", ItemRequestDialog(context, request)))
    for name, dialog in dialogs:
        widgets.make_responsive(dialog)
        dialog.show()
        rs.settle(app, 10)
        found += problems_in(dialog, f"{tag} dialog {name}")
        dialog.close()
        dialog.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    store.close()
    return found


def main() -> int:
    """``--all`` (default): every look; ``--quick``: the default look only."""
    app = QApplication.instance() or QApplication(sys.argv)
    looks = [("ocean", "light", "full")] if "--quick" in sys.argv else LOOKS
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
