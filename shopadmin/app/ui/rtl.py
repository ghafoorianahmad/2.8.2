"""Right-to-left helpers (v2.8.0).

In a right-to-left widget Qt mirrors ``AlignRight`` to the LEFT edge (it swaps
left and right unless ``AlignAbsolute`` is set). Until v2.7.0 tables, labels and
form captions used plain ``AlignRight`` and so sat on the left. ``RIGHT`` is the
real right edge.

Text without Persian letters (codes, part numbers, paths, URLs, usernames) is
shown left-to-right inside the right-aligned cell, so «C:\\Data» or «ZAA-256»
never comes out scrambled.

v2.9.3 (``scripts/rtl_audit.py`` checks every screen):

* every text box, multi-line box, table and list is right-to-left; a multi-line
  box gets a right-to-left *document* too (``rtl_text``): an empty
  QPlainTextEdit used to start left-to-right, and a paragraph that began with a
  Latin word was laid out left-to-right («پیام به مشتری»);
* only code fields (card, Sheba, account, IP, URL, proxy, user name, password)
  are left-to-right, and they say so (``mark_ltr``) so the audit can tell a
  deliberate one from a mistake;
* Persian text that starts with a Latin word («ahmad سفارش را لغو کرد») gets a
  RIGHT-TO-LEFT MARK first (``bidi``), so its word order never flips.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt

#: The physical right edge (never mirrored).
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
#: The physical left edge (code fields).
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute

_PERSIAN = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN = re.compile(r"[A-Za-z]")
#: the first strong character: a Persian / Arabic letter or a Latin letter
_STRONG = re.compile(r"[A-Za-z\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
#: LEFT-TO-RIGHT EMBEDDING ... POP DIRECTIONAL FORMATTING
LRE, PDF = "\u202a", "\u202c"
#: RIGHT-TO-LEFT MARK, and the other marks that already fix a direction
RLM = "\u200f"
_MARKS = ("\u200e", "\u200f", "\u202a", "\u202b", "\u202d", "\u202e", "\u2066", "\u2067",
          "\u2068")
#: Qt property of a deliberate left-to-right field (``mark_ltr``)
LTR_PROPERTY = "ltrField"


def is_ltr_text(text: str) -> bool:
    """Latin text without any Persian letter (an English name, code, path, URL)."""
    value = str(text or "")
    return bool(_LATIN.search(value)) and not _PERSIAN.search(value)


def has_persian(text: str) -> bool:
    return bool(_PERSIAN.search(str(text or "")))


def starts_latin(text: str) -> bool:
    """The first strong character is a Latin letter (each line counts)."""
    match = _STRONG.search(str(text or ""))
    return bool(match) and bool(_LATIN.match(match.group(0)))


def needs_rlm(text: str) -> bool:
    """Persian text whose first strong letter is Latin and has no mark: shown in
    a right-to-left box without a mark, Qt may lay it out left-to-right and the
    Persian words then come out in the wrong order. Checked line by line."""
    for line in str(text or "").splitlines() or [""]:
        if not has_persian(line) or not _LATIN.search(line):
            continue
        if line.lstrip().startswith(_MARKS):
            continue
        if starts_latin(line):
            return True
    return False


def bidi(text: str) -> str:
    """``text`` ready for a right-to-left widget: LTR-only text is embedded LTR;
    v2.9.3: a Persian line that starts with a Latin word gets an RLM first."""
    value = str(text if text is not None else "")
    if value.startswith(LRE) or not value:
        return value
    if is_ltr_text(value):
        return f"{LRE}{value}{PDF}"
    return fix_mixed(value)


def fix_mixed(text: str) -> str:
    """Only the RLM part of ``bidi``: a Persian line that starts with a Latin word
    gets a RIGHT-TO-LEFT MARK first; any other text is returned unchanged (a
    label lays out a Latin-only text left-to-right by itself)."""
    value = str(text if text is not None else "")
    if not needs_rlm(value):
        return value
    return "\n".join(f"{RLM}{line}" if has_persian(line) and starts_latin(line) and
                     not line.lstrip().startswith(_MARKS) else line
                     for line in value.split("\n"))


def mark_ltr(widget, *, align_left: bool = True):
    """A code field (card, Sheba, account, IP, URL, proxy, user name, password):
    left-to-right on purpose. Returns the widget."""
    widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    widget.setProperty(LTR_PROPERTY, True)
    if align_left and hasattr(widget, "setAlignment") and hasattr(widget, "setEchoMode"):
        widget.setAlignment(LEFT | Qt.AlignmentFlag.AlignVCenter)
    return widget


def is_marked_ltr(widget) -> bool:
    return bool(widget.property(LTR_PROPERTY))


def rtl_text(edit):
    """A QPlainTextEdit / QTextEdit / QTextBrowser that is right-to-left in its
    document as well: an empty box starts on the right, and a paragraph that
    begins with a Latin word keeps the right-to-left order. Returns the edit."""
    from PySide6.QtGui import QTextOption

    edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    document = edit.document()
    option = document.defaultTextOption()
    option.setTextDirection(Qt.LayoutDirection.RightToLeft)
    option.setAlignment(RIGHT)
    document.setDefaultTextOption(option)
    return edit


def document_is_rtl(edit) -> bool:
    option = edit.document().defaultTextOption()
    return option.textDirection() == Qt.LayoutDirection.RightToLeft


class _RtlDefaults:
    """v2.9.3: every multi-line box (QPlainTextEdit / QTextEdit) of the program gets
    a right-to-left document when it is first shown, unless it was marked as a
    left-to-right code / log box (``mark_ltr``). Installed by ``theme.apply_theme``."""

    _filter = None
    #: v2.9.4: more first-polish steps in the same (single) application filter,
    #: e.g. the eye of password fields: one Python call per event, not one each
    hooks: list = []

    @classmethod
    def install(cls, app) -> None:
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

        if cls._filter is not None:
            return

        class Filter(QObject):
            def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
                if event.type() == QEvent.Type.Polish:
                    if isinstance(obj, (QPlainTextEdit, QTextEdit)) and \
                            not is_marked_ltr(obj) and not document_is_rtl(obj):
                        rtl_text(obj)
                    for hook in _RtlDefaults.hooks:
                        hook(obj)
                return False

        cls._filter = Filter()
        app.installEventFilter(cls._filter)


def install_rtl_defaults(app) -> None:
    _RtlDefaults.install(app)


def add_polish_hook(hook) -> None:
    """``hook(widget)`` on every widget's first polish (once per hook)."""
    if hook not in _RtlDefaults.hooks:
        _RtlDefaults.hooks.append(hook)
