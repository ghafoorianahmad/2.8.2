"""تغییر اجباری گذرواژه — وقتی مدیر کل برای کاربر گذرواژهٔ موقت گذاشته است."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..auth import MIN_PASSWORD_LENGTH, AuthService
from ..persian import to_persian_digits
from . import theme, widgets
from .async_utils import run_async


class ForcedPasswordChangeDialog(QDialog):
    """Blocks until the user picks their own password (or cancels = sign out)."""

    def __init__(self, auth: AuthService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.auth = auth
        self.setWindowTitle("تغییر گذرواژه")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(12)
        layout.addWidget(widgets.label("گذرواژهٔ خود را تغییر دهید", size=14, bold=True))
        layout.addWidget(widgets.label(
            "گذرواژهٔ فعلی شما موقت است و توسط مدیر کل تعیین شده. برای ادامه، یک "
            f"گذرواژهٔ تازه با حداقل {to_persian_digits(MIN_PASSWORD_LENGTH)} نویسه "
            "که هم حرف و هم عدد داشته باشد انتخاب کنید.",
            name="Muted", wrap=True,
        ))

        self.current = self._field("گذرواژهٔ فعلی (موقت)")
        self.new = self._field("گذرواژهٔ جدید")
        self.confirm = self._field("تکرار گذرواژهٔ جدید")
        for caption, field in (("گذرواژهٔ فعلی", self.current), ("گذرواژهٔ جدید", self.new),
                               ("تکرار گذرواژهٔ جدید", self.confirm)):
            layout.addWidget(widgets.label(caption))
            layout.addWidget(field)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = widgets.button("ذخیره و ادامه", variant="primary", icon_name="check",
                                          on_click=self._save)
        cancel = widgets.button("خروج از حساب", on_click=self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.confirm.returnPressed.connect(self._save)

    @staticmethod
    def _field(placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(placeholder)
        field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        field.setMinimumHeight(40)
        return field

    def _save(self) -> None:
        if not self.save_button.isEnabled():
            return
        self.error_label.setVisible(False)
        self.save_button.setEnabled(False)
        current, new, confirm = self.current.text(), self.new.text(), self.confirm.text()

        def work() -> None:
            self.auth.change_own_password(current, new, confirm)

        def fail(message: str, _kind: str) -> None:
            self.error_label.setText(message)
            self.error_label.setVisible(True)

        def done() -> None:
            self.save_button.setEnabled(True)

        run_async(work, on_success=lambda _r: self.accept(), on_error=fail, on_done=done)

