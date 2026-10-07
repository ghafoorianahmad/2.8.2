"""تقویم شمسی: انتخابگر تاریخ که هیچ عدد و ماه میلادی نشان نمی‌دهد."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..persian import (
    PERSIAN_MONTHS,
    gregorian_to_jalali,
    jalali_to_gregorian,
    to_persian_digits,
)
from . import theme, widgets


class ShamsiDateEdit(QWidget):
    """A Jalali date selector built from three Persian-friendly inputs."""

    date_changed = Signal(object)  # datetime.date

    def __init__(self, initial: date | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._current = initial or date.today()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.day_combo = QComboBox()
        self.month_combo = QComboBox()
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1380, 1450)
        self.year_spin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.year_spin.setMinimumWidth(90)
        self.year_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

        self.month_combo.addItems(PERSIAN_MONTHS)

        for widget, width in ((self.day_combo, 70), (self.month_combo, 110), (self.year_spin, 92)):
            widget.setMinimumWidth(width)

        # RTL order: year (right), month, day (left) — matching Persian reading.
        layout.addWidget(self.year_spin)
        layout.addWidget(self.month_combo)
        layout.addWidget(self.day_combo)

        self._syncing = False
        self.day_combo.currentIndexChanged.connect(self._on_changed)
        self.month_combo.currentIndexChanged.connect(self._on_changed)
        self.year_spin.valueChanged.connect(self._on_changed)
        self.set_date(self._current)

    # ---- api -------------------------------------------------------------
    def date(self) -> date:
        return self._current

    def set_date(self, value: date) -> None:
        jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
        self._syncing = True
        try:
            self.year_spin.setValue(jy)
            self.month_combo.setCurrentIndex(jm - 1)
            self._fill_days(jy, jm)
            self.day_combo.setCurrentIndex(min(jd, self.day_combo.count()) - 1)
        finally:
            self._syncing = False
        self._current = value

    def _fill_days(self, jy: int, jm: int) -> None:
        length = _month_length(jy, jm)
        previous = self.day_combo.currentIndex()
        self.day_combo.blockSignals(True)
        self.day_combo.clear()
        self.day_combo.addItems([to_persian_digits(d) for d in range(1, length + 1)])
        self.day_combo.setCurrentIndex(min(previous, length - 1) if previous >= 0 else 0)
        self.day_combo.blockSignals(False)

    def _on_changed(self, _value: int = 0) -> None:
        if self._syncing:
            return
        jy = int(self.year_spin.value())
        jm = int(self.month_combo.currentIndex()) + 1
        self._syncing = True
        try:
            self._fill_days(jy, jm)
        finally:
            self._syncing = False
        jd = int(self.day_combo.currentIndex()) + 1
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        self._current = date(gy, gm, gd)
        self.date_changed.emit(self._current)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        for widget in (self.day_combo, self.month_combo, self.year_spin):
            widget.setEnabled(enabled)


def _labelled(text: str, field: QWidget) -> QWidget:
    """A caption and its field kept together when a flow layout wraps."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(widgets.label(text))
    row.addWidget(field)
    return holder


class ShamsiRangePicker(QWidget):
    """From/To Shamsi range with quick presets."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        today = date.today()

        layout = widgets.FlowLayout(self, spacing=10)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem("امروز", "today")
        self.preset_combo.addItem("۷ روز گذشته", "week")
        self.preset_combo.addItem("۳۰ روز گذشته", "month30")
        self.preset_combo.addItem("این ماه شمسی", "shamsi_month")
        self.preset_combo.addItem("بازهٔ دلخواه", "custom")
        self.preset_combo.setMinimumWidth(150)
        layout.addWidget(_labelled("بازه:", self.preset_combo))

        self.from_edit = ShamsiDateEdit(today - timedelta(days=29))
        layout.addWidget(_labelled("از:", self.from_edit))

        self.to_edit = ShamsiDateEdit(today)
        layout.addWidget(_labelled("تا:", self.to_edit))

        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        self.from_edit.date_changed.connect(lambda _d: self._emit())
        self.to_edit.date_changed.connect(lambda _d: self._emit())
        self._apply_preset()

    # ---- api -------------------------------------------------------------
    def range(self) -> tuple[date, date]:
        return self.from_edit.date(), self.to_edit.date()

    def from_date(self) -> date:
        return self.from_edit.date()

    def to_date(self) -> date:
        return self.to_edit.date()

    def _emit(self) -> None:
        self.changed.emit()

    def _apply_preset(self) -> None:
        key = self.preset_combo.currentData()
        today = date.today()
        if key == "today":
            self.from_edit.set_date(today)
            self.to_edit.set_date(today)
        elif key == "week":
            self.from_edit.set_date(today - timedelta(days=7))
            self.to_edit.set_date(today)
        elif key == "month30":
            self.from_edit.set_date(today - timedelta(days=30))
            self.to_edit.set_date(today)
        elif key == "shamsi_month":
            jy, jm, _jd = gregorian_to_jalali(today.year, today.month, today.day)
            first = date(*jalali_to_gregorian(jy, jm, 1))
            self.from_edit.set_date(first)
            self.to_edit.set_date(today)
        self.changed.emit()


def _month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    # Esfand: 30 in a leap year, else 29.
    return 30 if _is_leap_jalali(jy) else 29


def _is_leap_jalali(jy: int) -> bool:
    """Standard 33-year cycle leap rule used by the Jalali calendar."""
    return ((jy + 12) % 33) % 4 == 1
