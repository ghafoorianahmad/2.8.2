"""Reusable widgets: cards, badges, table with loading/empty states, toasts.

Every visible string here is Persian and every number is rendered with Persian
digits by the caller (or by the helpers in :mod:`app.persian`).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
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
    QScrollArea,
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
    re-renders its children, so it must not wrap big tables. v2.9.0: none with
    «جلوه‌ها: ساده»; deeper in the dark look."""
    if theme.EFFECTS == "simple":
        return widget
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(theme.shadow_color(alpha * 4 if theme.MODE == "dark" else alpha + 10))
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
                 accent: str | None = None, tint: str | None = None,
                 hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # v2.9.0: read at run time (the palette is chosen after this module loads)
        accent = accent or theme.PRIMARY
        tint = tint or theme.PRIMARY_SOFT
        self.setObjectName("Card")
        self._accent = accent
        self.setMinimumHeight(122)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        icon_holder = QLabel()
        icon_holder.setFixedSize(58, 58)
        icon_holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if theme.EFFECTS == "simple":
            icon_holder.setPixmap(theme.icon_pixmap(icon_name, 30, accent))
            icon_holder.setStyleSheet(f"background: {tint}; border-radius: 16px;")
        else:
            # v2.9.0 (the control panel's stat icons): a white icon on an accent gradient
            light = QColor(accent).lighter(135).name()
            icon_holder.setPixmap(theme.icon_pixmap(icon_name, 30, "#FFFFFF"))
            icon_holder.setStyleSheet(
                f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent}, "
                f"stop:1 {light}); border-radius: 16px;")
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
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.updateGeometry()
        self.adjustSize()

    # v2.8.2: the bold text + the 12px padding on both sides, measured with the font
    # the pill really draws with (its parent's): Qt's own hint left the padding out,
    # so «کاربر فروش» / «ثبت‌شده در حسابداری» were cut.
    PADDING = 12

    def _text_width(self) -> int:
        bold = QFont(self.font())
        bold.setBold(True)
        return QFontMetrics(bold).horizontalAdvance(self.text()) + 2 * self.PADDING + 6

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        return QSize(max(hint.width(), self._text_width()), max(hint.height(), 26))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange,
                            QEvent.Type.ParentChange):
            self.updateGeometry()


def theme_status_colors(status: str) -> tuple[str, str]:
    from ..statuses import status_colors

    return status_colors(status)


def actions_menu_button(actions, *, text: str = "بیشتر", tooltip: str = "کارهای دیگر") -> QPushButton:
    """v2.8.2: «بیشتر» (a "⋯" menu) for row actions that do not fit as buttons (the
    "⋯" glyph itself is not in the Persian font).
    ``actions``: (text, callback, enabled, tooltip) tuples; ``None`` = separator."""
    from PySide6.QtWidgets import QMenu

    button = QPushButton(text)
    button.setObjectName("RowMenu")
    button.setToolTip(tooltip)
    button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    menu = QMenu(button)
    menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    for entry in actions:
        if entry is None:
            menu.addSeparator()
            continue
        label_text, callback, enabled, tip = (tuple(entry) + ("",))[:4]
        action = menu.addAction(label_text)
        action.setEnabled(bool(enabled))
        if tip:
            action.setToolTip(tip)
        action.triggered.connect(lambda _c=False, cb=callback: cb())
    menu.setToolTipsVisible(True)
    button.setMenu(menu)
    button.menu_actions = menu.actions()      # tests / callers
    return button


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
class MaskedLineEdit(QLineEdit):
    """v2.9.0: clicking or tabbing into a field with an input mask (card number,
    Sheba) puts the cursor on the FIRST EMPTY place of the mask, not where the
    mouse happened to land among the blanks. A click inside what is already
    typed keeps its place (to correct a digit); a field without a mask (account
    number) goes to the end of its text."""

    def blank_char(self) -> str:
        mask = self.inputMask()
        if ";" in mask:
            return mask.rsplit(";", 1)[1][:1] or " "
        return " "

    def first_empty_position(self) -> int:
        if not self.inputMask():
            return len(self.text())
        shown = self.displayText()
        index = shown.find(self.blank_char())
        return index if index >= 0 else len(shown)

    def jump_to_first_empty(self) -> None:
        if not self.hasSelectedText():
            self.setCursorPosition(self.first_empty_position())

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().focusInEvent(event)
        if event.reason() != Qt.FocusReason.MouseFocusReason:
            # after Qt's own placement (it moves to the mask's first place)
            QTimer.singleShot(0, self.jump_to_first_empty)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and \
                self.cursorPosition() > self.first_empty_position():
            self.setCursorPosition(self.first_empty_position())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not self.hasSelectedText() and \
                self.cursorPosition() > self.first_empty_position():
            self.setCursorPosition(self.first_empty_position())


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
                 fit_width: bool = False, stretch_column: int = 1,
                 parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
        #: v2.8.3: the columns fit the visible width (never a horizontal scroll bar):
        #: each column as wide as its content, ``stretch_column`` takes the rest
        self._fit_width = bool(fit_width)
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
        if self._fit_width:
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            if 0 <= stretch_column < len(headers):
                header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
            # the stretching column absorbs the rest: a scroll bar only appears on a
            # window too narrow for the content itself (never hides a column)
        self._headers = list(headers)
        # v2.8.1: every header is readable from the start (also while empty)
        self._header_floor = [self.header_width(text) for text in self._headers]
        self._apply_widths(self._header_floor)
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
    def sizeHintForColumn(self, column: int) -> int:  # noqa: N802 - Qt naming
        """v2.8.3 (``fit_width``): a content-sized column is never narrower than
        its header or a pill / button in it."""
        hint = super().sizeHintForColumn(column)
        if not getattr(self, "_fit_width", False):
            return hint
        floors = getattr(self, "_header_floor", [])
        if column < len(floors):
            hint = max(hint, floors[column])
        for row in range(min(self.rowCount(), 50)):
            widget = self.cellWidget(row, column)
            if widget is not None:
                hint = max(hint, widget.sizeHint().width() + 24)
        return hint

    def _settings_name(self) -> str:
        return f"table_widths.{self._key}"

    def _restore_widths(self) -> None:
        store = DataTable.settings_store
        if not self._key or store is None or self._fit_width:
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

    #: Room around a header's text: the section padding (2 x 10), its border and
    #: a little air so the bold text is never cut with «…».
    HEADER_PADDING = 40

    def header_width(self, text: str) -> int:
        """Width that shows the whole (bold) header ``text``."""
        bold = QFont(self.horizontalHeader().font())
        bold.setBold(True)
        return max(self.MIN_COLUMN,
                   QFontMetrics(bold).horizontalAdvance(text) + self.HEADER_PADDING)

    def _apply_widths(self, widths: Sequence[int]) -> None:
        """Programmatic widths (automatic, or restored from an older version)
        never cut a header: each column is at least as wide as its title."""
        floors = getattr(self, "_header_floor", [])
        self._sizing = True
        try:
            for column, width in enumerate(widths):
                floor = floors[column] if column < len(floors) else self.MIN_COLUMN
                self.setColumnWidth(column, max(self.MIN_COLUMN, floor, int(width)))
        finally:
            self._sizing = False

    def _on_section_resized(self, index: int, _old: int, _new: int) -> None:
        if self._sizing or self._fit_width:
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
        widths = []
        floors = []
        for column in range(self.columnCount()):
            # v2.7.0: headers are drawn bold, so they are measured bold (no cut header)
            floor = self.header_width(self._headers[column]) + 8
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


def show_full_headers(table, padding: int = 40) -> None:
    """v2.8.1: a plain table / tree never cuts its column titles: every column
    starts at least as wide as its (bold) header."""
    header = table.header() if hasattr(table, "header") else table.horizontalHeader()
    model = table.model()
    bold = QFont(header.font())
    bold.setBold(True)
    metrics = QFontMetrics(bold)
    widest = 0
    for column in range(header.count()):
        text = str(model.headerData(column, Qt.Orientation.Horizontal) or "")
        wanted = metrics.horizontalAdvance(text) + padding
        widest = max(widest, wanted)
        if header.sectionSize(column) < wanted:
            header.resizeSection(column, wanted)
    # stretched columns are sized by Qt: the minimum keeps every title whole
    header.setMinimumSectionSize(max(header.minimumSectionSize(), widest))


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
# --------------------------------------------------------------------------
# windows and dialogs that fit any screen (v2.8.1)
# --------------------------------------------------------------------------
#: Part of the screen's work area a window may take when it opens.
SCREEN_FRACTION = 0.92


def available_geometry(widget: QWidget | None) -> QRect:
    """The work area (without the taskbar) of the screen the widget is on, in
    device-independent pixels, so Windows scaling (125%, 150%, …) is included."""
    screen = None
    if widget is not None:
        parent = widget.parentWidget()
        screen = (parent.window().screen() if parent is not None else None) or widget.screen()
    screen = screen or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)


def fit_window_to_screen(window: QWidget, *, center: bool = True) -> None:
    """Never bigger than the screen: shrink the minimum size and the size to the
    work area (the content scrolls instead), grow to the wanted size when there
    is room, and keep the whole window on the screen."""
    area = available_geometry(window)
    max_w = max(320, int(area.width() * SCREEN_FRACTION))
    max_h = max(240, int(area.height() * SCREEN_FRACTION))
    minimum = window.minimumSize()
    window.setMinimumSize(min(minimum.width(), max_w), min(minimum.height(), max_h))
    hint = window.sizeHint()
    width = min(max(window.width(), hint.width(), window.minimumWidth()), max_w)
    height = min(max(window.height(), hint.height(), window.minimumHeight()), max_h)
    window.resize(width, height)
    if isinstance(window, QDialog):
        fit_wrapped_height(window)
    if not center:
        return
    parent = window.parentWidget()
    if parent is not None and parent.window().isVisible():
        anchor = parent.window().frameGeometry().center()
    else:
        anchor = area.center()
    x = min(anchor.x() - window.width() // 2, area.right() - window.width())
    y = min(anchor.y() - window.height() // 2, area.bottom() - window.height())
    window.move(max(x, area.left()), max(y, area.top()))


def fit_wrapped_height(dialog: QDialog) -> None:
    """Grow a dialog so wrapped labels are not clipped (up to the screen height).

    Top-level windows ignore height-for-width, so a long wrapped message would
    be cut off at the bottom; ask the layout for the height it needs at the
    current width instead. A responsive dialog asks its scrolled body.
    """
    scroll = getattr(dialog, "_fit_scroll", None)
    if scroll is not None:
        body_layout = scroll.widget().layout()
        if body_layout is None or not body_layout.hasHeightForWidth():
            return
        width = scroll.viewport().width() or dialog.width()
        needed = (dialog.height() - scroll.viewport().height()
                  + body_layout.totalHeightForWidth(width))
    else:
        layout = dialog.layout()
        if layout is None:
            return
        needed = layout.totalHeightForWidth(dialog.width())
    limit = int(available_geometry(dialog).height() * SCREEN_FRACTION)
    if needed > dialog.height():
        dialog.resize(dialog.width(), min(needed, max(limit, dialog.minimumHeight())))


class _FitScrollArea(QScrollArea):
    """A scroll area that asks for the size of its content (the window is then
    capped by the screen), instead of Qt's small default."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        hint = widget.sizeHint()
        frame = 2 * self.frameWidth()
        return QSize(hint.width() + frame + self.verticalScrollBar().sizeHint().width(),
                     hint.height() + frame)


def _is_button(widget: QWidget | None) -> bool:
    return isinstance(widget, (QPushButton, QDialogButtonBox))


def _is_button_row(item) -> bool:
    """The last row of a dialog made only of buttons (plus spacing / short labels)."""
    widget = item.widget()
    if _is_button(widget):
        return True
    if widget is not None:
        return False
    layout = item.layout()
    if layout is None:
        return False
    found = False
    for index in range(layout.count()):
        child = layout.itemAt(index)
        if child.spacerItem() is not None:
            continue
        if _is_button(child.widget()):
            found = True
        elif not isinstance(child.widget(), QLabel):
            return False
    return found


def _readd(layout: QBoxLayout, item, stretch: int) -> None:
    if item.widget() is not None:
        layout.addWidget(item.widget(), stretch, item.alignment())
    elif item.layout() is not None:
        layout.addLayout(item.layout(), stretch)
    elif item.spacerItem() is not None:
        layout.addItem(item.spacerItem())
        layout.setStretch(layout.count() - 1, stretch)


def _button_flow(row) -> QWidget:
    """The footer buttons in a row that wraps to a second line on a narrow window
    (same order: in a right-to-left window the first button is on the right)."""
    holder = QWidget()
    flow = FlowLayout(holder, spacing=8)
    if row.widget() is not None:
        flow.addWidget(row.widget())
        return holder
    source = row.layout()
    while source.count():
        child = source.takeAt(0)
        if child.widget() is not None:
            flow.addWidget(child.widget())
    return holder


class _FitOnShow(QObject):
    """Fits a responsive window to its screen the first time it is shown."""

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.Show and not watched.property("fitted"):
            watched.setProperty("fitted", True)
            fit_window_to_screen(watched)
        return False


_FIT_ON_SHOW = _FitOnShow()


#: v2.8.2: an explicit title-bar set. Adding the maximise hint to a dialog's default
#: flags (2.8.1) made Windows grey out the ✕ (SC_CLOSE disabled); with
#: CustomizeWindowHint every listed button is shown and enabled.
DIALOG_FLAGS = (Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)


def make_responsive(dialog: QDialog) -> QDialog:
    """v2.8.1: a dialog that scrolls, can be resized and maximised, and opens no
    larger than the screen (any screen size, any Windows scaling).

    The content moves into a scroll area; a last row of buttons stays visible
    below it and wraps on a narrow window, so «تأیید موجودی» can always be
    pressed. Call before the dialog is shown (:class:`ResponsiveDialog` does).
    """
    if dialog.property("responsive"):
        return dialog
    dialog.setProperty("responsive", True)
    dialog.setWindowFlags(DIALOG_FLAGS)
    dialog.setSizeGripEnabled(True)
    dialog.installEventFilter(_FIT_ON_SHOW)
    layout = dialog.layout()
    if not isinstance(layout, QBoxLayout) or layout.count() == 0 \
            or layout.direction() != QBoxLayout.Direction.TopToBottom:
        return dialog

    items = []
    while layout.count():
        stretch = layout.stretch(0)
        items.append((layout.takeAt(0), stretch))
    footer = items.pop()[0] if len(items) > 1 and _is_button_row(items[-1][0]) else None
    margins = layout.contentsMargins()

    body = QWidget()
    body.setObjectName("DialogBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(margins.left(), margins.top(), margins.right(),
                                   6 if footer is not None else margins.bottom())
    body_layout.setSpacing(layout.spacing())
    for item, stretch in items:
        _readd(body_layout, item, stretch)

    scroll = _FitScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(body)
    dialog._fit_scroll = scroll
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(scroll, 1)
    if footer is not None:
        bar = QWidget()
        bar.setObjectName("DialogFooter")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(margins.left(), 8, margins.right(), margins.bottom())
        bar_layout.addWidget(_button_flow(footer))
        layout.addWidget(bar)
    return dialog


class ResponsiveDialog(QDialog):
    """A dialog made responsive (:func:`make_responsive`) just before it opens."""

    def _prepare(self) -> None:
        make_responsive(self)

    def exec(self) -> int:  # noqa: A003 - Qt naming
        self._prepare()
        return super().exec()

    def show(self) -> None:
        self._prepare()
        super().show()

    def open(self) -> None:  # noqa: A003 - Qt naming
        self._prepare()
        super().open()


class MessageDialog(ResponsiveDialog):
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


class ConfirmDialog(ResponsiveDialog):
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
