"""v2.18.2: the wheel, thousands separators, the installments page, the previous-years ledger."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QScrollBar, QSlider, QSpinBox, QTabBar, QWidget

from app.ui.wheel_guard import _WheelGuard, install_wheel_guard


def _wheel(widget: QWidget) -> QWheelEvent:
    event = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                        QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    event.setAccepted(True)
    return event


def test_the_wheel_is_ignored_unless_the_control_has_focus(admin_qapp):
    install_wheel_guard(admin_qapp)
    spin, combo = QSpinBox(), QComboBox()
    spin.setRange(0, 9)
    spin.setValue(5)
    combo.addItems(["الف", "ب", "پ"])
    combo.setCurrentIndex(1)
    for widget in (spin, combo):
        event = _wheel(widget)
        admin_qapp.sendEvent(widget, event)
        assert not event.isAccepted()        # so it goes on to the scroll area
    assert spin.value() == 5 and combo.currentIndex() == 1


def test_a_clicked_control_takes_the_wheel_and_a_scroll_bar_always_does():
    guard = _WheelGuard()

    class Focused(QSpinBox):
        def hasFocus(self):  # noqa: N802 - Qt naming
            return True

    assert guard.eventFilter(Focused(), _wheel(QSpinBox())) is False
    assert guard.eventFilter(QScrollBar(), _wheel(QSpinBox())) is False
    for widget in (QSpinBox(), QComboBox(), QSlider(), QTabBar()):
        assert guard.eventFilter(widget, _wheel(widget)) is True


def test_the_wheel_gives_these_controls_no_focus(admin_qapp):
    install_wheel_guard(admin_qapp)
    spin, combo = QSpinBox(), QComboBox()
    for widget in (spin, combo):
        widget.ensurePolished()
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
