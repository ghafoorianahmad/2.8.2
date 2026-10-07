"""Reusable widgets: cards, badges, table with loading/empty states, toasts.

Every visible string here is Persian and every number is rendered with Persian
digits by the caller (or by the helpers in :mod:`app.persian`).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..persian import to_persian_digits
from . import theme

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
    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return widget


def page_title(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(label(title, name="PageTitle"))
    if subtitle:
        layout.addWidget(label(subtitle, name="PageSubtitle"))
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
        text_column.addWidget(label(title, name="CardTitle"))
        self._value_label = label(value, name="CardValue")
        text_column.addWidget(self._value_label)
        self._hint_label = label(hint, name="Faint")
        self._hint_label.setVisible(bool(hint))
        text_column.addWidget(self._hint_label)
        text_column.addStretch(1)
        root.addLayout(text_column, 1)

        self._apply_accent()

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
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.addAction(theme.icon("search", 18, theme.TEXT_FAINT), QLineEdit.ActionPosition.LeadingPosition)


# --------------------------------------------------------------------------
# data table with loading / empty states
# --------------------------------------------------------------------------
class DataTable(QTableWidget):
    """A read-only table that knows how to show loading and empty states."""

    row_activated = Signal(int)

    def __init__(self, headers: Sequence[str], *, selectable_rows: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(0, len(headers), parent)
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
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.verticalHeader().setDefaultSectionSize(50)

        self._empty_title = "موردی برای نمایش وجود ندارد"
        self._empty_hint = ""
        self._empty_icon = "inbox"
        self._busy = False
        self._empty_widget: QWidget | None = None
        self._busy_widget: QWidget | None = None

        if selectable_rows:
            self.cellClicked.connect(self._emit_row)
            self.doubleClicked.connect(lambda index: self.row_activated.emit(index.row()))

    # ---- helpers ---------------------------------------------------------
    def _emit_row(self, row: int, _column: int) -> None:
        self.row_activated.emit(row)

    def set_empty_state(self, title: str, hint: str = "", icon_name: str = "inbox") -> None:
        self._empty_title = title
        self._empty_hint = hint
        self._empty_icon = icon_name

    def set_cell(self, row: int, column: int, text: str, *, color: str | None = None,
                 bold: bool = False, tooltip: str = "",
                 align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        if bold:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
        if tooltip:
            item.setToolTip(tooltip)
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
        for widget in (self._empty_widget, self._busy_widget):
            if widget is not None:
                widget.setGeometry(self.viewport().rect())


class _CenteredOverlay(QWidget):
    """Friendly empty/loading illustration shown over a table."""

    def __init__(self, *, icon_name: str, title: str, hint: str, spin: bool = False,
                 background: str = theme.SURFACE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"background: {background};")
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
