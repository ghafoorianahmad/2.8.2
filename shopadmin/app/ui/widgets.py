"""Reusable widgets: cards, badges, table with loading/empty states, toasts.

Every visible string here is Persian and every number is rendered with Persian
digits by the caller (or by the helpers in :mod:`app.persian`).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..persian import to_persian_digits
from . import theme
from .rtl import RIGHT, is_ltr_text

# --------------------------------------------------------------------------
# small building blocks
# --------------------------------------------------------------------------


def label(text: str, *, name: str = "", size: int | None = None, bold: bool = False,
          color: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if size is not None or bold or color:
        font = widget.font()
        if size is not None:
            font.setPointSize(size)
        font.setBold(bold or font.bold())
        widget.setFont(font)
        if color:
            widget.setStyleSheet(f"color: {color};")
    widget.setWordWrap(wrap)
    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    widget.setAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
    return widget


def add_shadow(widget: QWidget, *, blur: int = 24, dy: int = 4, alpha: int = 28) -> QWidget:
    """Soft drop shadow for a card. Use on small cards only: a graphics effect
    re-renders its children, so it must not wrap big tables."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)
    return widget


def page_title(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(label(title, name="PageTitle"))
    if subtitle:
        layout.addWidget(label(subtitle, name="PageSubtitle", wrap=True))
    return container


def button(text: str, *, icon_name: str = "", variant: str = "default",
           tooltip: str = "", on_click: Callable[[], None] | None = None) -> QPushButton:
    widget = QPushButton(text)
    if icon_name:
        widget.setIcon(theme.icon(icon_name, 18, _variant_icon_color(variant)))
        widget.setIconSize(QSize(18, 18))
    if variant == "primary":
        widget.setObjectName("Primary")
    elif variant == "success":
        widget.setObjectName("Success")
    elif variant == "danger":
        widget.setObjectName("Danger")
    elif variant == "ghost":
        widget.setObjectName("Ghost")
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    if on_click is not None:
        widget.clicked.connect(lambda: on_click())
    return widget


def _variant_icon_color(variant: str) -> str:
    if variant in ("primary", "success", "danger"):
        return "#FFFFFF"
    if variant == "ghost":
        return theme.TEXT_MUTED
    return theme.TEXT


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
    return line


def vline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-width: 1px;")
    return line


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------
class FlowLayout(QLayout):
    """Lays widgets out in rows and wraps to the next row when the width runs out.

    Right-to-left aware: in an RTL parent the first widget sits on the right.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        rtl = self.parentWidget() is not None and             self.parentWidget().layoutDirection() == Qt.LayoutDirection.RightToLeft
        x, y, row_height = area.x(), area.y(), 0
        row: list[tuple[Any, int, int]] = []

        def flush() -> None:
            if not apply:
                return
            for item, ix, iy in row:
                size = item.sizeHint()
                left = area.x() + area.right() - ix - size.width() + 1 if rtl else ix
                item.setGeometry(QRect(left, iy, size.width(), size.height()))

        for item in self._items:
            size = item.sizeHint()
            if x + size.width() > area.right() + 1 and row_height > 0:
                flush()
                row = []
                x, y, row_height = area.x(), y + row_height + self._space, 0
            row.append((item, x, y))
            x += size.width() + self._space
            row_height = max(row_height, size.height())
        flush()
        return y + row_height - rect.y() + margins.bottom()


class CardGrid(QWidget):
    """Equal-width cards: all in one row when wide, wrapping into 2 / 1 columns when narrow."""

    def __init__(self, min_card_width: int = 250, spacing: int = 14,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[QWidget] = []
        self._min = min_card_width
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        self._columns = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def add_card(self, card: QWidget) -> None:
        self._cards.append(card)
        self._relayout(force=True)

    def columns(self) -> int:
        return self._columns

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._min, 0)

    def _relayout(self, force: bool = False) -> None:
        count = max(1, len(self._cards))
        columns = max(1, min(count, (self.width() or 10_000) // self._min))
        if columns < count:   # prefer an even grid (4 cards -> 2 x 2) over a lonely last card
            even = max((c for c in range(2, columns + 1) if count % c == 0), default=columns)
            columns = even
        if columns == self._columns and not force:
            return
        self._columns = columns
        for card in self._cards:
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self._grid.setColumnStretch(column, 1)
        for column in range(columns, count):
            self._grid.setColumnStretch(column, 0)


class StatCard(QFrame):
    """A large coloured dashboard card."""

    clicked = Signal()

    def __init__(self, title: str, value: str = "—", *, icon_name: str = "info",
                 accent: str = theme.PRIMARY, tint: str = theme.PRIMARY_SOFT,
                 hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._accent = accent
        self.setMinimumHeight(122)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        icon_holder = QLabel()
        icon_holder.setPixmap(theme.icon_pixmap(icon_name, 30, accent))
        icon_holder.setFixedSize(58, 58)
        icon_holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_holder.setStyleSheet(f"background: {tint}; border-radius: 16px;")
        root.addWidget(icon_holder)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        text_column.addWidget(label(title, name="CardTitle", wrap=True))
        self._value_label = label(value, name="CardValue")
        text_column.addWidget(self._value_label)
        self._hint_label = label(hint, name="Faint", wrap=True)
        self._hint_label.setVisible(bool(hint))
        text_column.addWidget(self._hint_label)
        text_column.addStretch(1)
        root.addLayout(text_column, 1)

        self._apply_accent()
        add_shadow(self, blur=18, dy=3, alpha=22)

    def _apply_accent(self) -> None:
        self.setStyleSheet(
            f"QFrame#Card {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_LG}px; border-top: 3px solid {self._accent}; }}"
        )

    def set_value(self, value: str, hint: str = "") -> None:
        self._value_label.setText(to_persian_digits(value))
        if hint:
            self._hint_label.setText(hint)
        self._hint_label.setVisible(bool(hint or self._hint_label.text()))

    def set_loading(self) -> None:
        self._value_label.setText("…")

    def set_error(self) -> None:
        self._value_label.setText("—")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class BarChart(QWidget):
    """Minimal bar chart (label + integer value per bar), painted directly.

    Value labels are drawn above every bar so the chart never relies on colour
    alone; bars use PRIMARY on the white panel (non-text contrast >= 3:1).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self.setMinimumHeight(170)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self._data = list(data)
        self.update()

    def data(self) -> list[tuple[str, int]]:
        return list(self._data)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QColor, QPainter

        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(theme.app_font(9))
        count = len(self._data)
        top_pad, bottom_pad = 22, 24
        slot = self.width() / count
        bar_width = min(46.0, slot * 0.55)
        plot_height = max(10, self.height() - top_pad - bottom_pad)
        peak = max(1, max(value for _, value in self._data))
        base_y = top_pad + plot_height
        painter.setPen(QColor(theme.BORDER))
        painter.drawLine(0, int(base_y), self.width(), int(base_y))
        for index, (text, value) in enumerate(self._data):
            center = slot * (count - index - 0.5)  # RTL: oldest bar on the right
            height = plot_height * value / peak
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.PRIMARY if value else theme.BORDER_STRONG))
            painter.drawRoundedRect(
                int(center - bar_width / 2), int(base_y - max(height, 3)),
                int(bar_width), int(max(height, 3)), 6, 6,
            )
            painter.setPen(QColor(theme.INK))
            painter.drawText(
                int(center - slot / 2), int(base_y - max(height, 3) - 20),
                int(slot), 18, Qt.AlignmentFlag.AlignCenter, to_persian_digits(value),
            )
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                int(center - slot / 2), int(base_y + 4),
                int(slot), 18, Qt.AlignmentFlag.AlignCenter, text,
            )
        painter.end()


class Panel(QFrame):
    """A titled white panel used to group content."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(12)
        if title:
            self.body.addWidget(label(title, name="SectionTitle"))


# --------------------------------------------------------------------------
# status pills
# --------------------------------------------------------------------------
class StatusPill(QLabel):
    def __init__(self, text: str, status: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status, text)

    def set_status(self, status: str, text: str | None = None) -> None:
        foreground, background = theme_status_colors(status)
        if text is not None:
            self.setText(text)
        # sizeHint on a QLabel with a stylesheet padding is unreliable inside a
        # table cell, so reserve the height explicitly and let it grow.
        self.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 11px; "
            f"padding: 4px 12px; font-weight: 600;"
        )
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.adjustSize()


def theme_status_colors(status: str) -> tuple[str, str]:
    from ..statuses import status_colors

    return status_colors(status)


def pill_cell(widget: QWidget) -> QWidget:
    """Wrap a pill so it sits centred inside a table cell with room to breathe."""
    holder = QWidget()
    holder.setMinimumHeight(widget.minimumHeight() + 8 if widget.minimumHeight() else 34)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.addWidget(widget)
    layout.addStretch(1)
    return holder


# --------------------------------------------------------------------------
# search box
# --------------------------------------------------------------------------
class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "جستجو…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(240)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAlignment(RIGHT)
        self.addAction(theme.icon("search", 18, theme.TEXT_FAINT), QLineEdit.ActionPosition.LeadingPosition)


# --------------------------------------------------------------------------
# data table with loading / empty states
# --------------------------------------------------------------------------
class BidiDelegate(QStyledItemDelegate):
    """v2.8.0: a cell whose text has no Persian letter (a code, path, URL, English
    name) is laid out left-to-right; it stays on the right edge (``RIGHT``)."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt naming
        super().initStyleOption(option, index)
        if is_ltr_text(option.text):
            option.direction = Qt.LayoutDirection.LeftToRight


class DataTable(QTableWidget):
    """A read-only table that knows how to show loading and empty states."""

    row_activated = Signal(int)

    #: Object with ``get_setting`` / ``set_setting`` (the Store); set by the app so
    #: column widths survive restarts. ``None`` in tests and before login.
    settings_store: Any = None
    MIN_COLUMN = 72
    MAX_AUTO_COLUMN = 280

    def __init__(self, headers: Sequence[str], *, selectable_rows: bool = False,
                 key: str = "", keep_columns: Iterable[int] = (),
                 parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        self._key = key
        #: v2.6.1: columns never squeezed below their content (dates, short codes)
        self._keep = frozenset(int(c) for c in keep_columns)
        self._sizing = False       # True while we set widths ourselves (not a user drag)
        self._auto_sized = False
        self._user_sized = False   # the user dragged a column, or saved widths were restored
        self._natural: list[int] = []
        self._floor: list[int] = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_widths)
        self.setHorizontalHeaderLabels(list(headers))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
            if selectable_rows
            else QAbstractItemView.SelectionMode.NoSelection
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setItemDelegate(BidiDelegate(self))
        header = self.horizontalHeader()
        # Interactive: the user can drag any column edge; the last column fills the rest.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(self.MIN_COLUMN)
        header.setCascadingSectionResizes(False)
        header.setDefaultAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        header.sectionResized.connect(self._on_section_resized)
        # Long text is cut with an ellipsis (tooltip shows it all); a horizontal
        # scroll bar appears only when the columns really do not fit.
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalHeader().setDefaultSectionSize(46)
        self._headers = list(headers)
        self._restore_widths()

        self._empty_title = "موردی برای نمایش وجود ندارد"
        self._empty_hint = ""
        self._empty_icon = "inbox"
        self._busy = False
        self._empty_widget: QWidget | None = None
        self._busy_widget: QWidget | None = None

        if selectable_rows:
            self.cellClicked.connect(self._emit_row)
            self.doubleClicked.connect(lambda index: self.row_activated.emit(index.row()))

    # ---- column widths ---------------------------------------------------
    def _settings_name(self) -> str:
        return f"table_widths.{self._key}"

    def _restore_widths(self) -> None:
        store = DataTable.settings_store
        if not self._key or store is None:
            return
        try:
            saved = store.get_setting(self._settings_name())
        except Exception:  # noqa: BLE001 - widths are a convenience only
            return
        if isinstance(saved, list) and len(saved) == self.columnCount() \
                and all(isinstance(w, int) and w > 0 for w in saved):
            self._apply_widths(saved)
            self._auto_sized = True   # the user's widths win over automatic sizing
            self._user_sized = True

    def _apply_widths(self, widths: Sequence[int]) -> None:
        self._sizing = True
        try:
            for column, width in enumerate(widths):
                self.setColumnWidth(column, max(self.MIN_COLUMN, int(width)))
        finally:
            self._sizing = False

    def _on_section_resized(self, index: int, _old: int, _new: int) -> None:
        if self._sizing:
            return
        if index == self.columnCount() - 1 and self.horizontalHeader().stretchLastSection():
            # v2.6.1: the stretching last column follows the window, not the user;
            # counting it as a drag froze the default widths and cut the dates.
            return
        self._user_sized = True
        if self._key and DataTable.settings_store is not None:
            self._save_timer.start()

    def _save_widths(self) -> None:
        store = DataTable.settings_store
        if store is None or not self._key:
            return
        widths = [self.columnWidth(c) for c in range(self.columnCount())]
        try:
            store.set_setting(self._settings_name(), widths)
        except Exception:  # noqa: BLE001
            pass

    def reset_widths(self) -> None:
        """Forget saved widths and size the columns to their content again."""
        store = DataTable.settings_store
        if store is not None and self._key:
            try:
                store.set_setting(self._settings_name(), None)
            except Exception:  # noqa: BLE001
                pass
        self._auto_sized = False
        self._user_sized = False
        self._auto_size()

    def _auto_size(self) -> None:
        """Sensible first widths: content width clamped to [MIN, MAX_AUTO]."""
        if self._auto_sized or self.rowCount() == 0:
            return
        self._auto_sized = True
        metrics = self.fontMetrics()
        # v2.7.0: headers are drawn bold, so they are measured bold (no cut header)
        bold = QFont(self.horizontalHeader().font())
        bold.setBold(True)
        header_metrics = QFontMetrics(bold)
        widths = []
        floors = []
        for column in range(self.columnCount()):
            floor = max(self.MIN_COLUMN,
                        header_metrics.horizontalAdvance(self._headers[column]) + 48)
            floors.append(floor)
            wanted = floor
            for row in range(min(self.rowCount(), 30)):
                item = self.item(row, column)
                if item is not None:
                    wanted = max(wanted, metrics.horizontalAdvance(item.text()) + 36)
                elif self.cellWidget(row, column) is not None:
                    hint = self.cellWidget(row, column).sizeHint().width() + 24
                    wanted = max(wanted, hint)
                    floors[column] = max(floors[column], hint)   # never squeeze a pill/button
            width = min(max(wanted, self.MIN_COLUMN), self.MAX_AUTO_COLUMN)
            if column in self._keep:
                floors[column] = max(floors[column], width)
            widths.append(width)
        self._natural, self._floor = widths, floors
        self._fit_to_viewport()

    def _fit_to_viewport(self) -> None:
        """Shrink the roomy columns (never below their header) so nothing is cut off."""
        if self._user_sized or not self._natural:
            return
        available = self.viewport().width() or self.width()
        widths = list(self._natural)
        excess = sum(widths) - available
        slack = sum(w - f for w, f in zip(widths, self._floor))
        if excess > 0 and slack > 0 and available > 0:
            factor = min(1.0, excess / slack)
            widths = [round(w - (w - f) * factor) for w, f in zip(widths, self._floor)]
        self._apply_widths(widths)

    # ---- helpers ---------------------------------------------------------
    def _emit_row(self, row: int, _column: int) -> None:
        self.row_activated.emit(row)

    def set_empty_state(self, title: str, hint: str = "", icon_name: str = "inbox") -> None:
        self._empty_title = title
        self._empty_hint = hint
        self._empty_icon = icon_name

    def set_cell(self, row: int, column: int, text: str, *, color: str | None = None,
                 bold: bool = False, tooltip: str = "",
                 align: Qt.AlignmentFlag = RIGHT) -> QTableWidgetItem:
        # v2.8.0: the real right edge; Latin-only text (codes, paths) is drawn
        # left-to-right by the table's delegate (the text itself is unchanged)
        item = QTableWidgetItem(text)
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        if bold:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
        item.setToolTip(tooltip or text)   # the full text when the cell is cut short
        self.setItem(row, column, item)
        return item

    def set_widget(self, row: int, column: int, widget: QWidget) -> None:
        self.setCellWidget(row, column, widget)

    def fill(self, rows: Iterable[Sequence[Any]]) -> None:
        """Replace the contents. ``None`` values become a Persian dash."""
        self.setUpdatesEnabled(False)
        try:
            self.setRowCount(0)
            for row_values in rows:
                row = self.rowCount()
                self.insertRow(row)
                for column, value in enumerate(row_values):
                    text = "—" if value is None else str(value)
                    self.set_cell(row, column, text)
        finally:
            self.setUpdatesEnabled(True)
        self._refresh_states()

    # ---- states ----------------------------------------------------------
    def set_error_state(self, title: str = "دریافت اطلاعات ناموفق بود",
                        hint: str = "اتصال به سرور فروشگاه را بررسی کنید و دوباره تلاش کنید.") -> None:
        """Show a clear failure state instead of leaving the spinner running."""
        self.set_busy(False)
        self.set_empty_state(title, hint, "error")
        self.setRowCount(0)
        self._refresh_states()

    def set_busy(self, busy: bool, message: str = "در حال دریافت اطلاعات…") -> None:
        self._busy = busy
        if busy:
            if self._busy_widget is None:
                self._busy_widget = _CenteredOverlay(
                    icon_name="refresh", title=message, hint="", spin=True,
                    background=theme.SURFACE,
                )
                self._busy_widget.setParent(self.viewport())
            self._busy_widget.setGeometry(self.viewport().rect())
            self._busy_widget.raise_()
            self._busy_widget.show()
        elif self._busy_widget is not None:
            self._busy_widget.hide()
        self._refresh_states()

    def _refresh_states(self) -> None:
        if self.rowCount():
            self._auto_size()
        empty = self.rowCount() == 0 and not self._busy
        if empty:
            if self._empty_widget is None:
                self._empty_widget = _CenteredOverlay(
                    icon_name=self._empty_icon,
                    title=self._empty_title,
                    hint=self._empty_hint,
                    background=theme.SURFACE,
                )
                self._empty_widget.setParent(self.viewport())
            else:
                self._empty_widget.update_text(self._empty_title, self._empty_hint, self._empty_icon)
            self._empty_widget.setGeometry(self.viewport().rect())
            self._empty_widget.raise_()
            self._empty_widget.show()
        elif self._empty_widget is not None:
            self._empty_widget.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_to_viewport()
        for widget in (self._empty_widget, self._busy_widget):
            if widget is not None:
                widget.setGeometry(self.viewport().rect())


class _CenteredOverlay(QWidget):
    """Friendly empty/loading illustration shown over a table."""

    def __init__(self, *, icon_name: str, title: str, hint: str, spin: bool = False,
                 background: str = theme.SURFACE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Scoped by object name: an unscoped "background" would cascade onto the
        # labels inside and paint boxes behind them.
        self.setObjectName("CenteredOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#CenteredOverlay {{ background: {background}; }}")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setFixedHeight(56)
        layout.addWidget(self._icon)

        self._title = label(title, name="EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        self._hint = label(hint, name="EmptyHint", wrap=True)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setVisible(bool(hint))
        layout.addWidget(self._hint)

        self._spin = spin
        self._timer: QTimer | None = None
        self._angle = 0
        self.update_text(title, hint, icon_name)
        if spin:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._rotate)
            self._timer.start(60)

    def update_text(self, title: str, hint: str, icon_name: str) -> None:
        self._title.setText(title)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
        self._icon_name = icon_name
        self._render_icon()

    def _render_icon(self) -> None:
        size = 44
        pixmap = theme.icon_pixmap(self._icon_name, size, theme.TEXT_FAINT)
        if self._spin:
            rotated = QPixmap(size, size)
            rotated.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rotated)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.translate(size / 2, size / 2)
            painter.rotate(self._angle)
            painter.translate(-size / 2, -size / 2)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            pixmap = rotated
        self._icon.setPixmap(pixmap)

    def _rotate(self) -> None:
        self._angle = (self._angle + 12) % 360
        self._render_icon()


# --------------------------------------------------------------------------
# toasts
# --------------------------------------------------------------------------
class Toast(QFrame):
    """Small transient notification anchored to the bottom-left of a window."""

    def __init__(self, parent: QWidget, message: str, kind: str = "success",
                 duration_ms: int = 3800) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        colors = {
            "success": (theme.SUCCESS, theme.SUCCESS_LIGHT, "success"),
            "error": (theme.DANGER, theme.DANGER_LIGHT, "error"),
            "warning": (theme.WARNING, theme.WARNING_LIGHT, "warning"),
            "info": (theme.PRIMARY, theme.PRIMARY_LIGHT, "info"),
        }
        foreground, background, icon_name = colors.get(kind, colors["info"])
        self.setStyleSheet(
            f"QFrame#Toast {{ background: {background}; border: 1px solid {foreground}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(theme.icon_pixmap(icon_name, 20, foreground))
        layout.addWidget(icon_label)
        text = label(message, color=theme.INK, wrap=True)
        text.setStyleSheet(f"color: {theme.INK}; background: transparent;")
        layout.addWidget(text, 1)
        close = QPushButton()
        close.setIcon(theme.icon("close", 14, theme.TEXT_MUTED))
        close.setObjectName("Ghost")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

        self.adjustSize()
        self.setFixedWidth(min(420, max(280, self.sizeHint().width())))
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(180)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()
        QTimer.singleShot(duration_ms, self.dismiss)

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self.deleteLater)
        self._animation.start()


class ToastHost(QWidget):
    """Mix-in style helper: ``toast.show_success("...")``."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._active: list[Toast] = []

    def show(self, message: str, kind: str = "success", duration_ms: int = 3800) -> None:
        toast = Toast(self._parent, message, kind, duration_ms)
        toast.show()
        self._active = [t for t in self._active if t.isVisible()]
        self._active.append(toast)
        self._reposition()
        # A toast shown before the window finished its first layout would land
        # at a stale position, so re-place it once the event loop settles.
        QTimer.singleShot(0, self._reposition)

    def show_success(self, message: str) -> None:
        self.show(message, "success")

    def show_error(self, message: str) -> None:
        self.show(message, "error", 6000)

    def show_warning(self, message: str) -> None:
        self.show(message, "warning", 5000)

    def _reposition(self) -> None:
        margin = 24
        offset = 0
        for toast in reversed(self._active):
            toast.adjustSize()
            toast.move(margin, self._parent.height() - toast.height() - margin - offset)
            offset += toast.height() + 8
            toast.raise_()


def position_toasts(host: ToastHost) -> None:
    host._reposition()


# --------------------------------------------------------------------------
# dialogs
# --------------------------------------------------------------------------
def fit_wrapped_height(dialog: QDialog) -> None:
    """Grow a dialog so wrapped labels are not clipped.

    Top-level windows ignore height-for-width, so a long wrapped message would
    be cut off at the bottom; ask the layout for the height it needs at the
    current width instead.
    """
    layout = dialog.layout()
    if layout is None:
        return
    needed = layout.totalHeightForWidth(dialog.width())
    if needed > dialog.height():
        dialog.resize(dialog.width(), needed)


class MessageDialog(QDialog):
    """A clear Persian message box with an icon; no English button text."""

    def __init__(self, parent: QWidget | None, title: str, message: str,
                 kind: str = "info", detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(420)
        colors = {
            "error": (theme.DANGER, "error"),
            "warning": (theme.WARNING, "warning"),
            "success": (theme.SUCCESS, "success"),
            "question": (theme.PRIMARY, "info"),
            "info": (theme.PRIMARY, "info"),
        }
        accent, icon_name = colors.get(kind, colors["info"])

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_label = QLabel()
        icon_label.setPixmap(theme.icon_pixmap(icon_name, 34, accent))
        icon_label.setFixedSize(46, 46)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"background: {theme.BACKGROUND}; border-radius: 12px;")
        header.addWidget(icon_label)
        header.addWidget(label(title, size=13, bold=True), 1)
        root.addLayout(header)

        root.addWidget(label(message, wrap=True))
        if detail:
            detail_label = label(detail, name="Muted", wrap=True)
            detail_label.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; background: {theme.BACKGROUND}; "
                f"border-radius: {theme.RADIUS_SM}px; padding: 10px;"
            )
            root.addWidget(detail_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = button("باشه", variant="primary")
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.ok_button)
        root.addLayout(buttons)
        self.ok_button.setDefault(True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        fit_wrapped_height(self)


class ConfirmDialog(QDialog):
    """RTL confirmation with Persian Yes/No labels."""

    def __init__(self, parent: QWidget | None, title: str, message: str,
                 *, confirm_text: str = "تأیید", cancel_text: str = "انصراف",
                 kind: str = "question", detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(440)

        accent = {"danger": theme.DANGER, "warning": theme.WARNING}.get(kind, theme.PRIMARY)
        icon_name = {"danger": "warning", "warning": "warning"}.get(kind, "info")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(theme.icon_pixmap(icon_name, 34, accent))
        icon_label.setFixedSize(46, 46)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"background: {theme.BACKGROUND}; border-radius: 12px;")
        header.addWidget(icon_label)
        header.addWidget(label(title, size=13, bold=True), 1)
        root.addLayout(header)
        root.addWidget(label(message, wrap=True))
        if detail:
            root.addWidget(label(detail, name="Muted", wrap=True))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button(cancel_text)
        cancel.clicked.connect(self.reject)
        confirm = button(confirm_text, variant="danger" if kind == "danger" else "primary")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        fit_wrapped_height(self)


def info(parent: QWidget | None, title: str, message: str, *, kind: str = "info",
         detail: str = "") -> None:
    MessageDialog(parent, title, message, kind, detail).exec()


def error(parent: QWidget | None, title: str, message: str, detail: str = "") -> None:
    MessageDialog(parent, title, message, "error", detail).exec()


def success(parent: QWidget | None, title: str, message: str) -> None:
    MessageDialog(parent, title, message, "success").exec()


def confirm(parent: QWidget | None, title: str, message: str, *, confirm_text: str = "تأیید",
            cancel_text: str = "انصراف", kind: str = "question", detail: str = "") -> bool:
    dialog = ConfirmDialog(parent, title, message, confirm_text=confirm_text,
                           cancel_text=cancel_text, kind=kind, detail=detail)
    return dialog.exec() == QDialog.DialogCode.Accepted
