"""v2.9.0: «ظاهر برنامه» - palette, light / dark and «جلوه‌ها», chosen per computer.

Option cards like the equipment control panel's theme cards: each palette shows
its side-bar gradient and accent, so the choice is visible before it is made.
The look is stored in this computer's local settings (``theme_palette``,
``theme_mode``, ``theme_effects``); v2.9.1: it is applied at once (the main
window is rebuilt on the same page), no restart. v2.9.3: a click on a card is
enough: the choice is saved and applied to the whole program at once (no
«ذخیره» button, no restart).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QVBoxLayout, QWidget

from . import theme, widgets

KEY_PALETTE = "theme_palette"
KEY_MODE = "theme_mode"
KEY_EFFECTS = "theme_effects"
DEFAULT_LOOK = ("ocean", "light", "auto")

EFFECT_HINTS = {
    "auto": "سایه و حرکت نرم؛ روی رایانهٔ ضعیف یا «Remote Desktop» ساده",
    "full": "سایهٔ نرم زیر کارت‌ها و دکمه‌ها، پس‌زمینهٔ رنگی",
    "simple": "بدون سایه و گرادیان؛ سریع‌تر",
}


def saved_look(store) -> tuple[str, str, str]:
    """(palette, mode, effects) of this computer; unknown values -> defaults."""
    def get(key: str, allowed: tuple[str, ...], default: str) -> str:
        try:
            value = str(store.get_setting(key, default) or default)
        except Exception:  # noqa: BLE001 - a missing / broken local store
            return default
        return value if value in allowed else default
    return (get(KEY_PALETTE, theme.PALETTE_NAMES, DEFAULT_LOOK[0]),
            get(KEY_MODE, theme.THEME_MODES, DEFAULT_LOOK[1]),
            get(KEY_EFFECTS, theme.EFFECT_CHOICES, DEFAULT_LOOK[2]))


def save_look(store, palette: str, mode: str, effects: str) -> None:
    store.set_setting(KEY_PALETTE, palette)
    store.set_setting(KEY_MODE, mode)
    store.set_setting(KEY_EFFECTS, effects)


def palette_swatch(palette: str, mode: str = "light", size: QSize = QSize(46, 30)) -> QPixmap:
    """A small rounded tile: the side-bar gradient with the accent dot."""
    tokens = theme.palette_tokens(palette, mode)
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(0.5, 0.5, size.width() - 1, size.height() - 1)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(tokens["SIDEBAR_BG"]))
    gradient.setColorAt(1, QColor(tokens["SIDEBAR_BG2"]))
    path = QPainterPath()
    path.addRoundedRect(rect, 8, 8)
    painter.fillPath(path, QBrush(gradient))
    accent = QLinearGradient(0, 0, size.width(), 0)
    accent.setColorAt(0, QColor(tokens["ACCENT"]))
    accent.setColorAt(1, QColor(tokens["ACCENT2"]))
    dot = QRectF(size.width() * 0.52, size.height() * 0.28, size.height() * 0.44,
                 size.height() * 0.44)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(accent))
    painter.drawEllipse(dot)
    painter.end()
    return pixmap


def _mode_swatch(mode: str, size: QSize = QSize(46, 30)) -> QPixmap:
    light, dark = theme.palette_tokens(theme.PALETTE, "light"), theme.palette_tokens(theme.PALETTE, "dark")
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(0.5, 0.5, size.width() - 1, size.height() - 1)
    path = QPainterPath()
    path.addRoundedRect(rect, 8, 8)
    if mode == "system":
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0.0, QColor(light["SURFACE"]))
        gradient.setColorAt(0.49, QColor(light["SURFACE"]))
        gradient.setColorAt(0.51, QColor(dark["SURFACE"]))
        gradient.setColorAt(1.0, QColor(dark["SURFACE"]))
        painter.fillPath(path, QBrush(gradient))
    else:
        tokens = light if mode == "light" else dark
        painter.fillPath(path, QColor(tokens["SURFACE"]))
    painter.setPen(QColor(light["BORDER_STRONG"]))
    painter.drawPath(path)
    painter.end()
    return pixmap


class OptionCard(QPushButton):
    """One choice: a picture and a name; the chosen one has an accent frame."""

    def __init__(self, text: str, pixmap: QPixmap | None = None, tooltip: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("OptionCard")
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if pixmap is not None:
            self.setIcon(pixmap)
            self.setIconSize(pixmap.size())
        if tooltip:
            self.setToolTip(tooltip)
        self.setMinimumHeight(48)


def apply_look_now(context) -> None:
    """v2.9.3: the saved look on the whole program, right now: the main window is
    rebuilt on the same page (``context.apply_look``, set by the program for every
    signed-in window); without it (tests) the look is only saved."""
    apply_now = getattr(context, "apply_look", None) if context is not None else None
    if apply_now is not None:
        QTimer.singleShot(0, apply_now)


class AppearancePicker(QWidget):
    """Palette / mode / effects as three rows of option cards. v2.9.3 (``context``
    given): a click saves and applies the look at once; ``applied`` is emitted."""

    changed = Signal()
    applied = Signal()
    #: clicks closer than this are applied once (the window is rebuilt each time)
    APPLY_DELAY_MS = 120

    def __init__(self, store, parent: QWidget | None = None, *, context=None) -> None:
        super().__init__(parent)
        self.store = store
        self.context = context
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(self.APPLY_DELAY_MS)
        self._apply_timer.timeout.connect(self.apply_now)
        self.initial = saved_look(store)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.groups: dict[str, QButtonGroup] = {}
        self.cards: dict[str, dict[str, OptionCard]] = {}
        rows = (
            ("palette", "رنگ‌بندی", [(name, theme.PALETTE_LABELS[name],
                                      palette_swatch(name, theme.MODE), "")
                                     for name in theme.PALETTE_NAMES]),
            ("mode", "روشن یا تیره", [(name, theme.MODE_LABELS[name], _mode_swatch(name), "")
                                      for name in theme.THEME_MODES]),
            ("effects", "جلوه‌ها", [(name, theme.EFFECT_LABELS[name], None, EFFECT_HINTS[name])
                                    for name in theme.EFFECT_CHOICES]),
        )
        current = dict(zip(("palette", "mode", "effects"), self.initial))
        for key, title, options in rows:
            root.addWidget(widgets.label(title + ":", bold=True))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            group = QButtonGroup(self)
            group.setExclusive(True)
            self.groups[key] = group
            self.cards[key] = {}
            for column, (value, text, pixmap, tip) in enumerate(options):
                card = OptionCard(text, pixmap, tip)
                card.setProperty("value", value)
                card.setChecked(value == current[key])
                group.addButton(card)
                grid.addWidget(card, 0, column)
                grid.setColumnStretch(column, 1)
                self.cards[key][value] = card
            group.buttonToggled.connect(lambda *_: self.changed.emit())
            # v2.9.3: a click (never a programmatic select) saves and applies
            group.buttonClicked.connect(lambda *_: self._clicked())
            root.addLayout(grid)
        self.note = widgets.label(
            "با کلیک روی هر گزینه، ظاهر همان لحظه روی کل برنامه اعمال و ذخیره می‌شود؛ "
            "دکمهٔ ذخیره یا باز کردن دوبارهٔ برنامه لازم نیست. انتخاب فقط روی همین رایانه "
            "است.", name="Muted", wrap=True)
        root.addWidget(self.note)

    def value(self, key: str) -> str:
        button = self.groups[key].checkedButton()
        return str(button.property("value")) if button is not None else ""

    def values(self) -> tuple[str, str, str]:
        return self.value("palette"), self.value("mode"), self.value("effects")

    def select(self, palette: str | None = None, mode: str | None = None,
               effects: str | None = None) -> None:
        for key, value in (("palette", palette), ("mode", mode), ("effects", effects)):
            if value is not None and value in self.cards[key]:
                self.cards[key][value].setChecked(True)

    def has_changed(self) -> bool:
        return self.values() != self.initial

    def save(self) -> bool:
        """Store the choice; True when it differs from what this program started with."""
        changed = self.has_changed()
        save_look(self.store, *self.values())
        self.initial = self.values()
        return changed

    def _clicked(self) -> None:
        if self.context is not None and self.has_changed():
            self._apply_timer.start()

    def apply_now(self) -> None:
        """Save the chosen look and apply it to the whole program."""
        self._apply_timer.stop()
        if self.save():
            apply_look_now(self.context)
            self.applied.emit()


def offer_restart(parent: QWidget, context) -> None:
    """After a new look was saved: v2.9.1 applies it at once (after the dialog that
    saved it has closed); only without the live path, open the program again."""
    apply_now = getattr(context, "apply_look", None)
    if apply_now is not None:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, apply_now)
        return
    restart = getattr(context, "restart_app", None)
    if restart is None:
        widgets.info(parent, "ظاهر برنامه", "ذخیره شد؛ برنامه را یک بار ببندید و دوباره باز کنید.")
        return
    if widgets.confirm(parent, "ظاهر برنامه",
                       "ظاهر تازه ذخیره شد. برای دیدن آن، برنامه بسته و دوباره باز شود؟",
                       confirm_text="باز کردن دوباره", cancel_text="بعداً"):
        restart()
