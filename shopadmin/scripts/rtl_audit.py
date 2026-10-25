"""v2.9.3: right-to-left audit of every screen (like ``text_fit_audit.py``).

Every page (as «مدیر» and «کاربر فروش», wide and narrow), every dialog, the
sign-in window and the setup wizards, in every look, are checked:

* every text box, multi-line box, combo box, table, list and label is
  right-to-left; a multi-line box has a right-to-left document too (an empty
  box starts on the right, a paragraph that begins with a Latin word keeps the
  Persian word order);
* only code fields (card, Sheba, account, IP, URL, proxy, user name, password)
  are left-to-right, and only when marked so on purpose (``rtl.mark_ltr``); a
  field that holds or asks for such a code must be left-to-right;
* Persian text that starts with a Latin word («ahmad سفارش را لغو کرد») has a
  right-to-left mark in front (``rtl.bidi``), or its words come out in the
  wrong order, in labels, buttons and read-only boxes (table and list cells are
  always laid out right-to-left by Qt).

Exits with 1 and a list when something is wrong.

    python scripts/rtl_audit.py            (every look)
    python scripts/rtl_audit.py --quick    (the default look only)
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import audit_screens as screens
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
                               QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QWidget)

from app.ui import rtl

RTL = Qt.LayoutDirection.RightToLeft
#: what only a code field holds: an address, a card / Sheba / account number, a link
_CODE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://\S*|tg://\S+|t\.me/\S+|\\\\\S+|[A-Za-z]:\\\S*"
    r"|\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?|[\w.-]+\.\w{2,}(?::\d+)?(?:/\S*)?"
    r"|IR[\d\s-]{6,}|[\d\s-]{12,})$", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def looks_like_code(text: str) -> bool:
    value = str(text or "").strip()
    if not value or rtl.has_persian(value):
        return False
    return bool(_CODE.match(value))


def _plain(text: str) -> str:
    return _TAGS.sub("", str(text or "")).replace("&nbsp;", " ")


def _name(widget: QWidget) -> str:
    name = type(widget).__name__
    if widget.objectName():
        name += f"#{widget.objectName()}"
    return name


def _mixed(where: str, widget: QWidget, text: str) -> list[str]:
    if rtl.needs_rlm(text):
        short = text.replace("\n", " ⏎ ")[:70]
        return [f"{where} › {_name(widget)}: mixed text without a right-to-left mark «{short}»"]
    return []


def problems_in(root: QWidget, where: str) -> list[str]:
    out: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisibleTo(root) and widget is not root:
            continue
        marked = rtl.is_marked_ltr(widget)
        direction = widget.layoutDirection()
        name = f"{where} › {_name(widget)}"
        if isinstance(widget, QLineEdit):
            if isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
                continue                 # the box itself is checked
            text = widget.text() if widget.echoMode() == QLineEdit.EchoMode.Normal else ""
            code = bool(widget.inputMask()) or looks_like_code(widget.placeholderText()) or \
                looks_like_code(text)
            if direction != RTL and not marked:
                out.append(f"{name}: left-to-right but not marked as a code field "
                           f"(«{widget.placeholderText() or text}»)")
            elif direction == RTL and code:
                out.append(f"{name}: a code field («{widget.placeholderText() or text}») must be "
                           "left-to-right (rtl.mark_ltr)")
            if widget.isReadOnly() and direction == RTL:
                out += _mixed(where, widget, text)
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            if marked:
                continue
            if direction != RTL:
                out.append(f"{name}: multi-line box is left-to-right")
            elif not rtl.document_is_rtl(widget):
                out.append(f"{name}: multi-line box without a right-to-left document "
                           f"(«{widget.placeholderText()[:40]}»)")
        elif isinstance(widget, QAbstractSpinBox):
            continue                     # numbers: either direction reads the same
        elif isinstance(widget, QComboBox):
            if direction != RTL and not marked:
                out.append(f"{name}: combo box is left-to-right")
            out += _mixed(where, widget, widget.currentText())
        elif isinstance(widget, QAbstractItemView):
            if isinstance(widget.parentWidget(), QComboBox) or widget.parentWidget() is None:
                continue
            if direction != RTL and not marked:
                out.append(f"{name}: table / list is left-to-right")
        elif isinstance(widget, QLabel):
            text = widget.text()
            if not text or (widget.pixmap() is not None and not widget.pixmap().isNull()):
                continue
            plain = _plain(text) if widget.textFormat() != Qt.TextFormat.PlainText and "<" in text \
                else text
            if direction != RTL and not marked and rtl.has_persian(plain):
                out.append(f"{name}: Persian label is left-to-right «{plain[:50]}»")
            if direction == RTL:
                out += _mixed(where, widget, plain)
        elif isinstance(widget, QAbstractButton):
            if direction == RTL:
                out += _mixed(where, widget, widget.text().replace("&", ""))
    return out


def audit_look(app, tmp: Path, look) -> list[str]:
    tag = screens.apply_look(app, look)
    found: list[str] = []
    for where, widget in screens.iter_screens(app, tmp, tag=tag):
        found += problems_in(widget, where)
    found += screens.BUILD_PROBLEMS
    screens.BUILD_PROBLEMS.clear()
    return found


def main() -> int:
    app = screens.app_instance()
    looks = screens.looks_from_argv(sys.argv)
    found: list[str] = []
    for look in looks:
        with tempfile.TemporaryDirectory() as tmp:
            problems = audit_look(app, Path(tmp), look)
        print(f"{look[0]:8} {look[1]:6} {look[2]:6}: {len(set(problems))} RTL problems", flush=True)
        found += problems
    # the same widget in another look is the same problem
    unique = sorted({re.sub(r"^\[[^\]]+\] ", "", line) for line in found})
    for line in unique:
        print(line)
    print(f"{len(unique)} RTL problems in {len(looks)} looks")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
