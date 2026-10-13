"""پنجرهٔ ورود به برنامه."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..auth import MAX_FAILED_ATTEMPTS, AuthError, AuthService
from ..logging_setup import get_logger
from ..paths import APP_VERSION
from ..persian import to_english_digits, to_persian_digits
from ..store import Store
from . import theme, widgets
from .async_utils import run_async

log = get_logger("login")


class LoginWindow(QWidget):
    """Username + password login with an optional remember-me token."""

    logged_in = Signal(object)   # LoginResult
    cancelled = Signal()

    def __init__(self, store: Store, auth: AuthService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.auth = auth
        self.toasts = widgets.ToastHost(self)

        self.setWindowTitle("ورود به مدیریت فروشگاه")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(520, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(440)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 28)
        card_layout.setSpacing(16)

        logo = QPushButton()
        logo.setObjectName("Ghost")
        logo.setIcon(theme.icon("products", 40, theme.PRIMARY))
        logo.setIconSize(QSize(40, 40))
        logo.setFixedSize(76, 76)
        logo.setStyleSheet(f"background: {theme.PRIMARY_SOFT}; border-radius: 20px;")
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        card_layout.addLayout(logo_row)

        title = widgets.label("ورود به مدیریت فروشگاه", size=16, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = widgets.label(
            "برای ادامه، نام کاربری و گذرواژهٔ خود را وارد کنید.", name="Muted", wrap=True
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(subtitle)

        card_layout.addWidget(widgets.hline())

        card_layout.addWidget(widgets.label("نام کاربری"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("نام کاربری خود را وارد کنید")
        self.username_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.username_input.setMinimumHeight(42)
        card_layout.addWidget(self.username_input)

        card_layout.addWidget(widgets.label("گذرواژه"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("گذرواژه")
        self.password_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.password_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.password_input.setMinimumHeight(42)
        card_layout.addWidget(self.password_input)

        self.remember_check = QCheckBox("مرا به خاطر بسپار")
        self.remember_check.setChecked(bool(self.store.get_setting("remember_me", False)))
        card_layout.addWidget(self.remember_check)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.error_label)

        self.login_button = widgets.button(
            "ورود", variant="primary", icon_name="logout", on_click=self._submit
        )
        self.login_button.setMinimumHeight(46)
        card_layout.addWidget(self.login_button)

        # ---- last user hint (informational only) ------------------------
        self.forgot_button = widgets.button(
            "فراموشی گذرواژه", variant="ghost", on_click=self._forgot_password,
            tooltip="درخواست تعیین گذرواژهٔ جدید از مدیر فروشگاه")
        card_layout.addWidget(self.forgot_button)

        self.saved_box = QFrame()
        self.saved_box.setVisible(False)
        saved_layout = QVBoxLayout(self.saved_box)
        saved_layout.setContentsMargins(0, 6, 0, 0)
        saved_layout.setSpacing(8)
        self.saved_label = widgets.label("", name="Muted", wrap=True)
        self.saved_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        saved_layout.addWidget(self.saved_label)
        card_layout.addWidget(self.saved_box)

        card_layout.addWidget(widgets.hline())
        footer = widgets.label(
            f"نسخهٔ {to_persian_digits(APP_VERSION)} — ارتباط با سرور فروشگاه از طریق API",
            name="Faint", wrap=True,
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(footer)

        root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

        # Scoped to this window only: an unscoped "background" would also paint
        # every child, overriding the white-on-blue primary buttons.
        self.setObjectName("WindowRoot")
        self.setStyleSheet(f"QWidget#WindowRoot {{ background: {theme.BACKGROUND}; }}")

        self.username_input.returnPressed.connect(self._submit)
        self.password_input.returnPressed.connect(self._submit)
        self._attempts = 0
        QTimer.singleShot(0, self._prefill_remembered_username)

    # ------------------------------------------------------------------ forgot
    def _forgot_password(self) -> None:
        from .forgot_dialog import ForgotPasswordDialog

        dialog = ForgotPasswordDialog(self.auth, to_english_digits(self.username_input.text()),
                                      self)
        dialog.exec()
        if dialog.completed:
            self.username_input.setText(dialog.username)
            self.password_input.clear()
            self.password_input.setFocus()
            self.saved_label.setText("گذرواژهٔ جدید ثبت شد. با آن وارد شوید.")
            self.saved_box.setVisible(True)

    # ------------------------------------------------------------------ saved
    def _prefill_remembered_username(self) -> None:
        """Pre-fill the username when a saved login exists but is not usable.

        Automatic login is attempted by the controller BEFORE this window is
        shown. If we are here, that failed (revoked token, disabled account…),
        so the least we can do is fill in the name the user used last time.
        """
        try:
            username = self.auth.remembered_username()
        except sqlite3.Error:
            return   # the window outlived its store (teardown); nothing to prefill
        if not username:
            return
        self.username_input.setText(username)
        self.remember_check.setChecked(True)
        self.saved_label.setText(
            f"آخرین کاربر این دستگاه: «{username}». گذرواژه را وارد کنید."
        )
        self.saved_box.setVisible(True)
        self.password_input.setFocus()

    def prefill_username(self, username: str) -> None:
        """Lock screen: the same person usually comes back."""
        self.username_input.setText(username)
        self.password_input.setFocus()

    def show_message(self, message: str) -> None:
        """Explain why the login window is showing (session ended, locked…)."""
        self.saved_box.setVisible(False)
        self._fail(message)

    # ------------------------------------------------------------------ login
    def _fail(self, message: str, detail: str = "") -> None:
        self.error_label.setText(message + (f"\n{detail}" if detail else ""))
        self.error_label.setVisible(True)

    def _submit(self) -> None:
        if self.login_button.isEnabled() is False:
            return
        username = to_english_digits(self.username_input.text()).strip()
        password = self.password_input.text()
        self.error_label.setVisible(False)

        if not username or not password:
            self._fail("نام کاربری و گذرواژه را وارد کنید.")
            return

        self.login_button.setEnabled(False)
        self.login_button.setText("در حال بررسی…")

        remember = self.remember_check.isChecked()

        def work():
            return self.auth.authenticate(username, password, remember=remember)

        def ok(result) -> None:
            self._on_success(result)

        def fail(message: str, _kind: str) -> None:
            self._attempts += 1
            detail = ""
            if _kind == "auth_error" and self._attempts >= 2 and "قفل" not in message                     and "گذرواژه نادرست" in message:
                remaining = max(0, MAX_FAILED_ATTEMPTS - self._attempts)
                detail = f"تعداد تلاش‌های باقی‌مانده تا قفل شدن حساب: {to_persian_digits(remaining)}"
            self._fail(message, detail)
            log.warning("login attempt failed (%s)", self._attempts)

        def done() -> None:
            self.login_button.setEnabled(True)
            self.login_button.setText("ورود")

        run_async(work, on_success=ok, on_error=fail, on_done=done)

    def _on_success(self, result) -> None:
        self._attempts = 0
        remember = self.remember_check.isChecked()
        self.store.set_setting("remember_me", remember)
        principal = result.principal

        if remember:
            backend = self.auth.remember_user(principal.username)
            if backend == "keyring":
                log.info("remember-me enabled (OS keyring)")
            elif backend == "file":
                log.warning("remember-me enabled using the local obfuscated file")
            else:
                log.error("remember-me could not be stored; login will be required again")
                self.store.set_setting("remember_me", False)
        else:
            # Unticking the box revokes the saved login immediately.
            self.auth.forget_remembered()

        self.password_input.clear()
        self.logged_in.emit(result)

    def reset(self) -> None:
        """Called after a logout so the form is clean."""
        self.password_input.clear()
        self.error_label.setVisible(False)
        self.remember_check.setChecked(bool(self.store.get_setting("remember_me", False)))
        self.username_input.setFocus()
        self.saved_box.setVisible(False)
        self._prefill_remembered_username()
