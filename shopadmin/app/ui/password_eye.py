"""v2.9.4: an eye on EVERY password field (setup wizard, SQL password, change
password, new user, Telegram 2FA, secrets …).

The eye shows only what the person typed in this field. A password the program
put there itself (a saved one) is never shown: the eye is disabled until the
field is emptied. Installed once for the whole application (a polish hook):
any line edit in password mode gets the eye when it is first polished, so a new
dialog cannot forget it. A field that has its own eye (the sign-in window) sets
the property ``password_eye``.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from . import theme

PROPERTY = "password_eye"
TIP_SHOW = "نمایش گذرواژه"
TIP_HIDE = "پنهان کردن گذرواژه"
TIP_SAVED = "گذرواژهٔ ذخیره‌شده نمایش داده نمی‌شود"


class PasswordEye(QObject):
    """The eye of one field."""

    def __init__(self, field: QLineEdit) -> None:
        super().__init__(field)
        self.field = field
        self.shown = False
        #: the text came from the program (not typed): never revealed
        self.saved = bool(field.text())
        self._typed = field.text() if not self.saved else None
        field.setProperty(PROPERTY, True)
        self.action = field.addAction(theme.icon("eye", 18, theme.TEXT_MUTED),
                                      QLineEdit.ActionPosition.TrailingPosition)
        self.action.triggered.connect(self.toggle)
        field.textEdited.connect(self._edited)
        field.textChanged.connect(self._changed)
        self._refresh()

    def _edited(self, text: str) -> None:
        self._typed = text

    def _changed(self, _text: str) -> None:
        # textEdited arrives with the same edit: decide once both are in
        QTimer.singleShot(0, self._settle)

    def _settle(self) -> None:
        try:
            text = self.field.text()
        except RuntimeError:          # the field is gone
            return
        if not text:
            self.saved = False
        elif text != self._typed and not self.saved:
            self.saved = True         # set by the program: a saved password
        if self.saved and self.shown:
            self.set_shown(False)
        self._refresh()

    def toggle(self) -> None:
        if self.saved:
            return
        self.set_shown(not self.shown)

    def set_shown(self, shown: bool) -> None:
        self.shown = bool(shown) and not self.saved
        self.field.setEchoMode(QLineEdit.EchoMode.Normal if self.shown
                               else QLineEdit.EchoMode.Password)
        self._refresh()

    def _refresh(self) -> None:
        self.action.setEnabled(not self.saved)
        self.action.setIcon(theme.icon("eye_off" if self.shown else "eye", 18, theme.TEXT_MUTED))
        self.action.setToolTip(TIP_SAVED if self.saved else TIP_HIDE if self.shown else TIP_SHOW)


def attach(field: QLineEdit) -> PasswordEye | None:
    """Give ``field`` an eye (once)."""
    if field.property(PROPERTY):
        return None
    eye = PasswordEye(field)
    field._password_eye = eye  # noqa: SLF001 - keep it alive with the field
    return eye


def _on_polish(widget) -> None:
    if isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Password \
            and not widget.property(PROPERTY):
        attach(widget)


def install(app: QApplication) -> None:
    """Once per application (apply_theme calls it every time; it is idempotent).
    Rides on the single application filter of ``rtl`` (every widget's polish),
    so no second per-event Python filter slows the program down."""
    from .rtl import add_polish_hook, install_rtl_defaults

    install_rtl_defaults(app)
    add_polish_hook(_on_polish)
