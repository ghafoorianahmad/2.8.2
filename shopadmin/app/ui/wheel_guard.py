"""v2.18.2 the mouse wheel only scrolls the page.

A spin box, combo box, date picker, slider or tab bar takes the wheel only when the user has clicked
into it first. One application filter, so a new page cannot forget it: the ignored event goes on to
the parent and so to the scroll area around the control.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QComboBox, QScrollBar, QTabBar

GUARDED = (QAbstractSpinBox, QComboBox, QAbstractSlider, QTabBar)


def _guarded(widget: object) -> bool:
    return isinstance(widget, GUARDED) and not isinstance(widget, QScrollBar)


class _WheelGuard(QObject):
    def eventFilter(self, watched, event):  # noqa: N802 - Qt naming
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            if _guarded(watched) and not watched.hasFocus():
                event.ignore()
                return True
        elif kind == QEvent.Type.Polish and _guarded(watched):
            # Qt would give these the focus on the wheel itself, before this filter looks
            if watched.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                watched.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return False


_guard: _WheelGuard | None = None


def install_wheel_guard(app) -> None:
    global _guard
    if _guard is None:
        _guard = _WheelGuard()
        app.installEventFilter(_guard)
